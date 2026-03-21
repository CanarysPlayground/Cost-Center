# Cost-Center

![Python Version](https://img.shields.io/badge/python-3.x-blue)

## Overview

This repository helps administrators manage cost centers in a GitHub Enterprise Account. It provides steps and scripts to add users to cost centers, associate organizations and repositories, and streamline enterprise billing.

## Prerequisites

- Python 3.x installed on your machine
- Enterprise Owner or Billing Manager permissions on GitHub
- GitHub Classic token with admin, read, and write permissions

## Installation

1. **Clone the repository:**
    ```sh
    git clone https://github.com/CanarysPlayground/Cost-Center.git
    cd Cost-Center
    ```
2. **(Optional) Install dependencies:**  
   If there are Python dependencies, install them:
    ```sh
    pip install -r requirements.txt
    ```

## Usage

### Manual Steps for Creating a Cost Center

1. Navigate to **Your Enterprises** and select your enterprise account.
2. Ensure you have the necessary permissions (Enterprise Owner or Billing Manager).
3. Go to **Billing and Licensing** > **Cost Centers** and create a new cost center.
4. Edit the cost center to add users as needed.

### Adding Users via GitHub REST API

1. Generate a Classic Personal Access Token on GitHub with admin, read, and write permissions.
2. Use the appropriate REST API endpoints for enterprise billing as described in [GitHub's documentation](https://docs.github.com/en/enterprise-cloud@latest/rest/enterprise-admin/billing?apiVersion=2022-11-28#add-users-to-a-cost-center).
3. Example `curl` command:
 ```sh
    
  curl -L \
  -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer <YOUR-TOKEN>" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/enterprises/ENTERPRISE/settings/billing/cost-centers/COST_CENTER_ID/resource \
  -d '{"users":["monalisa"]}'
  
  ```
   Replace placeholders with your details.

### Adding Users via Python Script

Make sure both `cost-center.py` and `users.csv` are in the same directory.
## Inputs Required for Python Script Execution

To successfully run the `cost-center.py` script, you must provide the following inputs:

1. **GitHub Token**
   - A Classic Personal Access Token with `admin`, `read`, and `write` permissions.
   - Replace the value of `GITHUB_TOKEN` in `cost-center.py` with your actual token, or modify the script to read from an environment 
      variable for better security.

2. **Enterprise Slug Name**
   - The slug (short name) of your GitHub Enterprise (e.g., `my-enterprise`).
   - Set the `ENTERPRISE` variable in the script.

3. **Cost Center ID**
   - The unique identifier for the cost center you wish to add users to.
   - Set the `COST_CENTER_ID` variable in the script.

4. **CSV File of Users**
   - Prepare a `users.csv` file in the same directory as the script.
   - The first row should be a header (e.g., `username`), and each subsequent row should contain a GitHub username.
   - **Example:**
     ```csv
     username
     johndoe
     janedoe
     anotheruser
     ```

**How to Set Inputs:**
- You can either edit the variables directly in `cost-center.py`, or for improved security and flexibility, modify the script to read these values from environment variables or prompt for them at runtime.

**Example Variable Assignment in Script:**
```python
GITHUB_TOKEN = "your_personal_access_token"
ENTERPRISE = "your_enterprise_slug"
COST_CENTER_ID = "cost_center_id"
```

5. Run the script:
    ```sh
    python cost-center.py
    ```
6. The script will process the CSV and add users to the specified cost center.

---

## Syncing Enterprise Teams to Cost Centers (`new_sync.py`)

The `new_sync.py` script (run automatically by the GitHub Actions workflow) syncs one or more enterprise teams to their corresponding cost centers.

> **Important – GitHub exclusive membership:** A user can only belong to **one** cost center at a time. Adding a user to a new cost center automatically removes them from their previous one. The multi-mapping mode accounts for this.

### Single cost-center mode (backward compatible)

Set the following repository secrets and run the workflow as before:

| Secret | Description |
|--------|-------------|
| `ENTERPRISE` | Enterprise slug (e.g. `canarys`) |
| `TEAM_SLUG` | Enterprise team slug whose members to sync |
| `COST_CENTER_ID` | UUID of the target cost center |
| `TOKEN` | Personal access token |

### Multi-cost-center mode (recommended for overlapping memberships)

When users are members of multiple teams and need to be split across cost centers (e.g. 3 users from `MarchCC` belong to `PR1`), use the `COST_CENTER_MAPPINGS` secret instead of `TEAM_SLUG` / `COST_CENTER_ID`.

**How it works:**
1. Mappings are processed **in order**.
2. Once a user is assigned to a cost center, they are **skipped** for all subsequent mappings — preventing GitHub's exclusive-membership behaviour from moving them back.
3. List higher-priority cost centers **first** (e.g. `PR1` before `MarchCC`).

#### Example scenario

- `MarchCC` has 8 users.  
- 3 of those users should be in `PR1` (budget $50) and must **not** consume MarchCC budget.  
- The remaining 5 stay in `MarchCC` (budget $0).

**Step 1 – Create two enterprise teams:**

| Team | Members |
|------|---------|
| `pr1-team` | The 3 users that belong to PR1 |
| `march-team` | All 8 users (or just the 5 remaining ones) |

**Step 2 – Set the `COST_CENTER_MAPPINGS` secret** (in *Settings → Secrets and variables → Actions*):

```json
[
  {"team_slug": "pr1-team",   "cost_center_id": "<PR1-cost-center-uuid>"},
  {"team_slug": "march-team", "cost_center_id": "<MarchCC-cost-center-uuid>"}
]
```

Because `PR1` is listed first, those 3 users are claimed by PR1 and will **not** be re-added to MarchCC when the `march-team` mapping runs.

**Step 3 – Leave `TEAM_SLUG` and `COST_CENTER_ID` secrets empty** (or remove them). When `COST_CENTER_MAPPINGS` is set it takes priority.

**Step 4 – Run the workflow** (`Actions → Sync_EntTeam_Cost_Center → Run workflow`).

#### Dry-run

To preview changes without applying them, set the `DRY_RUN` environment variable to `true` in the workflow step or locally:

```sh
DRY_RUN=true COST_CENTER_MAPPINGS='[...]' python new_sync.py
```

#### Report artifact

After each run the workflow uploads `synced_users.csv` as an artifact. The CSV now includes `team` and `cost_center` columns so you can see exactly which mapping each user was processed under.
