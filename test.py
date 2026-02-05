import os
import csv
import time
import random
import requests
from dotenv import load_dotenv


def parse_next_link(link_header: str) -> str | None:
    if not link_header:
        return None
    parts = [p.strip() for p in link_header.split(",")]
    for part in parts:
        if 'rel="next"' in part:
            start = part.find("<") + 1
            end = part.find(">")
            if start > 0 and end > start:
                return part[start:end]
    return None


def extract_memberships(payload):
    """
    The memberships endpoint can return either:
    - list: [ {membership}, ... ]
    - dict: { memberships: [ ... ] } (or other common wrapper keys)
    """
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in ("memberships", "items", "value", "data"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]

        for v in payload.values():
            if isinstance(v, list) and (len(v) == 0 or isinstance(v[0], dict)):
                return v

    return []


def github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def is_secondary_rate_limit(resp: requests.Response) -> bool:
    # Secondary rate limits often come as 403 with a message like:
    # "You have exceeded a secondary rate limit..."
    try:
        j = resp.json()
        msg = (j.get("message") or "").lower()
    except Exception:
        msg = (resp.text or "").lower()
    return "secondary rate limit" in msg


def request_with_backoff(
    method: str,
    url: str,
    *,
    headers: dict,
    json=None,
    timeout: int = 30,
    max_retries: int = 8,
    max_backoff_seconds: int = 60,
) -> requests.Response:
    """
    Retries on:
    - 429 Too Many Requests
    - 403 with "secondary rate limit" message (GitHub abuse/secondary throttling)

    Respects Retry-After when present.
    Uses exponential backoff + jitter otherwise.
    """
    last: requests.Response | None = None

    for attempt in range(max_retries):
        resp = requests.request(method, url, headers=headers, json=json, timeout=timeout)
        last = resp

        if resp.status_code not in (403, 429):
            return resp

        retry_after = resp.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            sleep_s = int(retry_after)
        else:
            sleep_s = min(max_backoff_seconds, 2**attempt) + random.uniform(0, 1.5)

        if resp.status_code == 429 or is_secondary_rate_limit(resp):
            # Helpful debug context (don’t print huge bodies)
            body_preview = (resp.text or "")[:200].replace("\n", " ")
            print(
                f"Rate limited (HTTP {resp.status_code}). "
                f"Sleeping {sleep_s:.1f}s then retrying. "
                f"url={url} body_preview={body_preview!r}"
            )
            time.sleep(sleep_s)
            continue

        # If it's a 403 for some other reason, do not retry.
        return resp

    # Exhausted retries: return last response so caller can raise a useful error.
    assert last is not None
    return last


def fetch_enterprise_team_member_logins(base: str, enterprise: str, team_slug: str, token: str) -> list[str]:
    url = f"{base}/enterprises/{enterprise}/teams/{team_slug}/memberships"

    logins: list[str] = []
    next_url = url
    page = 1

    while next_url:
        resp = request_with_backoff("GET", next_url, headers=github_headers(token), timeout=30)

        if resp.status_code != 200:
            raise SystemExit(
                f"Fetch memberships failed (page {page})\n"
                f"URL: {next_url}\n"
                f"HTTP {resp.status_code}\n"
                f"Response (first 1000 chars):\n{resp.text[:1000]}"
            )

        try:
            payload = resp.json()
        except Exception:
            raise SystemExit(
                f"Non-JSON response (page {page})\n"
                f"URL: {next_url}\n"
                f"HTTP {resp.status_code}\n"
                f"Body (first 1000 chars):\n{resp.text[:1000]}"
            )

        memberships = extract_memberships(payload)
        print(f"Fetched membership page {page}: {len(memberships)} items")

        for m in memberships:
            if not isinstance(m, dict):
                continue
            user = m.get("user") or {}
            login = None
            if isinstance(user, dict):
                login = user.get("login")
            login = login or m.get("login")
            if login:
                logins.append(login)

        next_url = parse_next_link(resp.headers.get("Link"))
        page += 1
        if page > 200:
            raise SystemExit("Aborting: too many pages (possible pagination loop).")

        # Gentle pacing during pagination (helps avoid secondary throttling on large orgs)
        time.sleep(random.uniform(0.1, 0.3))

    # de-dup while preserving order
    seen = set()
    unique = []
    for x in logins:
        if x not in seen:
            seen.add(x)
            unique.append(x)
    return unique


