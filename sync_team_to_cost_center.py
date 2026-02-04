import os
import csv
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


def fetch_enterprise_team_member_logins(base: str, enterprise: str, team_slug: str, token: str) -> list[str]:
    url = f"{base}/enterprises/{enterprise}/teams/{team_slug}/memberships"

    logins: list[str] = []
    next_url = url
    page = 1

    while next_url:
        resp = requests.get(next_url, headers=github_headers(token), timeout=30)
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

    # de-dup while preserving order
    seen = set()
    unique = []
    for x in logins:
        if x not in seen:
            seen.add(x)
            unique.append(x)
    return unique


def add_user_to_cost_center(base: str, enterprise: str, cost_center_id: str, token: str, login: str) -> tuple[bool, str]:
    """
    Returns (success, message).
    Treats "already added" as a skip (success=False but not an error), depending on API response.
    """
    url = f"{base}/enterprises/{enterprise}/settings/billing/cost-centers/{cost_center_id}/resource"
    payload = {"users": [login]}

    resp = requests.post(url, headers=github_headers(token), json=payload, timeout=30)

    # Most common: created/accepted
    if resp.status_code in (200, 201, 202, 204):
        return True, f"Added {login} (HTTP {resp.status_code})"

    # Common patterns when already present: 409 conflict, or 422 validation depending on backend behavior
    if resp.status_code in (409, 422):
        body = (resp.text or "")[:500].lower()
        if "already" in body or "exists" in body or "has already been taken" in body or "conflict" in body:
            return False, f"Skip {login}: already in cost center (HTTP {resp.status_code})"
        return False, f"Skip {login}: not added (HTTP {resp.status_code}) body={resp.text[:500]}"

    # Anything else: hard error
    raise SystemExit(
        f"Add to cost center failed for {login}\n"
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

    missing = [k for k in ("GITHUB_ENTERPRISE", "GITHUB_TEAM_SLUG", "GITHUB_COST_CENTER_ID", "GITHUB_TOKEN") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"Missing required env keys: {', '.join(missing)}")

    members = fetch_enterprise_team_member_logins(base, enterprise, team_slug, token)
    print(f"Total unique team members fetched: {len(members)}")

    results = []
    added = 0
    skipped = 0

    for login in members:
        ok, msg = add_user_to_cost_center(base, enterprise, cost_center_id, token, login)
        print(msg)
        results.append({"login": login, "result": "added" if ok else "skipped", "message": msg})
        if ok:
            added += 1
        else:
            skipped += 1

    # write a small report CSV as an artifact in Actions
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["login", "result", "message"])
        w.writeheader()
        w.writerows(results)

    print(f"Done. added={added}, skipped={skipped}, report={output_csv}")


if __name__ == "__main__":
    main()
