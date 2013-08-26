"""
Classes to cache and read specific items from github issues in a uniform way
"""

from functools import partial as Partial
import datetime, time, shelve
# Requires PyGithub version >= 1.13 for access to raw_data attribute
import github

# Github deals only in UTC, need way to convert date/time
class UTC(datetime.tzinfo):
    """UTC"""

    def utcoffset(self, dt):
        return datetime.timedelta(0)

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return datetime.timedelta(0)


class LocalTimezone(datetime.tzinfo):
    """Represents the local timezone automatically"""

    def __init__(self):
        self.STDOFFSET = datetime.timedelta(seconds = -time.timezone)
        if time.daylight:
            self.DSTOFFSET = datetime.timedelta(seconds = -time.altzone)
        else:
            self.DSTOFFSET = self.STDOFFSET
        self.DSTDIFF = self.DSTOFFSET - self.STDOFFSET
        self.ZERO = datetime.timedelta(0)


    def utcoffset(self, dt):
        if self._isdst(dt):
            return self.DSTOFFSET
        else:
            return self.STDOFFSET


    def dst(self, dt):
        if self._isdst(dt):
            return self.DSTDIFF
        else:
            return self.ZERO


    def tzname(self, dt):
        return time.tzname[self._isdst(dt)]


    def _isdst(self, dt):
        tt = (dt.year, dt.month, dt.day,
              dt.hour, dt.minute, dt.second,
              dt.weekday(), 0, 0)
        stamp = time.mktime(tt)
        tt = time.localtime(stamp)
        return tt.tm_isdst > 0



# Needed to not confuse cached 'None' objects
class Nothing(object):
    raw_data = None


# Needed to signal list cache, not github object
class SearchResults(object):

    def __init__(self, *stuff):
        self.raw_data = stuff


