"""
Classes to cache and read specific items from github issues in a uniform way
"""

from functools import partial as Partial
import datetime, time, shelve
# Requires PyGithub version >= 1.13 for access to raw_data attribute
import github


CACHE_LIFETIMES = {
    'tiny':datetime.timedelta(minutes=10),
    'short':datetime.timedelta(hours=2),
    'medium':datetime.timedelta(days=15),
    'long':datetime.timedelta(days=30),
    'forever':datetime.timedelta(days=9999)}


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

    def __init__(self, github_obj, cache_get_partial, cache_set_partial,
                 pre_fetch_partial, fetch_partial):
        self.github = github_obj
        self.cache_get = cache_get_partial # Returns native dict
        self.cache_set = cache_set_partial # called with value=dict
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
        # Short by default
        expires = now + CACHE_LIFETIMES['short']
        # github.PaginatedList.PaginatedList need special handling
        if isinstance(fetched_obj, github.PaginatedList.PaginatedList):
            raw_data = [item.raw_data for item in fetched_obj]
            inside_klass = fetched_obj[0].__class__
            dont_change_much = [github.GitCommit.GitCommit,
                                github.NamedUser.NamedUser,
                                github.Commit.Commit]
            for dont_change in dont_change_much:
                if issubclass(inside_klass, dont_change):
                    expires = now + CACHE_LIFETIMES['medium']
                    break
            return self.__class__.format_data(klass,
                                              expires,
                                              raw_data,
                                              inside_klass)
        else:
            # closed issues/pull requests don't change much
            if (issubclass(klass, github.Issue.Issue) or
                issubclass(klass, github.PullRequest.PullRequest)):
                if fetched_obj.closed_at is not None:
                    expires = now + CACHE_LIFETIMES['long']
                else:
                    # Issue comments are cheap to get
                    if issubclass(klass, github.Issue.Issue):
                        expires = now + CACHE_LIFETIMES['tiny']
                    else: # pull request commits are expensive
                        expires = now + CACHE_LIFETIMES['short']
            # These should expire fairly quickly
            if issubclass(klass, SearchResults):
                expires = now + CACHE_LIFETIMES['tiny']
            # These rarely change
            if issubclass(klass, github.NamedUser.NamedUser):
                expires = now + CACHE_LIFETIMES['medium']
            # These probably never change
            if issubclass(klass, github.GitAuthor.GitAuthor):
                expires = now + CACHE_LIFETIMES['forever']
            return self.__class__.format_data(klass, expires,
                                              fetched_obj.raw_data)


    def cached_data(self):
        """
        Return dictionary containing cached values or raise KeyError
        """
        try:
            return self.cache_get() # maybe raise KeyError or TypeError
        except TypeError:
            raise KeyError("Cache is corrupted")


class GithubIssuesBase(list):
    """
    Base class for cached list of github issues
    """

    # Force static pickle protocol version
    protocol = 2

    def __init__(self, github_obj, repo_full_name, cache_filename):
        """
        Initialize cache and reference github repository issues
        """

        self.github = github_obj
        self.repo_full_name = repo_full_name
        self.shelf = shelve.open(filename=cache_filename,
                                 protocol=self.protocol,
                                 writeback=True)

        # Avoid exceeding rate-limit per hour
        requests = self.github.rate_limiting[1] # requests per hour
        period = 60.0 * 60.0 # one hour in seconds
        sleeptime = period / requests
        self.pre_fetch_partial = Partial(time.sleep, sleeptime)
        # self.pre_fetch_partial = None # cheat-mode enable (no delays)

        # get_repo called same way throughout instance life
        cache_get_partial = Partial(self.shelf.__getitem__,
                                    'repo_%s' % self.repo_full_name)
        cache_set_partial = Partial(self.shelf.__setitem__,
                                    'repo_%s' % self.repo_full_name)
        fetch_partial = Partial(self.github.get_repo,
                                self.repo_full_name)
        # Callable instance
        self.get_repo = GithubCache(self.github,
                                    cache_get_partial,
                                    cache_set_partial,
                                    self.pre_fetch_partial,
                                    fetch_partial)


    def __del__(self):
        """
        Make sure cache is saved
        """
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
        for key in self.keys():
            yield self[key]


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
        cache_key = 'repo_%s_issue_%s' % (self.repo_full_name, str(int(key)))
        fetch_partial = Partial(repo.get_issue, int(key))
        item = self.get_gh_obj(cache_key, fetch_partial)
        # No exception raised, update cache on disk
        self.shelf.sync()
        return item


    def has_key(self, key):
        return self.__contains__(key)


    def items(self):
        # Iterator comprehension
        return (self[key] for key in self.keys())


    def keys(self):
        # Iterators are simply better
        return xrange(1, self.__len__() + 1)


    def values(self):
        # Iterator comprehension
        return (value for (key, value) in self.items())


