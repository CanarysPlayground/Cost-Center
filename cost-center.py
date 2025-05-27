import csv
import subprocess
import logging
import os

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# GitHub Token and Cost Center ID
GITHUB_TOKEN = "CLASSIC_TOKEN"
ENTERPRISE = "Slug name"
COST_CENTER_ID = "Cost center ID"

# Read CSV and get list of users
def read_users_from_csv(csv_file):
    users = []
    with open(csv_file, mode='r') as file:
        csv_reader = csv.reader(file)
        next(csv_reader)  # Skip header
        for row in csv_reader:
            users.append(row[0])
    return users

# Function to add users to the cost center
def add_users_to_cost_center(users):
    for user in users:
        command = [
            "curl", "-L", "-X", "POST",
            "-H", "Accept: application/vnd.github+json",
            "-H", f"Authorization: Bearer {GITHUB_TOKEN}",
            "-H", "X-GitHub-Api-Version: 2022-11-28",
            f"https://api.github.com/enterprises/{ENTERPRISE}/settings/billing/cost-centers/{COST_CENTER_ID}/resource",
            "-d", f'{{"users":["{user}"]}}'
        ]
        
        # Run the command and capture the output
        try:
            logging.info(f"Adding user {user} to cost center...")
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode == 0:
                logging.info(f"Successfully added {user} to cost center.")
                logging.info(result.stdout)
            else:
                logging.error(f"Failed to add {user} to cost center: {result.stderr}")
        except Exception as e:
            logging.error(f"Error occurred while adding {user}: {e}")

# Main function to execute the script
def main():
    csv_file = "users.csv"  # Update with your CSV file name
    users = read_users_from_csv(csv_file)
    add_users_to_cost_center(users)

if __name__ == "__main__":
    main()
