#!/usr/bin/env python

import sys, os, getpass, datetime
from github import Github
from github_issues import GithubIssues

gh = Github(login_or_token=raw_input("Enter github username: "),
            password=getpass.getpass('Enter github password: '),
            user_agent='PyGithub/Python')

print "Enter location (<user>/<repo>)",
repo_full_name = 'autotest/virt-test'
repo_full_name = raw_input("or blank for '%s': "
                           % repo_full_name).strip() or repo_full_name

print

issues = GithubIssues(gh, repo_full_name)
print

print "Pull requests applied since:"

while True:
    date_string = "20" + raw_input("Enter date (YY-MM-DD): ") + " 00:00:00.0"
    date_string = date_string.strip()
    fmt = '%Y-%m-%d %H:%M:%S.%f'
    try:
        since = datetime.datetime.strptime(date_string, fmt)
        break
    except ValueError:
        print "When?"
print

print "Enter github labels, blank to end:"
labels = []
while True:
    label = raw_input("labels[%d]" % (len(labels) + 1))
    label = label.strip()
    if label:
        try:
            # http://jacquev6.github.io
            #       /PyGithub/github_objects/Label.html#github.Label.Label
            labels.append(issues.get_gh_label(label).name)
        except ValueError, detail:
            print str(detail)
    else:
        break
print

# Search criteria is put into a dictionary
#            state - str - 'open', 'closed'
#            assignee - list of str (login), "none" or "*"
#            mentioned - str (login)
#            labels - list of str (label name)
#            sort - str - 'created', 'updated', 'comments'
#            direction - str - 'asc', 'desc'
#            since - datetime.datetime
if labels:
    criteria = {'labels':labels, 'sort':'updated', 'since':since}
else:
    criteria = {'sort':'updated', 'since':since}

print "Searching..."

# Colate issues per author
author_issues = {}

# Can't search both open and closed at same time
for state in ['open', 'closed']:
    criteria['state'] = state
    for number in issues.search(criteria):
        issue = issues[number]
        # Skip issues (they don't have commits)
        if issue['commits'] is not None:
            # Pull req. could be closed but not merged
            if issue['merged'] is not None:
                author_issues[issue['author']] = issue
        sys.stdout.write('.')
        sys.stdout.flush()

print '\n'

heading = ("Applied %s pull-requests from %s since %s  by author"
           % (",".join(labels), repo_full_name, since.isoformat()))
print heading
print "-" * len(heading)
print

authors = author_issues.keys()
authors.sort()
for author in authors:
    issue = author_issues[author]
    print "Pull #%d: '%s'" % (issue['number'], issue['summary'])
    if issue['commits'] > 0:
        print "    %d commit(s) by %s" % (issue['commits'],
                                          ",".join(issue['commit_authors']))
        print
    else:
        print "    commit information unavailable"
        print

# make sure cache is cleaned and saved up
del issues

print