class GithubCache(object):
    """
    Auto-refreshing github.GithubObject.GithubObject from dict
    """

    cache_hits = 0
    cache_misses = 0

    cache_lifetimes = {
        'default':datetime.timedelta(hours=2),
        github.GitCommit.GitCommit:datetime.timedelta(days=30),
        github.NamedUser.NamedUser:datetime.timedelta(days=30),
        github.Commit.Commit:datetime.timedelta(days=30),
        github.Issue.Issue:datetime.timedelta(minutes=30),
        github.PullRequest.PullRequest:datetime.timedelta(hours=1),
        # Special case for github.Issue.Issue
        'closed':datetime.timedelta(days=30),
        SearchResults:datetime.timedelta(minutes=10),
        github.NamedUser.NamedUser:datetime.timedelta(hours=2),
        github.GitAuthor.GitAuthor:datetime.timedelta(days=999),
        'total_issues':datetime.timedelta(days=999)
    }


    def __init__(self, github_obj, cache_get_partial, cache_set_partial,
                 cache_del_partial, pre_fetch_partial, fetch_partial):
        self.github = github_obj
        self.cache_get = cache_get_partial # Returns native dict
        self.cache_set = cache_set_partial # called with value=dict
        self.cache_del = cache_del_partial
        self.pre_fetch = pre_fetch_partial # called with nothing
        self.fetch = fetch_partial # Returns github.GithubObject.GithubObject


    def __call__(self):
        """
        Retrieve instance from fresh or cached data
        """
        # microseconds aren't useful when fetch takes ~1 second
        now = datetime.datetime.utcnow()
        now = datetime.datetime(year=now.year, month=now.month,
                                day=now.day, hour=now.hour,
                                minute=now.minute, second=0, microsecond=0)
        try:
            data = self.cached_data()
            if data['expires'] < now:
                raise KeyError # refresh cache
            self.cache_hits += 1
        except KeyError:
            data = self.fetched_data(now)
            self.cache_set(value=data)
            self.cache_misses += 1
        # Any exceptions thrown during conversion should purge cache entry
        try:
            # Format data for consumption
            if data['klass'] == github.PaginatedList.PaginatedList:
                inside_klass = data['inside_klass']
                result = []
                for item in data['raw_data']:
                    result.append(self.github.create_from_raw_data(inside_klass,
                                                                   item))
                return result
            elif data['klass'] == Nothing:
                return None # it's a None object
            elif data['klass'] == SearchResults:
                return data['raw_data'] # just the contents
            else:
                return self.github.create_from_raw_data(data['klass'],
                                                        data['raw_data'])
        except:
            try:
                self.cache_del()
            except KeyError:
                pass # doesn't exist in cache, ignore
            raise # original exception


    @staticmethod
    def format_data(klass, expires, raw_data, inside_klass=None):
        """
        Enforce uniform data format for fetched data
        """
        if inside_klass is None:
            return {'klass':klass,
                    'fetched':datetime.datetime.utcnow(),
                    'expires':expires,
                    'raw_data':raw_data}
        else:
            return {'klass':klass,
                    'inside_klass':inside_klass,
                    'fetched':datetime.datetime.utcnow(),
                    'expires':expires,
                    'raw_data':raw_data}


    def fetched_data(self, now):
        """
        Return dictionary containing freshly fetched values
        """
        try:
            if callable(self.pre_fetch):
                self.pre_fetch()
            fetched_obj = self.fetch()
        except github.GithubException, detail:
            if detail.status == 404:
                raise KeyError('Github item not-found error while calling %s '
                               'with args=%s and dargs=%s' % (self.fetch.func,
                                                              self.fetch.args,
                                                           self.fetch.keywords))
            else:
                raise
        if fetched_obj is None:
            fetched_obj = Nothing()
        klass = fetched_obj.__class__
        # github.PaginatedList.PaginatedList need special handling
        if isinstance(fetched_obj, github.PaginatedList.PaginatedList):
            raw_data = [item.raw_data for item in fetched_obj]
            inside_klass = fetched_obj[0].__class__
            expires = now + self.cache_lifetimes.get(inside_klass,
                                                self.cache_lifetimes['default'])
            return self.__class__.format_data(klass,
                           now + self.cache_lifetimes.get(inside_klass,
                                  self.cache_lifetimes['default']),
                           raw_data, inside_klass)
        else:
            expires = now + self.cache_lifetimes.get(klass,
                                                     # else default
                                                self.cache_lifetimes['default'])
            # closed issues/pull requests don't change much
            if hasattr(fetched_obj, 'closed_at'):
                if fetched_obj.closed_at is not None:
                    expires = now + self.cache_lifetimes['closed']
            return self.__class__.format_data(klass, expires,
                                              fetched_obj.raw_data)


    def cached_data(self):
        """
        Return dictionary containing cached values or raise KeyError
        """
        try:
            return self.cache_get() # maybe raise KeyError or TypeError
        except KeyError:
            raise
        except:
            # Try to delete the entry
            self.cache_del()
            raise

class HourRateLimiter(object):
    """
    Objects that sleep when called, based on per-hour rate limiting.
    """

    def __init__(self, limit, remaining, reset=None):
        """
        Initialize rate-limiter callable based on current external state

        @param: limit: Number of requests per period
        @param: remaining: Number of requests remaining for this period
        @param: period: datetime.TimeDelta describing reset period
        @param: reset: datetime of current period end (None for bottom of hour)
        """
        if reset is None:
            self.__next_reset__()
        else:
            self.reset = reset
        self.limit = limit
        self.remaining = remaining
        self.duration = 0
        self.__update__() # Set self.duration


    def __next_reset__(self):
        """Calculate and set reset time from now"""
        now = datetime.datetime.utcnow()
        hour_top = datetime.datetime(year=now.year, month=now.month,
                                     day=now.day, hour=now.hour,
                                     minute=0, second=0, microsecond=0)
        self.reset = hour_top + datetime.timedelta(hours=1)


    def __update__(self):
        """Update counters and timers, deducting one request"""
        now = datetime.datetime.utcnow()
        if now >= self.reset:
            self.remaining = self.limit
            self.__next_reset__()
        if self.remaining < 1:
            raise ValueError("Rate limit exceeded: Check for unaccounted "
                             "requests or inaccurate reset time")
        # Seconds until next reset
        delta = self.reset - now
        reset_seconds = delta.seconds + (delta.microseconds / 1000000.0)
        # Divide remaining requests into available time
        self.duration = reset_seconds / self.remaining


    def __call__(self):
        """Sleep for self.duration"""
        # Deduct request and update self.duration
        self.__update__()
        if self.duration > 5:
            raise ValueError("Sleeping too long: %0.4fseconds" % self.duration)
        time.sleep(self.duration)
        # Deduct this request
        self.remaining -= 1


