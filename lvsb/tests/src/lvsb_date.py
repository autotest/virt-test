"""
Simple test that executes date command in a sanbox and verifies it is correct
"""

import datetime
from autotest.client.shared import error
from virttest.lvsb import make_sandboxes


def verify_datetime(start_time, stop_time, result_list):
    """
    Return the number of sandboxes which reported incorrect date
    """
    bad_dt = 0
    for results in result_list:  # list of aggregate managers
        for result in results:  # list of sandbox stdouts
            try:
                test_dt = datetime.datetime.fromtimestamp(
                    float(result.strip()))
            except (TypeError, ValueError):
                bad_dt += 1
            else:
                if test_dt >= start_time and test_dt <= stop_time:
                    continue  # good result, check next
                else:
                    bad_dt += 1
    return bad_dt


def some_failed(failed_list):
    """
    Return True if any single sandbox reported a non-zero exit code
    """
    for failed in failed_list:  # list of sandboxes w/ non-zero exit codes
        if failed > 0:
            return True
    return False


def run_lvsb_date(test, params, env):
    """
    Executes date command in a sanbox and verifies it is correct

    1) Gather parameters
    2) Create configured sandbox aggregater(s)
    3) Run and stop all sandboxes in all agregators
    4) Handle results
    """
    # Record time for comparison when finished
    start_time = datetime.datetime.now()
    status_error = bool('yes' == params.get('status_error', 'no'))
    # list of sandbox agregation managers (list of lists of list of sandboxes)
    sb_agg_list = make_sandboxes(params, env)
    # Number of sandboxes for each aggregate type
    agg_count = [agg.count for agg in sb_agg_list]
    # Run all sandboxes until timeout or finished w/ output
    # store list of stdout's for each sandbox in each aggregate type
    result_list = [agg.results() for agg in sb_agg_list]
    # Timeouts throw SandboxException, if normal exit, record ending time
    stop_time = datetime.datetime.now()

    # Number of sandboxs with non-zero exit codes for each aggregate type
    failed_list = [agg.are_failed() for agg in sb_agg_list]

    # handle results
    if status_error:  # Negative test
        if not some_failed(failed_list) and verify_datetime(start_time,
                                                            stop_time,
                                                            result_list) < 1:
            raise error.TestFail("Error test failed on only %s of %s sandboxes"
                                 % (failed_list, agg_count))
    else:  # Positive test
        if some_failed(failed_list):
            raise error.TestFail("Some sandboxes had non-zero exit codes")
        if verify_datetime(start_time, stop_time, result_list) > 0:
            raise error.TestFail("Some sandboxes reported invalid date/time")
    # Otherwise test passed
