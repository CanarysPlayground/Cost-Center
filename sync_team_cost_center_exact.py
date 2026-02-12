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
    """Extract memberships from API response"""
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
    """Fetch all users from enterprise team"""
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
                f"Response: {resp.text[:1000]}"
            )

        try:
            payload = resp.json()
        except Exception:
            raise SystemExit(
                f"Non-JSON response (page {page})\n"
                f"URL: {next_url}\n"
                f"Body: {resp.text[:1000]}"
            )

        memberships = extract_memberships(payload)
        print(f"[TEAM] Fetched page {page}: {len(memberships)} members")

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
            raise SystemExit("Aborting: too many pages")

    # De-duplicate
    seen = set()
    unique = []
    for x in logins:
        if x not in seen:
            seen.add(x)
            unique.append(x)
    return unique


def fetch_cost_center_users(base: str, enterprise: str, cost_center_id: str, token: str) -> list[str]:
    """Fetch all users currently in the cost center"""
    url = f"{base}/enterprises/{enterprise}/settings/billing/cost-centers/{cost_center_id}"

    resp = requests.get(url, headers=github_headers(token), timeout=30)
    
    # If cost center doesn't exist, return empty list
    if resp.status_code == 404:
        print(f"[COST CENTER] Not found")
        return []
    
    if resp.status_code != 200:
        raise SystemExit(
            f"Fetch cost center users failed\n"
            f"URL: {url}\n"
            f"HTTP {resp.status_code}\n"
            f"Response: {resp.text[:1000]}"
        )

    try:
        payload = resp.json()
    except Exception:
        raise SystemExit(
            f"Non-JSON response from cost center\n"
            f"Body: {resp.text[:1000]}"
        )

    # Extract users from resources array
    logins: list[str] = []
    resources = payload.get("resources", [])
    
    print(f"[COST CENTER] Fetched {len(resources)} total resources")

    for resource in resources:
        if isinstance(resource, dict):
            resource_type = resource.get("type")
            name = resource.get("name")
            
            # DEBUG: Show each resource
            print(f"[DEBUG] Resource: type={resource_type}, name={name}")
            
            # Filter only User type resources
            if resource_type == "User":
                if name:
                    logins.append(name)

    # De-duplicate
    unique_logins = list(set(logins))
    
    # DEBUG: Show extracted users
    print(f"[COST CENTER] Extracted user logins: {sorted(unique_logins)}")
    
    return unique_logins


def add_user_to_cost_center(base: str, enterprise: str, cost_center_id: str, token: str, login: str) -> tuple[bool, str]:
    """Add user to cost center"""
    url = f"{base}/enterprises/{enterprise}/settings/billing/cost-centers/{cost_center_id}/resources"
    payload = {"users": [login]}

    resp = requests.post(url, headers=github_headers(token), json=payload, timeout=30)

    if resp.status_code in (200, 201, 202, 204):
        return True, f"Added {login}"

    if resp.status_code in (409, 422):
        body = (resp.text or "")[:500].lower()
        if "already" in body or "exists" in body:
            return False, f"Skip {login}: already exists"
        return False, f"Skip {login}: {resp.text[:500]}"

    raise SystemExit(
        f"Add to cost center failed for {login}\n"
        f"URL: {url}\n"
        f"HTTP {resp.status_code}\n"
        f"Response: {resp.text[:1000]}"
    )


def remove_user_from_cost_center(base: str, enterprise: str, cost_center_id: str, token: str, login: str) -> tuple[bool, str]:
    """Remove user from cost center"""
    # Use singular 'resource' instead of plural 'resources' endpoint.
    # The /resource endpoint is the correct API endpoint for removing individual users,
    # while /resources may be used for batch operations. This was confirmed through API testing
    # where /resources returned 404 or 400 "No resources to remove" errors.
    url = f"{base}/enterprises/{enterprise}/settings/billing/cost-centers/{cost_center_id}/resource"
    payload = {"users": [login]}

    print(f"[DEBUG] Attempting to remove {login} from {url}")
    
    resp = requests.delete(url, headers=github_headers(token), json=payload, timeout=30)
    
    # Show first 500 chars of response for debugging (consistent with error handling below)
    print(f"[DEBUG] DELETE response: status={resp.status_code}, body={resp.text[:500]}")

    if resp.status_code in (200, 201, 202, 204):
        return True, f"Removed {login}"

    # 400 with "No resources to remove" means user not in cost center
    if resp.status_code == 400:
        body = (resp.text or "")[:500].lower()
        if "no resources" in body:
            return False, f"Skip {login}: not in cost center (API says no resources to remove)"
        return False, f"Skip {login}: {resp.text[:500]}"
    
    if resp.status_code == 404:
        return False, f"Skip {login}: endpoint or user not found (HTTP 404)"

    raise SystemExit(
        f"Remove from cost center failed for {login}\n"
        f"URL: {url}\n"
        f"HTTP {resp.status_code}\n"
        f"Response: {resp.text[:1000]}"
    )


