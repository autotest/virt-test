from autotest.client.shared import error


def run_skip(test, params, env):
    """
    Raise TestNAError exception (should trigger SKIP in simple harness)
    """
    raise error.TestNAError("Skip test is raising a test NA Error!")
