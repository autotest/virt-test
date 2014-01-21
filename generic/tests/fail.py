from autotest.client.shared import error


def run(test, params, env):
    """
    Raise TestFail exception (should trigger FAIL in simple harness).
    """
    raise error.TestFail("Fail test is failing!")
