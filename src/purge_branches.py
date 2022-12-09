""" Script to find stale branches and notify if delete if they are older than 150 days 
"""
import argparse
import logging
import os
import sys
import datetime

import requests

KEEP_ALIVE_PREFIX = "keep-alive-"
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
GITHUB_API_URL = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 10


def add_branch_slack_reminders(branch, slack_reminder):
    """Add branch to list of user email"""
    if branch['target']['author']['email'] not in slack_reminder:
        slack_reminder[branch['target']['author']['email']] = []
    slack_reminder[branch['target']['author']['email']].append(branch['name'])

def delete_branches(args,branches):
    """Delete branch"""
    for branch in branches:
        logging.info(f"Deleting branch {branch['name']}")
        url = GITHUB_API_URL+"repos/"+args.gh_repo+"git/refs/"+branch['name']
        headers = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': f'Bearer {args.gh_token}',
        }
        try:
            response = requests.delete(url, headers=headers)
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            logging.error(err)

def grab_all_branches(args, page = "", branches = []) -> str:
    """Grab all branches from github"""
    repo_owner, repo_name = args.gh_repo.split('/')
    query = """{repository(owner: \"%s\", name: \"%s\") {
        refs(first: 100, refPrefix: \"refs/heads/\"%s) {
        nodes {
            name
            associatedPullRequests(first:1){
                nodes {
                    state
                }
            }
            target {
            ... on Commit {
                oid
                committedDate
                author {
                    name
                    email
                }
                
            }
            }
        }
        pageInfo {
            endCursor
            hasNextPage
            hasPreviousPage
        }
        }
    }
    }""" % (repo_owner, repo_name, page)
    headers = {
    'Accept': 'application/vnd.github.v3+json',
    'Authorization': f'Bearer {args.gh_token}',
    }
    try:
        response = requests.post(GITHUB_GRAPHQL_URL, json={'query': query}, headers=headers)
        response.raise_for_status()
        data = response.json()['data']
        branches.extend(data['repository']['refs']['nodes'])
        if data['repository']['refs']['pageInfo']['hasNextPage']:
            page = ", after: \"%s\"" % data['repository']['refs']['pageInfo']['endCursor']
            return grab_all_branches(args, page, branches)
        else:
            return branches
    except requests.exceptions.HTTPError as err:
        logging.error(err)
        sys.exit(1)
        
def triage_branches(args, branches):
    """Triage the branches"""
    branches_to_delete = []
    slack_reminder = {}

    for branch in branches:
        # ignore branches with keep-alive prefix
        if branch['name'].startswith(KEEP_ALIVE_PREFIX): 
            continue
        # ignore branches with open PRs
        if branch['associatedPullRequests']['nodes']:
            if branch['associatedPullRequests']['nodes'][0]['state'] == 'OPEN':
                continue
        lastBranchCommit = datetime.datetime.strptime(branch['target']['committedDate'], '%Y-%m-%dT%H:%M:%SZ')
        if lastBranchCommit < datetime.datetime.today() - datetime.timedelta(days=args.days_delete):
            branches_to_delete.append(branch)
        elif lastBranchCommit < datetime.datetime.today() - datetime.timedelta(days=args.days_slack):
            email = branch['target']['author']['email']
            if email not in slack_reminder:
                slack_reminder[email] = []
            slack_reminder[email].append(branch)

    if branches_to_delete:
        delete_branches(args, branches_to_delete)
    if slack_reminder:
        send_slack_message(args, slack_reminder)

def get_slack_user_id(args, email):
    """Get slack user id"""
    try:
        response = requests.get("https://slack.com/api/users.lookupByEmail?email="+email, headers={'Authorization': f'Bearer {args.slack_token}'})
        response.raise_for_status()
        if response.json()['ok']:
            return response.json()['user']['id']
        return None
    except requests.exceptions.HTTPError as err:
        logging.error(err)

def send_slack_message(args, slack_reminder):
    """Send slack message to remind users to delete their branches"""
    for user_email in slack_reminder.keys():
        try:
            if user_email == "gita@coda.io":
                slack_user_id = get_slack_user_id(args, user_email)
                if slack_user_id:
                    branch_url = "https://github.com/"+args.gh_repo+"/compare/main..."
                    branches = [branch_url + branch['name'] + '\n' for branch in slack_reminder[user_email]]
                    delete_branch_msg = "git push origin --delete " + ' '.join([branch['name'] for branch in slack_reminder[user_email]])
                    message = "Hi! The following branches are more than %s days old:\n%s" % (''.join(branches), args.days_slack)
                    message+="If you would like to keep the branch alive please rename the branch with the prefix `keep-alive-`.\n"
                    message+="You can do this by running\n`git push origin origin/old_name:refs/heads/keep-alive-old_name && git push origin :old_name`\n"
                    message+=f"Otherwise please run `{delete_branch_msg}` to delete the branches.\n"
                    message+=f"If no action is taken, the {'branch' if len(branches)>1 else 'branches' } will be deleted in another %s days." % (args.days_delete-args.days_slack)
                    headers = {'Authorization': f'Bearer {args.slack_token}'}
                    data = {'text': message, 'channel': slack_user_id}
                    res = requests.post(
                        "https://slack.com/api/chat.postMessage", headers=headers, json=data, timeout=REQUEST_TIMEOUT_SECONDS)
                    res.raise_for_status()
                else:
                    logging.error(f"Slack user id not found for {user_email}")
        except requests.exceptions.HTTPError as err:
            logging.error(err)

def parse_args():
    """Define and parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Find old github branches', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '--gh-repo', help='The owner and repository name', default=os.getenv('GITHUB_REPOSITORY'))
    parser.add_argument('--gh-token', help='Github API Token', default=os.getenv('GITHUB_TOKEN'))
    parser.add_argument(
        '--slack-token', help='Slack token', default=os.getenv('SLACK_TOKEN'))
    parser.add_argument(
        '--days-delete', help='Number of days to delete')
    parser.add_argument(
        '--days-notify', help='Number of days to notify')
    parser.add_argument('--verbose', help='Verbose output', action='store_true')

    args = parser.parse_args()
    return args


def main():
    args = parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(format='%(asctime)s - %(levelname)s: %(message)s', level=log_level)
    if not args.gh_repo or not args.gh_token or not args.slack_token:
        logging.error("Missing required arguments")
        sys.exit(1)
    all_branches = grab_all_branches(args)

    if all_branches:
        triage_branches(args, all_branches)
    else:
        logging.info("No branches found")


if __name__ == "__main__":
    main()
