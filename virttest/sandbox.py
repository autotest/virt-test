"""
Test utility classes and functions to help test container sandboxes

@copyright: 2013 Red Hat Inc.
"""

import datetime, time, logging
import sandbox_base

# This utility function lets test-modules quickly create a list of all
# sandbox aggregate types, themselves containing a list of individual
# sandboxes.

def make_sandboxes(params, env, extra_ns=None):
    """
    Return list of instantiated sandbox_testsandboxes classes

    @param: params: an undiluted Params instance
    @param: env: the current env instance
    @param: extra_ns: An extra, optional namespace to search for classes
    """
    namespace = globals() # stuff in this module
    if extra_ns is not None:
        namespace.update(extra_ns) # copy in additional symbols
    names = namespace.keys()
    # Test may require more than one sandbox agregator type
    pobs = params.objects('sandbox_testsandboxes') # manditory parameter
    # filter out non-TestSandboxes subclasses
    for name in names:
        try:
            if not issubclass(namespace[name], sandbox_base.TestSandboxes):
                # Working on name list, okay to modify dict
                del namespace[name]
        except TypeError:
            # Symbol wasn't a class
            pass
    # Return a list of instantiated sandbox_testsandboxes's classes
    return [namespace[type_name](params, env) for type_name in pobs]


# TestSandboxes instances may be defined below, or inside other namespaces
# They simply help the test-module iterate over many SimpleSandbox's or
# subclasses, initializing, finalizing, and gathering results.

class TestSimpleSandboxes(sandbox_base.TestSandboxes):
    """
    Simplistic sandbox aggregator using count SandboxCommandBase instance(s)
    """

    def __init__(self, params, env):
        """
        Initialize to run, all SandboxCommandBase's
        """
        super(TestSimpleSandboxes, self).__init__(params, env)
        self.init_sandboxes() # create instances of SandboxCommandBase
        # Point all of them at the same local uri
        self.for_each(lambda sb: sb.add_optarg('-c', self.uri))
        # Use each instances name() method to produce name argument
        self.for_each(lambda sb: sb.add_optarg('-n', sb.name))
        # Command should follow after a --
        self.for_each(lambda sb: sb.add_mm())
        # Each one gets the same command (that's why it's simple)
        self.for_each(lambda sb: sb.add_pos(self.command))


    def results(self, each_timeout=5):
        """
        Run sandboxe(s), allowing each_timeout to complete, return output list
        """
        start = datetime.datetime.now()
        total_timeout_seconds = each_timeout * self.count
        timeout_at = start + datetime.timedelta(seconds=total_timeout_seconds)
        self.for_each(lambda sb: sb.run())
        while datetime.datetime.now() < timeout_at:
            # Wait until number of running sandboxes is zero
            if bool(self.are_running()):
                time.sleep(0.1) # Don't busy-wait
                continue
            else: # none are running
                break
        end = datetime.datetime.now()
        still_running = self.are_running()
        # Be sure to clean up in all cases
        self.for_each(lambda sb: sb.auto_clean(True))
        if bool(still_running):
            raise sandbox_base.SandboxException("%d of %d sandboxes are still "
                                                "running after "
                                                "the timeout of %d seconds."
                                                % (still_running,
                                                   self.count,
                                                   total_timeout_seconds))
        # Kill off all sandboxes
        self.for_each(lambda sb: sb.stop())
        logging.info("%d sandboxe(s) finished in %s", self.count,
                                                      end - start)
        return self.for_each(lambda sb: sb.recv())
