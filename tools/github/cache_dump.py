#!/usr/bin/env python

import sys, os, getpass, datetime, shelve
from github import Github

print "Enter location (<user>/<repo>)",
repo_full_name = 'autotest/virt-test'
repo_full_name = raw_input("or blank for '%s': "
                           % repo_full_name).strip() or repo_full_name

print

print "key,klass,inside_klass,fetched,expires,age"

todel = []

cache = shelve.open('GithubIssues.cache')
for key, value in cache.items():
    try:
        age = value['expires'] - value['fetched']
        days = age.days * 1.0
        seconds_per_day = (60 * 60 * 24)
        days += age.seconds / seconds_per_day
        if key.count(repo_full_name):
            print "%s,%s,%s,%s,%s,%s" % (key, value['klass'].__name__,
                                         value.get('inside_klass'),
                                         value['fetched'].isoformat(),
                                         value['expires'].isoformat(),
                                         str(days))
        # Prune invalid/expired entries
        if value['expires'] < datetime.datetime.utcnow():
            todel.append(key)
    except KeyError:
        todel.append(key)

print "Purging %d keys" % len(todel)

for key in todel:
    del cache[key]

cache.close()
