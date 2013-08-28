#!/usr/bin/env python

import sys, os, getpass, datetime, time
from github import Github
from github_issues import GithubIssues, UTC, LocalTimezone

tz_UTC = UTC()
tz_LOCAL = LocalTimezone()

class GithubUserMetrics(object):
    """Simple class to help tally metrics one issue at a time"""

    days_per_period = 365.25 / 12

    def __init__(self, github_user):
        self.github_user = github_user
        self.first_submission_date = datetime.datetime.utcnow()
        self.total_submissions = 0
        self.submission_reviews = 0


    @property
    def first_submission(self):
        # Convert to local timezone
        return self.first_submission_date.astimezone(tz_LOCAL)


    @property
    def days_since_first(self):
        # All dates are in UTC, no need to calculate offset
        now = datetime.datetime.utcnow()
        duration = now - self.first_submission_date
        return duration.days


    @property
    def avg_submissions(self):
        period = self.days_since_first
        submissions_per_day = self.total_submissions / period
        return submissions_per_day * self.days_per_period


    @property
    def avg_reviews(self):
        period = self.days_since_first
        reviews_per_day = self.submission_reviews / period
        return reviews_per_day * self.days_per_period


    def integrate_issue(self, issue):
        """
        Capture data from issue
        """
        self.integrate_first_submission_date(issue)
        self.integrate_total_submissions(issue)
        self.integrate_submission_reviews(issue)


    def integrate_first_submission_date(self, issue):
        if issue['author'] == self.github_user.login:
            if issue['opened'] < self.first_submission_date:
                self.first_submission_date = issue['opened']


    def integrate_total_submissions(self, issue):
        if issue['author'] == self.github_user.login:
            self.total_submissions += 1

    def integrate_submission_reviews(self, issue):
        # Issue may not have any comments
        if issue['comment_authors']:
            if self.github_user.login in issue['comment_authors']:
                self.submission_reviews += 1


gh = Github(login_or_token=raw_input("Enter github username: "),
            password=getpass.getpass('Enter github password: '),
            user_agent='PyGithub/Python')


print "Enter locations to search <user>/<repo> ",
print "(e.g. autotest/autotest, autotest/virt-test, etc.)"
repo_full_names = []
while True:
    repo_full_name = raw_input("Location (blank to end) [%d]: "
                               % (len(repo_full_names) + 1)).strip()
    if repo_full_name:
        repo_full_names.append(repo_full_name)
    else:
        break
print


# Retrieve and validate github user
github_user = None
while github_user is None:
    try:
        github_user = gh.get_user(raw_input("Github username to check: "))
    except ValueError, detail:
        print "Who?"
        github_user = None
        print str(detail)
print

while True:
    date_string = "20"
    date_string += raw_input("Enter search start date (YY-MM-DD): ")
    date_string += " 00:00:00.0"
    date_string = date_string.strip()
    fmt = '%Y-%m-%d %H:%M:%S.%f'
    try:
        since = datetime.datetime.strptime(date_string, fmt)
        since = since.replace(tzinfo=tz_LOCAL)
        since = since.astimezone(tz_UTC) # Convert to UTC
        break
    except ValueError:
        print "When?"
print

gum = GithubUserMetrics(github_user)
import pdb; pdb.set_trace()
# pygithub doesn't work correctly with multiple repo objects at same time
for repo_full_name in repo_full_names:
    issues = GithubIssues(gh, repo_full_name)
    criteria = {'since':since}
    # Can't search both open and closed at same time
    for state in ['open', 'closed']:
        print "Searching %s %s (this could take a while)..." % (
                                                state, issues.repo_full_name)
        criteria['state'] = state
        numbers = issues.search(criteria)
        for index, number in enumerate(numbers):
            issue = issues[number]
            # Only pull-request issues contain commits
            if issue['commits']:
                gum.integrate_issue(issue)
            sys.stdout.write('%d/%d\n' % (index, len(numbers) - 1))
            sys.stdout.flush()
    del issues # make sure cache gets flushed
    print

print "User %s metrics as of %s:" % (github_user.login, date_string)
print "    Date of first submission:    %s" % (gum.first_submission.ctime())
print "    Days since first submission: %d" % gum.days_since_first
print "    Avg. submissions / month:    %d" % gum.avg_submissions
print "    Avg. reviews / month:        %d" % gum.avg_reviews
print