class GithubIssuesBase(list):
    """
    Cached list of github issues in pygithub format
    """

    # Storage for property values
    _cache_hits = 0   # Tracks temporary cache instances
    _cache_misses = 0 # Tracks temporary cache instances

    # Force static pickle protocol version
    protocol = 2

    # Class to use for cache management
    cache_class = GithubCache

    def __init__(self, github_obj, repo_full_name):
        """
        Initialize cache and reference github repository issues
        """

        self.github = github_obj
        self.repo_full_name = repo_full_name
        self.shelf = shelve.open(filename='GithubIssues.cache',
                                 protocol=self.protocol,
                                 writeback=True)

        # Initialize sleeptime
        remaining, limit = self.github.rate_limiting
        self.ratelimit = HourRateLimiter(limit, remaining)

        repo_cache_key = 'repo_%s' % self.repo_full_name
        # get_repo called same way throughout instance life
        cache_get_partial = Partial(self.shelf.__getitem__, repo_cache_key)
        cache_set_partial = Partial(self.shelf.__setitem__, repo_cache_key)
        cache_del_partial = Partial(self.shelf.__delitem__, repo_cache_key)
        fetch_partial = Partial(self.github.get_repo,
                                self.repo_full_name)
        # Callable instance retrieves cached or fetched value for key
        self.get_repo = self.cache_class(self.github,
                                         cache_get_partial,
                                         cache_set_partial,
                                         cache_del_partial,
                                         self.ratelimit,
                                         fetch_partial)
        super(GithubIssuesBase, self).__init__()


    def __del__(self):
        """
        Make sure cache is saved
        """
 
        self.vacuum()
        try:
            self.shelf.close()
        except AttributeError:
            pass # Open must have failed


    def __len__(self):
        """
        Binary search through issue numbers until largest identified
        """
        increment = 1000
        last_issue = 1
        if not self.__contains__(last_issue):
            return 0 # no issues
        while increment > 0:
            while self.__contains__(last_issue):
                last_issue += increment
            # Fall back to prior one
            last_issue -= increment
            # Chop increment in half
            increment /= 2
        return last_issue


    def __contains__(self, key):
        try:
            # Must call this classes method specifically
            GithubIssuesBase.__getitem__(self, key)
        except KeyError:
            return False
        return True


    def __iter__(self):
        return (self[key] for key in self.keys())


    def __setitem__(self, key, value):
        raise KeyError("Read only mapping while trying to set %s to %s"
                       % (str(key), str(value)))


    def __delitem__(self, key):
        raise KeyError("Read only mapping while trying to delete %s" % str(key))


    def __getitem__(self, key):
        """
        Return a standardized dict of github issue unless NoEnumerate=True
        """
        repo = self.get_repo()
        # Enforce uniform key string
        cache_key = self.get_issue_cache_key(key)
        fetch_partial = Partial(repo.get_issue, int(key))
        item = self.get_gh_obj(cache_key, fetch_partial)
        # No exception raised, update cache on disk
        self.shelf.sync()
        return item


    @property
    def cache_hits(self):
        return self.get_repo.cache_hits + self._cache_hits


    @property
    def cache_misses(self):
        return self.get_repo.cache_misses + self._cache_misses


    def vacuum(self):
        """Vacuum up all expired entries"""
        # Can't modify list while iterating
        keys_to_del = []
        now = datetime.datetime.utcnow()
        for key, value in self.shelf.items():
            # no need to be precise
            if value['expires'] <= now:
                keys_to_del.append(key)
        for key in keys_to_del:
            del self.shelf[key]


    def get_gh_label(self, name):
        repo = self.get_repo()
        cache_key = str('repo_%s_label_%s' % (self.repo_full_name, name))
        fetch_partial = Partial(repo.get_label, name)
        try:
            return self.get_gh_obj(cache_key, fetch_partial)
        except KeyError:
            raise ValueError('label %s is not valid for repo %s' % (name,
                                                           self.repo_full_name))


    def get_pull(self, gh_issue):
        """Return possibly cached pull-request info"""
        num = gh_issue.number
        repo = self.get_repo()
        cache_key = 'repo_%s_pull_%s' % (self.repo_full_name, str(num))
        fetch_partial = Partial(repo.get_pull, num)
        return = self.get_gh_obj(cache_key, fetch_partial)



    def get_pull_commits(self, pull_request):
        """Return a list of pygithub commit objects"""
            cache_key = 'repo_%s_pull_%s_commits' % (self.repo_full_name,
                                                     str(num))
            fetch_partial = Partial(pull.get_commits)
            return self.get_gh_obj(cache_key, fetch_partial)


    def _fetch_pr_author_set(self, pull_request):
        # Don't count duplicates
        authors = set()
        for commit in get_pull_commits(pull_request):
            # pagination flip triggers a extra request
            self.ratelimit()
            # When not github user, use e-mail from git commit object
            if commit.author is None:
                # pagination flip triggers a extra request
                self.ratelimit()
                authors.add(commit.commit.author.email)
            else: # Author is a github user
                authors.add(commit.author)
        return authors


    def get_pull_commit_authors(self, pull_request):
        """Return set of unique commit author names/emails"""
        cache_key = 'repo_%s_pull_%s_commit_authors' % (
            self.repo_full_name, pull_request.number)
        fetch_partial = Partial(self._fetch_pr_author_set, pull_request)
        return self.get_gh_obj(cache_key, fetch_partial)



    def _fetch_issue_comment_authors(self, gh_issue):
        authors = set()
        for comment in gh_issue.get_comments:
            # pagination flip triggers a extra request
            self.ratelimit()
            authors.add(comment.user.login)
        return authors


    def get_issue_comment_authors(self, gh_issue):
        """Return set of unique comment author names"""
        cache_key = ('repo_%s_issue_%s_comments'
                     % (self.repo_full_name, gh_issue.number))
        fetch_partial = Partial(_fetch_issue_comment_authors, gh_issue)
        return self.get_gh_obj(cache_key, fetch_partial)


    def get_gh_obj(self, cache_key, fetch_partial):
        """
        Helper to get object possibly from cache and update counters
        """
        cache_get_partial = Partial(self.shelf.__getitem__,
                                    cache_key)
        cache_set_partial = Partial(self.shelf.__setitem__,
                                    cache_key)
        cache_del_partial = Partial(self.shelf.__delitem__,
                                    cache_key)
        # Callable instance could change every time
        get_obj = GithubCache(self.github,
                              cache_get_partial,
                              cache_set_partial,
                              cache_del_partial,
                              self.ratelimit,
                              fetch_partial)
        result = get_obj()
        self._cache_hits += get_obj.cache_hits
        self._cache_misses += get_obj.cache_misses
        return result # DOES NOT SYNC DATA!


    def get_issue_cache_key(self, number):
        """Return cache key to aid in item removal"""
        return 'repo_%s_issue_%s' % (self.repo_full_name, str(int(number)))


    def has_key(self, key):
        return self.__contains__(key)


    def items(self):
        # Iterator comprehension
        return (self[key] for key in self.keys())


    def keys(self):
        # Iterators are simply better
        return xrange(1, self.__len__())


    def values(self):
        # Iterator comprehension
        return (value for (key, value) in self.items())


