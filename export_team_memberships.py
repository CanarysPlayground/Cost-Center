import os
import csv
import json
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
        # common wrapper keys
        for key in ("memberships", "items", "value", "data"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]

        # sometimes it could be nested one more level
        # try to find the first list-of-dicts that looks like memberships
        for v in payload.values():
            if isinstance(v, list) and (len(v) == 0 or isinstance(v[0], dict)):
                return v

    return []


def main():
    load_dotenv()

    base = os.getenv("GITHUB_API_BASE", "https://api.github.com").rstrip("/")
    enterprise = os.getenv("GITHUB_ENTERPRISE")
    team_slug = os.getenv("GITHUB_TEAM_SLUG")
    token = os.getenv("GITHUB_TOKEN")
    output_csv = os.getenv("OUTPUT_CSV", "team_memberships.csv")

    missing = [k for k in ("GITHUB_ENTERPRISE", "GITHUB_TEAM_SLUG", "GITHUB_TOKEN") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"Missing required .env keys: {', '.join(missing)}")

    url = f"{base}/enterprises/{enterprise}/teams/{team_slug}/memberships"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    rows = []
    next_url = url
    page = 1

    while next_url:
        resp = requests.get(next_url, headers=headers, timeout=30)

        # hard-fail on non-200 with helpful output
        if resp.status_code != 200:
            raise SystemExit(
                f"Request failed (page {page})\n"
                f"URL: {next_url}\n"
                f"HTTP {resp.status_code}\n"
                f"Response (first 1000 chars):\n{resp.text[:1000]}"
            )

        # parse JSON safely
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

        # Debug info so you can see what is happening
        print(f"Fetched page {page}: memberships={len(memberships)}")

        for m in memberships:
            user = (m.get("user") or {}) if isinstance(m, dict) else {}
            rows.append(
                {
                    "login": user.get("login") or m.get("login"),
                    "id": user.get("id") or m.get("id"),
                    "html_url": user.get("html_url") or user.get("url"),
                    "role": m.get("role"),
                    "state": m.get("state"),
                }
            )

        next_url = parse_next_link(resp.headers.get("Link"))
        page += 1

        # safety: avoid infinite loops if Link header is weird
        if page > 200:
            raise SystemExit("Aborting: too many pages (possible pagination loop).")

    if not rows:
        # write the raw payload shape hint to help diagnose
        print("No memberships found. The API returned zero items.")
        print("Double-check enterprise/team slug, token permissions, and whether the team has members.")
    else:
        fieldnames = ["login", "id", "html_url", "role", "state"]
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        print(f"Wrote {len(rows)} rows to {output_csv}")


if __name__ == "__main__":
    main()