def chunked(xs: list[str], size: int) -> list[list[str]]:
    return [xs[i : i + size] for i in range(0, len(xs), size)]


def add_users_to_cost_center_bulk(
    base: str,
    enterprise: str,
    cost_center_id: str,
    token: str,
    logins: list[str],
    *,
    max_retries: int = 8,
) -> tuple[bool, str]:
    """
    Returns (success, message).
    Attempts to add a batch of users in one call to reduce request volume.

    Treats common "already added" patterns as a skip/soft-failure.
    """
    url = f"{base}/enterprises/{enterprise}/settings/billing/cost-centers/{cost_center_id}/resource"
    payload = {"users": logins}

    resp = request_with_backoff(
        "POST",
        url,
        headers=github_headers(token),
        json=payload,
        timeout=30,
        max_retries=max_retries,
    )

    # Most common: created/accepted
    if resp.status_code in (200, 201, 202, 204):
        return True, f"Added batch size={len(logins)} (HTTP {resp.status_code})"

    # Common patterns when already present: 409 conflict, or 422 validation depending on backend behavior
    if resp.status_code in (409, 422):
        body = (resp.text or "")[:800].lower()
        if "already" in body or "exists" in body or "has already been taken" in body or "conflict" in body:
            return False, f"Skip batch size={len(logins)}: already present (HTTP {resp.status_code})"
        return False, f"Skip batch size={len(logins)}: not added (HTTP {resp.status_code}) body={(resp.text or '')[:800]}"

    # Anything else: hard error
    raise SystemExit(
        f"Add to cost center failed for batch size={len(logins)}\n"
        f"URL: {url}\n"
        f"HTTP {resp.status_code}\n"
        f"Response (first 1000 chars):\n{resp.text[:1000]}"
    )


def main():
    load_dotenv()

    base = os.getenv("GITHUB_API_BASE", "https://api.github.com").rstrip("/")
    enterprise = os.getenv("GITHUB_ENTERPRISE")
    team_slug = os.getenv("GITHUB_TEAM_SLUG")
    cost_center_id = os.getenv("GITHUB_COST_CENTER_ID")
    token = os.getenv("GITHUB_TOKEN")

    output_csv = os.getenv("OUTPUT_CSV", "synced_users.csv")

    # Tuning knobs (safe defaults for ~1000 users)
    chunk_size = int(os.getenv("CHUNK_SIZE", "25"))  # try 25 first; you can raise to 50 if stable
    inter_batch_min = float(os.getenv("INTER_BATCH_SLEEP_MIN", "0.5"))
    inter_batch_max = float(os.getenv("INTER_BATCH_SLEEP_MAX", "1.5"))
    max_retries = int(os.getenv("MAX_RETRIES", "8"))

    missing = [
        k
        for k in ("GITHUB_ENTERPRISE", "GITHUB_TEAM_SLUG", "GITHUB_COST_CENTER_ID", "GITHUB_TOKEN")
        if not os.getenv(k)
    ]
    if missing:
        raise SystemExit(f"Missing required env keys: {', '.join(missing)}")

    members = fetch_enterprise_team_member_logins(base, enterprise, team_slug, token)
    print(f"Total unique team members fetched: {len(members)}")

    batches = chunked(members, chunk_size)
    print(f"Adding users in {len(batches)} batches of up to {chunk_size}")

    results = []
    added = 0
    skipped = 0

    for idx, batch in enumerate(batches, start=1):
        ok, msg = add_users_to_cost_center_bulk(
            base,
            enterprise,
            cost_center_id,
            token,
            batch,
            max_retries=max_retries,
        )
        print(f"[batch {idx}/{len(batches)}] {msg}")

        # Record per-login outcome (message is batch-level)
        for login in batch:
            results.append({"login": login, "result": "added" if ok else "skipped", "message": msg})

        if ok:
            added += len(batch)
        else:
            skipped += len(batch)

        # Gentle pacing between batches to reduce secondary rate limiting
        time.sleep(random.uniform(inter_batch_min, inter_batch_max))

    # write a small report CSV as an artifact in Actions
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["login", "result", "message"])
        w.writeheader()
        w.writerows(results)

    print(f"Done. added={added}, skipped={skipped}, report={output_csv}")


if __name__ == "__main__":
    main()