class GithubIssue(object):
    """Standardized representation of single issue/pull request"""

    # Static property values
    _number = None
    _github_issues = None


    # Dynamic property values
    _summary = None
    _description = None
    _modified = None
    _commits = None
    _merged = None
    _opened = None
    _closed = None
    _assigned = None
    _author = None
    _commit_authors = None
    _comments = None
    _comment_authors = None
    _labels = None
    _url = None
    _is_pull = None

    def __init__(self, number, github_issues):
        self._number = number
        # Super class hands out raw data
        self._github_issues = super(GithubIssues, github_issues)


    @property
    def number(self):
        return self._number


    @property
    def github_obj(self):
        return self._github_issues.github


    @property
    def repo_full_name(self):
        return self._github.repo_full_name


    @property
    def summary(self):
        if self._summary is None:
            self._summary = self._github_issues[self._number].title
        return self._summary


    @property
    def description(self):
        if self._description is None:
            self._description = self._github_issues[self._number].body
        return self._description


    @property
    def modified(self):
        if self._modified is None:
            self._modified = self._github_issues[self._number].updated_at
        return self._modified


    @property
    def opened(self):
        if self._opened is None:
            self._opened = self._github_issues[self._number].created_at
        return self._opened


    @property
    def closed(self):
        if self._closed is None:
            self._closed = self._github_issues[self._number].closed_at
        return self._closed


    @property
    def assigned(self):
        if self._assigned is None:
            assignee = self._github_issues[self._number].assignee
            if assignee is not None:
                assignee = assignee.login
            else:
                assignee = ''
            self._assigned = assignee
        return self._assigned


    @property
    def author(self):
        if self._author is None:
            self._author = self._github_issues[self._number].user
        return self._author


    @property
    def is_pull(self):
        if self._is_pull is None:
            issue = self._github_issues[self._number]
            # Sometimes this attribute doesn't exist
            pullreq = getattr(issue, 'pull_request', None)
            if pullreq is None:
                self._is_pull = False
            else:
                # Be certain, cache can get corrupted if wrong
                if (pullreq.diff_url is not None and
                    pullreq.html_url is not None and
                    pullreq.patch_url is not None):
                    self._is_pull = True
        return self._is_pull


    @property
    def merged(self):
        if self._merged is None:
            issue = self._github_issues[self._number]
            if self.is_pull
                pull = self._github_issues.get_pull(self._number)
                if pull.merged:
                    self._merged = pull.merged_at
            else: # not pull request or not merged
                # TODO: Throw exception
                self._merged = False
        return self._merged


    @property
    def commits(self):
        if self._commits is None:
            if self.is_pull():
                pull = self._github_issues.get_pull(self._number)
                self._commits = pull.commits
            else: # Not a pull request
                # TODO: Throw exception
                self._commits = 0
        return self._commits


    @property
    def commit_authors(self):
        if self._commit_authors is None:
            if self.is_pull():
                pull = self._github_issues.get_pull(self._number)
                # Difficult line to wrap
                authors = self._github_issues.get_pull_commit_authors(pull)
                self._commit_authors = authors
            else: # Not a pull request
                # TODO: Throw exception
                self._commit_authors = False
        return self._commit_authors


    @property
    def comments(self):
        return self._github_issues[self._number].comments


    @property
    def comment_authors(self):
        if self._comment_authors is None:
            if self.comments > 0:
                issue = self._github_issues[self._number]
                # Difficult line to wrap
                authors = self._github_issues.get_issue_comment_authors(issue)
                self._self._comment_authors = authors
        return self._comment_authors


    @property
    def labels(self):
        if self._labels is None:
            label_pglist = self._github_issues[self._number].labels
            self._labels = [label.name for label in label_pglist]
        return self._labels


    @property
    def url(self):
        if self._url is None:
            self._url = self._github_issues[self._number].html_url
        return self._url


