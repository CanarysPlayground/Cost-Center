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


def github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


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
    Memberships endpoint can return:
      - list: [ {...}, ... ]
      - dict wrapper: { memberships: [ ... ] } or similar
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


def fetch_enterprise_team_member_logins(base: str, enterprise: str, team_slug: str, token: str) -> list[str]:
    """
    Fetch all user logins in an enterprise team via:
      GET /enterprises/{enterprise}/teams/{team_slug}/memberships
    Handles pagination using Link header.
    """
    url = f"{base}/enterprises/{enterprise}/teams/{team_slug}/memberships"

    logins: list[str] = []
    next_url = url
    page = 1

    while next_url:
        resp = requests.get(next_url, headers=github_headers(token), timeout=30)
        if resp.status_code != 200:
            raise SystemExit(
                f"Fetch team memberships failed (page {page})\n"
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
        print(f"[TEAM] page={page} items={len(memberships)}")

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


def fetch_cost_center_users(base: str, enterprise: str, cost_center_id: str, token: str) -> list[str]:
    """
    Fetch cost center details via:
      GET /enterprises/{enterprise}/settings/billing/cost-centers/{cost_center_id}
    Then extract resources[] entries where type == "User" and take resource["name"] as login.
    """
    url = f"{base}/enterprises/{enterprise}/settings/billing/cost-centers/{cost_center_id}"
    resp = requests.get(url, headers=github_headers(token), timeout=30)

    if resp.status_code == 404:
        print("[COST_CENTER] not found (404); treating as empty.")
        return []

    if resp.status_code != 200:
        raise SystemExit(
            f"Fetch cost center failed\n"
            f"URL: {url}\n"
            f"HTTP {resp.status_code}\n"
            f"Response (first 1000 chars):\n{resp.text[:1000]}"
        )

    try:
        payload = resp.json()
    except Exception:
        raise SystemExit(
            f"Non-JSON response from cost center\n"
            f"URL: {url}\n"
            f"Body (first 1000 chars):\n{resp.text[:1000]}"
        )

    resources = payload.get("resources", [])
    print(f"[COST_CENTER] resources={len(resources)}")

    logins: list[str] = []
    for r in resources:
        if not isinstance(r, dict):
            continue
        if r.get("type") == "User":
            name = r.get("name")
            if name:
                logins.append(name)

    # de-dup
    return sorted(set(logins))


def add_user_to_cost_center(base: str, enterprise: str, cost_center_id: str, token: str, login: str) -> tuple[bool, str]:
    """
    Add a user to a cost center via:
      POST /enterprises/{enterprise}/settings/billing/cost-centers/{cost_center_id}/resource
    Body: {"users":[login]}
    """
    url = f"{base}/enterprises/{enterprise}/settings/billing/cost-centers/{cost_center_id}/resource"
    payload = {"users": [login]}

    resp = requests.post(url, headers=github_headers(token), json=payload, timeout=30)

    if resp.status_code in (200, 201, 202, 204):
        return True, f"Added {login} (HTTP {resp.status_code})"

    if resp.status_code in (409, 422):
        body = (resp.text or "")[:500].lower()
        if "already" in body or "exists" in body or "conflict" in body:
            return False, f"Skip {login}: already present (HTTP {resp.status_code})"
        return False, f"Skip {login}: not added (HTTP {resp.status_code}) body={resp.text[:500]}"

    raise SystemExit(
        f"Add to cost center failed for {login}\n"
        f"URL: {url}\n"
        f"HTTP {resp.status_code}\n"
        f"Response (first 1000 chars):\n{resp.text[:1000]}"
    )


def remove_user_from_cost_center(base: str, enterprise: str, cost_center_id: str, token: str, login: str) -> tuple[bool, str]:
    """
    Remove a user from a cost center via:
      DELETE /enterprises/{enterprise}/settings/billing/cost-centers/{cost_center_id}/resource
    Body: {"users":[login]}
    """
    url = f"{base}/enterprises/{enterprise}/settings/billing/cost-centers/{cost_center_id}/resource"
    payload = {"users": [login]}

    resp = requests.delete(url, headers=github_headers(token), json=payload, timeout=30)

    if resp.status_code in (200, 201, 202, 204):
        return True, f"Removed {login} (HTTP {resp.status_code})"

    # Some backends respond 400 when nothing to remove
    if resp.status_code in (400, 404, 409, 422):
        body = (resp.text or "")[:500].lower()
        if "no resources" in body or "not found" in body or "does not exist" in body:
            return False, f"Skip {login}: not present / nothing to remove (HTTP {resp.status_code})"
        return False, f"Skip {login}: not removed (HTTP {resp.status_code}) body={resp.text[:500]}"

    raise SystemExit(
        f"Remove from cost center failed for {login}\n"
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
    dry_run = os.getenv("DRY_RUN", "false").strip().lower() in ("1", "true", "yes")

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

            print("\n-- Fetching Enterprise Team Members --")
            team_members = fetch_enterprise_team_member_logins(base, enterprise, team_slug, token)
            print(f"[TEAM] total={len(team_members)}")
        else:
            # Direct user list — no enterprise team required.
            # De-dup while preserving order.
            seen: set[str] = set()
            team_members = []
            for u in direct_users:
                if u not in seen:
                    seen.add(u)
                    team_members.append(u)
            source_label = f"direct user list ({len(team_members)} users)"
            print(f"\n=== Syncing {source_label} -> cost center '{cost_center_id}' ===")
            print(f"[USERS] {team_members}")

        print("\n-- Fetching Cost Center Users --")
        cost_center_users = fetch_cost_center_users(base, enterprise, cost_center_id, token)
        print(f"[COST_CENTER] users={len(cost_center_users)}")

        team_set = set(team_members) - claimed_users
        cc_set = set(cost_center_users)

        users_to_add = sorted(team_set - cc_set)
        users_to_remove = sorted(cc_set - team_set)
        users_already_synced = sorted(team_set & cc_set)

        skipped_claimed = len(set(team_members)) - len(team_set)
        if skipped_claimed:
            print(
                f"[INFO] Skipping {skipped_claimed} user(s) already assigned to a "
                f"higher-priority cost center."
            )

        print("\n-- Sync Plan --")
        print(f"ADD ({len(users_to_add)}): {users_to_add}")
        print(f"REMOVE ({len(users_to_remove)}): {users_to_remove}")
        print(f"OK ({len(users_already_synced)}): {users_already_synced}")
        if dry_run:
            print("\n[DRY_RUN] No changes will be applied.")

        added_count = 0
        removed_count = 0
        error_count = 0

        print("\n-- Apply: Add missing users --")
        for login in users_to_add:
            if dry_run:
                msg = f"DRY_RUN would add {login}"
                print(msg)
                all_results.append({
                    "login": login, "source": team_slug or "(direct)", "cost_center": cost_center_id,
                    "action": "add", "status": "dry_run", "message": msg,
                })
                continue
            try:
                ok, msg = add_user_to_cost_center(base, enterprise, cost_center_id, token, login)
                print(msg)
                all_results.append({
                    "login": login, "source": team_slug or "(direct)", "cost_center": cost_center_id,
                    "action": "add", "status": "success" if ok else "skipped", "message": msg,
                })
                if ok:
                    added_count += 1
            except Exception as e:
                emsg = f"Error adding {login}: {e}"
                print(emsg)
                all_results.append({
                    "login": login, "source": team_slug or "(direct)", "cost_center": cost_center_id,
                    "action": "add", "status": "error", "message": emsg,
                })
                error_count += 1

        print("\n-- Apply: Remove extra users --")
        for login in users_to_remove:
            if dry_run:
                msg = f"DRY_RUN would remove {login}"
                print(msg)
                all_results.append({
                    "login": login, "source": team_slug or "(direct)", "cost_center": cost_center_id,
                    "action": "remove", "status": "dry_run", "message": msg,
                })
                continue
            try:
                ok, msg = remove_user_from_cost_center(base, enterprise, cost_center_id, token, login)
                print(msg)
                all_results.append({
                    "login": login, "source": team_slug or "(direct)", "cost_center": cost_center_id,
                    "action": "remove", "status": "success" if ok else "skipped", "message": msg,
                })
                if ok:
                    removed_count += 1
            except Exception as e:
                emsg = f"Error removing {login}: {e}"
                print(emsg)
                all_results.append({
                    "login": login, "source": team_slug or "(direct)", "cost_center": cost_center_id,
                    "action": "remove", "status": "error", "message": emsg,
                })
                error_count += 1

        for login in users_already_synced:
            all_results.append({
                "login": login, "source": team_slug or "(direct)", "cost_center": cost_center_id,
                "action": "none", "status": "already_synced", "message": "Already in sync",
            })

        # Mark all team members of this mapping as claimed so that subsequent
        # mappings do not attempt to re-assign them to a different cost center.
        claimed_users.update(team_members)

        print(f"\n-- Summary for '{cost_center_id}' --")
        print(f"  Added: {added_count}")
        print(f"  Removed: {removed_count}")
        print(f"  Already synced: {len(users_already_synced)}")
        print(f"  Errors: {error_count}")

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["login", "source", "cost_center", "action", "status", "message"])
        w.writeheader()
        w.writerows(all_results)

    print(f"\nDone. Report: {output_csv}")


if __name__ == "__main__":
    main()
