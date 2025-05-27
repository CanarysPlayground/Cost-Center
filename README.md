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


