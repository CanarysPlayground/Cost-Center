import os
import csv
import json
import requests
from dotenv import load_dotenv

# Common Unicode "smart" / curly quote characters that editors and word
# processors substitute for plain ASCII double-quotes (U+0022).
_SMART_QUOTE_MAP = str.maketrans({
    "\u201C": '"',  # LEFT DOUBLE QUOTATION MARK  "
    "\u201D": '"',  # RIGHT DOUBLE QUOTATION MARK "
    "\u201E": '"',  # DOUBLE LOW-9 QUOTATION MARK „
    "\u2018": "'",  # LEFT SINGLE QUOTATION MARK  '
    "\u2019": "'",  # RIGHT SINGLE QUOTATION MARK '
    "\uFF02": '"',  # FULLWIDTH QUOTATION MARK ＂
    "\uFF07": "'",  # FULLWIDTH APOSTROPHE ＇
})

_COST_CENTER_MAPPINGS_EXAMPLE = (
    '[\n'
    '  {"cost_center_id": "<uuid>", "users": ["login1", "login2"]},\n'
    '  {"cost_center_id": "<uuid>", "team_slug": "team-name"}\n'
    ']'
)


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
    token = os.getenv("GITHUB_TOKEN")

    output_csv = os.getenv("OUTPUT_CSV", "synced_users.csv")

    # --- Resolve cost center mappings ---
    # COST_CENTER_MAPPINGS (JSON array) takes priority over the single-mapping env vars.
    #
    # Format:
    #   [
    #     {"team_slug": "pr1-team",   "cost_center_id": "<PR1-uuid>"},
    #     {"team_slug": "march-team", "cost_center_id": "<MarchCC-uuid>"}
    #   ]
    #
    # Mappings are processed in order.  A user that has already been assigned to
    # an earlier cost center is skipped for all subsequent ones, which prevents
    # GitHub's exclusive-membership behaviour from moving users back.  List the
    # cost centers that should "claim" shared users FIRST (e.g. PR1 before MarchCC).
    mappings_raw = os.getenv("COST_CENTER_MAPPINGS", "").strip()
    if mappings_raw:
        # Normalize curly/smart quotes that word processors and some browsers
        # substitute for plain ASCII double-quotes.  These are invisible in
        # most UIs but cause json.loads() to fail with "Expecting property
        # name enclosed in double quotes".
        normalized = mappings_raw.translate(_SMART_QUOTE_MAP)
        if normalized != mappings_raw:
            print(
                "[WARNING] COST_CENTER_MAPPINGS contained smart/curly quote "
                "characters that were automatically replaced with plain ASCII "
                'double-quotes ("). '
                "Use straight ASCII double-quotes when editing the secret to "
                "avoid this warning."
            )
        try:
            mappings = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"Invalid COST_CENTER_MAPPINGS JSON: {exc}\n"
                "Common causes:\n"
                '  • Smart/curly quotes (\u201c\u201d) instead of plain ASCII double-quotes (")\n'
                "  • Trailing comma after the last element in an object or array\n"
                "  • Single quotes (') used instead of double-quotes\n"
                "  • Unquoted key names\n"
                f"Expected format:\n{_COST_CENTER_MAPPINGS_EXAMPLE}"
            )
        if not isinstance(mappings, list) or len(mappings) == 0:
            raise SystemExit("COST_CENTER_MAPPINGS must be a non-empty JSON array.")
        for i, m in enumerate(mappings):
            if not m.get("cost_center_id"):
                raise SystemExit(
                    f"COST_CENTER_MAPPINGS entry #{i} is missing 'cost_center_id': {m}"
                )
            has_team = bool(m.get("team_slug"))
            has_users = isinstance(m.get("users"), list) and len(m["users"]) > 0
            if not has_team and not has_users:
                raise SystemExit(
                    f"COST_CENTER_MAPPINGS entry #{i} must have either 'team_slug' "
                    f"or 'users' (non-empty list of logins): {m}"
                )
    else:
        # Backward-compatible single-mapping mode
        team_slug = os.getenv("GITHUB_TEAM_SLUG")
        cost_center_id = os.getenv("GITHUB_COST_CENTER_ID")
        missing = [
            k for k, v in {
                "GITHUB_ENTERPRISE": enterprise,
                "GITHUB_TEAM_SLUG": team_slug,
                "GITHUB_COST_CENTER_ID": cost_center_id,
                "GITHUB_TOKEN": token,
            }.items() if not v
        ]
        if missing:
            raise SystemExit(f"Missing required env keys: {', '.join(missing)}")
        mappings = [{"team_slug": team_slug, "cost_center_id": cost_center_id}]

    missing_global = [
        k for k, v in {"GITHUB_ENTERPRISE": enterprise, "GITHUB_TOKEN": token}.items() if not v
    ]
    if missing_global:
        raise SystemExit(f"Missing required env keys: {', '.join(missing_global)}")

    all_results = []
    # Track users already assigned to a higher-priority cost center so they are
    # not re-added to a later one.  GitHub cost centers have exclusive membership:
    # adding a user to a new cost center silently removes them from the old one.
    claimed_users: set[str] = set()

    for mapping in mappings:
        cost_center_id = mapping["cost_center_id"]
        team_slug = mapping.get("team_slug")
        direct_users: list[str] = mapping.get("users", [])

        if team_slug:
            source_label = f"team '{team_slug}'"
            print(f"\n=== Syncing {source_label} -> cost center '{cost_center_id}' ===")
            members = fetch_enterprise_team_member_logins(base, enterprise, team_slug, token)
            print(f"Total unique team members fetched: {len(members)}")
        else:
            # Direct user list — no enterprise team required.
            # De-dup while preserving order.
            seen: set[str] = set()
            members = []
            for u in direct_users:
                if u not in seen:
                    seen.add(u)
                    members.append(u)
            source_label = f"direct user list ({len(members)} users)"
            print(f"\n=== Syncing {source_label} -> cost center '{cost_center_id}' ===")
            print(f"[USERS] {members}")

        # Skip users already claimed by an earlier (higher-priority) cost center.
        members_to_sync = [login for login in members if login not in claimed_users]
        skipped_claimed = len(members) - len(members_to_sync)
        if skipped_claimed:
            print(
                f"[INFO] Skipping {skipped_claimed} user(s) already assigned to a "
                f"higher-priority cost center."
            )

        added = 0
        skipped = 0

        for login in members_to_sync:
            ok, msg = add_user_to_cost_center(base, enterprise, cost_center_id, token, login)
            print(msg)
            all_results.append({
                "login": login,
                "source": team_slug or "(direct)",
                "cost_center": cost_center_id,
                "result": "added" if ok else "skipped",
                "message": msg,
            })
            if ok:
                added += 1
            else:
                skipped += 1

        # Mark all members of this mapping as claimed so that subsequent mappings
        # do not attempt to re-assign them to a different cost center.
        claimed_users.update(members)

        print(f"  added={added}, skipped={skipped}")

    # write a small report CSV as an artifact in Actions
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["login", "source", "cost_center", "result", "message"])
        w.writeheader()
        w.writerows(all_results)

    print(f"Done. report={output_csv}")


if __name__ == "__main__":
    main()
