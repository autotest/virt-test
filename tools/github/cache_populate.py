#!/usr/bin/env python

import sys, os, getpass, datetime, time
from github import Github
from github_issues import GithubIssues, Partial

gh = Github(login_or_token=raw_input("Enter github username: "),
            password=getpass.getpass('Enter github password: '),
            user_agent='PyGithub/Python')

print "Enter location (<user>/<repo>)",
repo_full_name = 'autotest/virt-test'
repo_full_name = raw_input("or blank for '%s': "
                           % repo_full_name).strip() or repo_full_name

issues = GithubIssues(gh, repo_full_name)

start = 1
end = len(issues)
try:
    start = int(raw_input("Start at issue ([%d]-%d): " % (start, end)))
except ValueError:
   start = 1
print

# direct iteration doesn't work quite right, use indexes instead
for issue_num in xrange(start, end + 1):
    sys.stdout.write(str(issues[issue_num]['number']) + '\n')
    sys.stdout.flush()

# make sure cache is cleaned and saved up
del issues

print