class GithubIssues(GithubIssuesBase):
    """List of GithubIssue instances plus some extra methods"""


    def __getitem__(self, key):
        """
        Return a GithubIssue instances for issue number key
        """
        # These instances delay data retrieval until it is requested
        return GithubIssue(key, self)


    def __len__(self):
        """
        Return cached number of issues
        """
        cache_key = 'repo_%s_total_issues' % self.repo_full_name
        # seconds aren't useful when fetch takes > 1 minute
        now = datetime.datetime.utcnow()
        now = datetime.datetime(year=now.year, month=now.month,
                                day=now.day, hour=now.hour,
                                minute=now.minute, second=0, microsecond=0)
        # Easier to do custom caching behavior here than fuss with GithubCache
        try:
            cache_data = self.shelf.__getitem__(cache_key)
            if cache_data['expires'] < now:
                raise KeyError
            # Bypass search_result caching used in self.search()
            searchresult = self.make_search_results(
                                                  {'since':cache_data['since']})
            # about to change the number
            cache_data['since'] = now
            # total equal to old count plus new count since then
            cache_data['raw_data'] += len(searchresult.raw_data)
        except KeyError:
            cache_data = {}
            # doesn't expire ever
            cache_data['expires'] = now + GithubCache.cache_lifetimes[
                                                                 'total_issues']
            cache_data['since'] = now
            # This will take a while if issue cache is stale
            cache_data['raw_data'] = super(GithubIssues, self).__len__()
        self.shelf.__setitem__(cache_key, cache_data)
        return cache_data['raw_data']


    def search(self, criteria):
        """
        Return a list of issue-numbers that match a search criteria.

        @param: criteria: Dictionary of search terms
            state - str - 'open', 'closed'
            assignee - list of str (login), "none" or "*"
            mentioned - str (login)
            labels - list of str (label name)
            sort - str - 'created', 'updated', 'comments'
            direction - str - 'asc', 'desc'
            since - datetime.datetime
        """
        valid_criteria = {}
        # use search dictionary to form hash for cached results
        search_cache_key = 'repo_%s_issue_search' % self.repo_full_name
        # Validate & transform criteria
        if criteria.has_key('state'):
            state = str(criteria['state'])
            if state not in ('open', 'closed'):
                raise ValueError("'state' criteria must be 'open' or 'closed'")
            valid_criteria['state'] = state
            search_cache_key = '%s_%s' % (search_cache_key, state)

        if criteria.has_key('assignee'):
            assignee = str(criteria['assignee'])
            search_cache_key = '%s_%s' % (search_cache_key, assignee)
            if assignee in ('none', '*'):
                valid_criteria['assignee'] = assignee
            else:
                # returns github.NamedUser.NamedUser
                valid_criteria['assignee'] = self.get_gh_user(assignee)

        if criteria.has_key('mentioned'):
            mentioned = str(criteria['assignee'])
            search_cache_key = '%s_%s' % (search_cache_key, mentioned)
            if mentioned in ('none', '*'):
                valid_criteria['mentioned'] = mentioned
            else:
                # returns github.NamedUser.NamedUser
                valid_criteria['mentioned'] = self.get_gh_user(mentioned)

        if criteria.has_key('labels'):
            labels = criteria['labels']
            if not isinstance(labels, list):
                raise ValueError("'lables' criteria must be a list")
            valid_criteria['labels'] = []
            for name in labels:
                search_cache_key = '%s_%s' % (search_cache_key, labels)
                valid_criteria['labels'].append(self.get_gh_label(str(name)))

        if criteria.has_key('sort'):
            sort = str(criteria['sort'])
            if sort not in ('created', 'updated', 'comments'):
                raise ValueError("'sort' criteria must be 'created', 'updated'"
                                 ", 'comments'")
            valid_criteria['sort'] = sort
            search_cache_key = '%s_%s' % (search_cache_key, sort)

        if criteria.has_key('direction'):
            direction = str(criteria['direction'])
            if direction not in ('asc', 'desc'):
                raise ValueError("'direction' criteria must be 'asc', 'desc'")
            valid_criteria['direction'] = direction
            search_cache_key = '%s_%s' % (search_cache_key, direction)

        if criteria.has_key('since'):
            since = criteria['since']
            if not isinstance(since, datetime.datetime):
                raise ValueError("'since' criteria must be a "
                                 "datetime.datetime")
            # second and milisecond not useful to search or cache
            since = datetime.datetime(year=since.year,
                                      month=since.month,
                                      day=since.day,
                                      hour=since.hour,
                                      minute=since.minute,
                                      second=0,
                                      microsecond=0,
                                      tzinfo=since.tzinfo)
            since = since.astimezone(UTC())
            search_cache_key = '%s_%s' % (search_cache_key, since.isoformat())
            valid_criteria['since'] = since

        # Do not perform search operation unless no cached results
        # or cached results have expired
        fetch_partial = Partial(self.make_search_results, valid_criteria)
        # This could take an arbitrarily LONG time
        return self.get_gh_obj(search_cache_key, fetch_partial)


    def make_search_results(self, valid_criteria):
        """
        Return a SearchResults instance from issue numbers found by search
        """
        repo = self.get_repo()
        result = repo.get_issues(**valid_criteria)
        return SearchResults(*[issue.number for issue in result])


    def clean_cache_entry(self, key):
        """
        Remove an entry from cache, ignoring any KeyErrors
        """
        try:
            del self.shelf[key]
        except KeyError:
            pass


    def get_gh_user(self, login):
        cache_key = 'github_user_%s' % login
        fetch_partial = Partial(self.github.get_user, login)
        try:
            return self.get_gh_obj(cache_key, fetch_partial)
        except KeyError:
            raise ValueError('login %s is not a valid github user' % login)