def main():
    load_dotenv()

    base = os.getenv("GITHUB_API_BASE", "https://api.github.com").rstrip("/")
    enterprise = os.getenv("GITHUB_ENTERPRISE")
    team_slug = os.getenv("GITHUB_TEAM_SLUG")
    cost_center_id = os.getenv("GITHUB_COST_CENTER_ID")
    token = os.getenv("GITHUB_TOKEN")

    output_csv = os.getenv("OUTPUT_CSV", "sync_report.csv")

    missing = [k for k in ("GITHUB_ENTERPRISE", "GITHUB_TEAM_SLUG", "GITHUB_COST_CENTER_ID", "GITHUB_TOKEN") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"Missing required env keys: {', '.join(missing)}")

    # Fetch users from enterprise team
    print("\n=== Fetching Enterprise Team Members ===")
    team_members = fetch_enterprise_team_member_logins(base, enterprise, team_slug, token)
    print(f"Total team members: {len(team_members)}")
    print(f"[DEBUG] Team members: {sorted(team_members)}")

    # Fetch users currently in cost center
    print("\n=== Fetching Cost Center Users ===")
    cost_center_users = fetch_cost_center_users(base, enterprise, cost_center_id, token)
    print(f"Total cost center users: {len(cost_center_users)}")
    # Debug output already added in fetch_cost_center_users

    # Calculate differences
    team_set = set(team_members)
    cost_center_set = set(cost_center_users)

    users_to_add = team_set - cost_center_set
    users_to_remove = cost_center_set - team_set
    users_already_synced = team_set & cost_center_set

    print(f"\n=== Sync Plan ===")
    print(f"Users to ADD: {len(users_to_add)} - {sorted(users_to_add)}")
    print(f"Users to REMOVE: {len(users_to_remove)} - {sorted(users_to_remove)}")
    print(f"Users already synced: {len(users_already_synced)} - {sorted(users_already_synced)}")

    results = []
    added_count = 0
    removed_count = 0
    error_count = 0

    # Add missing users
    print("\n=== Adding Users to Cost Center ===")
    for login in users_to_add:
        try:
            ok, msg = add_user_to_cost_center(base, enterprise, cost_center_id, token, login)
            print(f"  {msg}")
            results.append({"login": login, "action": "add", "status": "success" if ok else "skipped", "message": msg})
            if ok:
                added_count += 1
        except Exception as e:
            error_msg = f"Error adding {login}: {str(e)}"
            print(f"  {error_msg}")
            results.append({"login": login, "action": "add", "status": "error", "message": error_msg})
            error_count += 1

    # Remove extra users
    print("\n=== Removing Users from Cost Center ===")
    for login in users_to_remove:
        try:
            ok, msg = remove_user_from_cost_center(base, enterprise, cost_center_id, token, login)
            print(f"  {msg}")
            results.append({"login": login, "action": "remove", "status": "success" if ok else "skipped", "message": msg})
            if ok:
                removed_count += 1
        except Exception as e:
            error_msg = f"Error removing {login}: {str(e)}"
            print(f"  {error_msg}")
            results.append({"login": login, "action": "remove", "status": "error", "message": error_msg})
            error_count += 1

    # Record already synced users
    for login in users_already_synced:
        results.append({"login": login, "action": "none", "status": "already_synced", "message": "Already in sync"})

    # Write CSV report
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["login", "action", "status", "message"])
        w.writeheader()
        w.writerows(results)

    print(f"\n=== Summary ===")
    print(f"Added: {added_count}")
    print(f"Removed: {removed_count}")
    print(f"Already synced: {len(users_already_synced)}")
    print(f"Errors: {error_count}")
    print(f"Report saved to: {output_csv}")


if __name__ == "__main__":
    main()
