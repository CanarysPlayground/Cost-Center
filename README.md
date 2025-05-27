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

1. Make sure both `cost-center.py` and `users.csv` are in the same directory.
2. Populate `users.csv` with the list of users you want to add.
3. Run the script:
    ```sh
    python cost-center.py
    ```
4. The script will process the CSV and add users to the specified cost center.