class MutateError(KeyError):

    def __init__(self, key, number):
        super(MutateError, self).__init__("Unable to modify %s on issue %d"
                                          % (str(key), number))


class MutableIssue(dict):
    """Allow modification of some issue values"""

    def __init__(self, github_issues, issue_number):
        if not isinstance(github_issues, GithubIssues):
            raise ValueError("github_issues %s is not a GithubIssues, it's a %s"
                             % (str(github_issues), str(type(github_issues))))
        # make sure issue_number is valid and cached
        junk = github_issues[issue_number]
        del junk
        # Private for private _github_issue property access
        self._github_issues = github_issues
        self._issue_number = issue_number
        super(MutableIssue, self).__init__()

    @property
    def _github_issue(self):
        return self._github_issues[self._issue_number]


    @property
    def _issue_cache_key(self):
        return self._github_issues.get_issue_cache_key(self._issue_number)


    def _setdelitem(self, opr, key, value):
        if key not in self._github_issues.marshal_map.keys():
            raise MutateError(key, self._issue_number)
        methodname = '%s_%s' % (opr, key)
        if callable(getattr(self, methodname)):
            method = getattr(self, methodname)
            if opr == 'set':
                method(value)
            else:
                method()
        else:
            raise MutateError(key, self._issue_number)


    def __getitem__(self, key):
        # Guarantees fresh/cached data for every call
        return self._github_issue[key]


    def __setitem__(self, key, value):
        self._setdelitem('set', key, value)


    def __delitem__(self, key):
        self._setdelitem('del', key, None)


    def set_labels(self, value):
        """
        Merge list of new lables into existing label set
        """
        new_labels = set(value)
        old_labels = set(self._github_issue['labels'])
        change_list = list(new_labels | old_labels)
        get_gh_label = self._github_issues.get_gh_label # save typing
        # Raise exception if any label name is bad
        gh_labels = [get_gh_label(label) for label in change_list]
        # Access PyGithub object to change labels
        self._github_issue['github_issue'].set_labels(*gh_labels)
        # Force retrieval of changed item
        self._github_issues.clean_cache_entry(self._issue_cache_key)


    def del_labels(self):
        """
        Remove all lbels from an issue
        """
        self._github_issue['github_issue'].delete_labels()
        # Force retrieval of changed item
        self._github_issues.clean_cache_entry(self._issue_cache_key)

    # TODO: Write get_*(), set_*(), del_*() for other dictionary keys
