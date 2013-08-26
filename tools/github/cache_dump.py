#!/usr/bin/env python

import sys, os, getpass, datetime, shelve
from github import Github

print "key,klass,inside_klass,fetched,expires,age"

todel = []

cache = shelve.open('GithubIssues.cache', flag='r', protocol=2)
for key, value in cache.items():
    age = value['expires'] - value['fetched']
    days = age.days * 1.0
    seconds_per_day = (60 * 60 * 24)
    days += age.seconds / seconds_per_day
    print "%s,%s,%s,%s,%s,%s" % (key, value['klass'].__name__,
                                 value.get('inside_klass'),
                                 value['fetched'].isoformat(),
                                 value['expires'].isoformat(),
                                 str(days))

cache.close()
