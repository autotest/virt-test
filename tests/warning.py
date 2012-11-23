from autotest.client.shared import error


def run_warning(test, params, env):
    """
    Raise TestWarn exception (should trigger WARN in simple harness).
    """
    raise error.TestWarn("Warn test is raising a test warning!")