class GithubIssues(GithubIssuesBase, object):
    """
    List-like interface to cached github issues in standardized format
    """

    # Marshal callables for key to github.Issue.Issue value
    marshal_map = {
        'number':lambda gh_obj:getattr(gh_obj, 'number'),
        'summary':lambda gh_obj:getattr(gh_obj, 'title'),
        'modified':lambda gh_obj:getattr(gh_obj, 'updated_at'),
        'commits':NotImplementedError, # setup in __init__
        'opened':lambda gh_obj:getattr(gh_obj, 'created_at'),
        'closed':lambda gh_obj:getattr(gh_obj, 'closed_at'),
        'assigned':lambda gh_obj:getattr(gh_obj, 'assignee'),
        'author':lambda gh_obj:getattr(gh_obj, 'user').login,
        'commit_authors':NotImplementedError, # setup in __init__
        'comments':lambda gh_obj:getattr(gh_obj, 'comments'),
        'comment_authors':NotImplementedError, # setup in __init__
        'labels':lambda gh_obj:[label.name for label in gh_obj.labels],
        'url':lambda gh_obj:getattr(gh_obj, 'html_url'),
        'github_issue':lambda gh_obj:gh_obj
    }

    # Storage for property values
    _cache_hits = 0   # Tracks temporary cache instances
    _cache_misses = 0 # Tracks temporary cache instances

    def __init__(self, github_obj, repo_full_name):
        """
        Initialize cache and reference github repository issues
        """
        cache_filename = self.__class__.__name__ + '.cache'
        super(GithubIssues, self).__init__(github_obj,
                                           repo_full_name,
                                           cache_filename)
        # These marshal functions require state
        self.marshal_map['commits'] = self.gh_pr_commits
        self.marshal_map['commit_authors'] = self.gh_pr_commit_authors
        self.marshal_map['comment_authors'] = self.gh_issue_comment_authors


    def __del__(self):
        self.vacuum()
        super(GithubIssues, self).__del__()


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


    @property
    def cache_hits(self):
        return self.get_repo.cache_hits + self._cache_hits


    @property
    def cache_misses(self):
        return self.get_repo.cache_misses + self._cache_misses


    def __getitem__(self, key):
        """
        Return a standardized dict of github issue
        """
        item = self.marshal_gh_obj(super(GithubIssues, self).__getitem__(key))
        self.shelf.sync()
        return item


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
            cache_data['expires'] = now + CACHE_LIFETIMES['forever']
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
        search_cache_key = 'issue_search'
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
                                      microsecond=0)
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


    def get_gh_obj(self, cache_key, fetch_partial):
        """
        Helper to get object possibly from cache and update counters
        """
        cache_get_partial = Partial(self.shelf.__getitem__,
                                    cache_key)
        cache_set_partial = Partial(self.shelf.__setitem__,
                                    cache_key)
        # Callable instance could change every time
        get_obj = GithubCache(self.github,
                              cache_get_partial,
                              cache_set_partial,
                              self.pre_fetch_partial,
                              fetch_partial)
        result = get_obj()
        self._cache_hits += get_obj.cache_hits
        self._cache_misses += get_obj.cache_misses
        return result # DOES NOT SYNC DATA!


    def get_gh_user(self, login):
        cache_key = 'github_user_%s' % login
        fetch_partial = Partial(self.github.get_user, login)
        try:
            return self.get_gh_obj(cache_key, fetch_partial)
        except KeyError:
            raise ValueError('login %s is not a valid github user' % login)


    def get_gh_label(self, name):
        repo = self.get_repo()
        cache_key = 'repo_%s_labels'
        fetch_partial = Partial(repo.get_label, name)
        try:
            return self.get_gh_obj(cache_key, fetch_partial)
        except KeyError:
            raise ValueError('label %s is not valid for repo %s' % (name,
                                                           self.repo_full_name))


    def marshal_gh_obj(self, gh_issue):
        """
        Translate a github issue object into dictionary w/ fixed keys
        """
        mkeys = self.marshal_map.keys()
        return dict([ (key, self.marshal_map[key](gh_issue)) for key in mkeys])


    @staticmethod
    def gh_issue_is_pull(gh_issue):
        """
        Return True/False if gh_issue is a pull request or not
        """
        pullreq = gh_issue.pull_request
        if pullreq is not None:
            if (pullreq.diff_url is None and
                pullreq.html_url is None and
                pullreq.patch_url is None):
                return False
        else:
            return False
        # pullreq not None but pullreq attributes are not None
        return True


    # marshal_map method
    def gh_issue_comment_authors(self, gh_issue):
        """
        Retrieve a list of comment author e-mail addresses
        """
        if gh_issue.comments > 0:
            num = gh_issue.number
            cache_key = ('repo_%s_issue_%s_comments'
                         % (self.repo_full_name, num))
            fetch_partial = Partial(gh_issue.get_comments)
            authors = set()
            for comment in self.get_gh_obj(cache_key, fetch_partial):
                # Referencing user attribute requires a request, so cache it
                user_cache_key = cache_key + '_%s_user' % comment.id
                user_fetch_partial = Partial(getattr, comment, 'user')
                user = self.get_gh_obj(user_cache_key, user_fetch_partial)
                authors.add(user.email)
            return authors
        else:
            return None


    # marshal_map method
    def gh_pr_commit_authors(self, gh_issue):
        """
        Return list of commit author e-mail addresses for a pull-request
        """
        if GithubIssues.gh_issue_is_pull(gh_issue):
            num = gh_issue.number
            repo = self.get_repo()
            cache_key = 'repo_%s_pull_%s' % (self.repo_full_name, str(num))
            fetch_partial = Partial(repo.get_pull, num)
            pull = self.get_gh_obj(cache_key, fetch_partial)
            if pull.commits is None or pull.commits < 1:
                return None # No commits == no commit authors

            cache_key = 'repo_%s_pull_%s_commits' % (self.repo_full_name,
                                                     str(num))
            fetch_partial = Partial(pull.get_commits)
            authors = set()
            for commit in self.get_gh_obj(cache_key, fetch_partial):
                # Referencing commit author requires a request, cache it.
                author_cache_key = cache_key + '_%s_author' % str(commit.sha)
                author_fetch_partial = Partial(getattr, commit, 'author')
                author_obj = self.get_gh_obj(author_cache_key,
                                             author_fetch_partial)
                # Retrieve e-mail from git commit object
                if author_obj is None:
                    # Referencing git commit requires a request, cache it
                    gitcommit_cache_key = (cache_key + '_%s_gitcommit'
                                                       % str(commit.sha))
                    gitcommit_fetch_partial = Partial(getattr, commit,
                                                     'commit') # git commit
                    gitcommit = self.get_gh_obj(gitcommit_cache_key,
                                                gitcommit_fetch_partial)
                    authors.add(gitcommit.author.email)
                else: # Author is a github user
                    authors.add(author_obj.login)
            return authors
        return None # not a pull request


    # marshal_map method
    def gh_pr_commits(self, gh_issue):
        """
        Retrieves the number of commits on a pull-request, None if not a pull.
        """
        if GithubIssues.gh_issue_is_pull(gh_issue):
            num = gh_issue.number
            repo = self.get_repo()
            cache_key = 'repo_%s_pull_%s' % (self.repo_full_name, str(num))
            fetch_partial = Partial(repo.get_pull, num)
            pull = self.get_gh_obj(cache_key, fetch_partial)
            return pull.commits
        return None # not a pull request
