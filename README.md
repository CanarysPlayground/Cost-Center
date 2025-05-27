# Cost-Center
#This repository helps to add users in cost center of Github Enterprise Account

Below are the steps to add users to Cost Center of Github Enterprise Account

Step-1: Navigate to 'your enterprises' and then select your enterprise account.  Make sure that you have Enterprise Owner, Organization Owner or billing manager permissions.
Step-2: Click on Billing and Licensing and click on cost centers and create new cost center.
Step-3: Click on edit of the cost center and Add Organization and Repository.
Step-4: You can add members either by rest API or by executing the script.
Step-5: If you want to add user through Rest API you must generate Classic token with admin read and write permissions.
Then change the parameters of curl command as present in REST API endpoints for enterprise billing - GitHub Enterprise Cloud Docs
Step-6: If you want to use the script to add users to cost center then you can use python.py script to add users.
Step-7: Make sure you are saving the users.csv file in same directory as of python.py script. And then run the script.
