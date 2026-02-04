import csv
import json
import sys
import urllib.request
import urllib.error

# ====== CONFIG (you asked to keep these in the script) ======
TOKEN = "ghp_xaQrYLlH9HHQtCEq992kF2gU"
DEFAULT_ENTERPRISE = "canarys"
DEFAULT_TEAM = "test"
API_VERSION = "2022-11-28"
# ===========================================================

def post(url: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": API_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body

def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "members.csv"

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"username"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise SystemExit("CSV must include at least a 'username' column. Optional: 'enterprise', 'team'.")

        for row in reader:
            username = (row.get("username") or "").strip()
            if not username:
                continue

            enterprise = (row.get("enterprise") or DEFAULT_ENTERPRISE).strip()
            team = (row.get("team") or DEFAULT_TEAM).strip()

            url = f"https://api.github.com/enterprises/{enterprise}/teams/{team}/memberships/add"
            status, body = post(url, {"usernames": [username]})

            print(f"{enterprise}/{team}: add {username} -> HTTP {status}")
            if body:
                print(body)

if __name__ == "__main__":
    main()