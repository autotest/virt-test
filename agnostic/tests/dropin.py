import os
from autotest.client import utils
from autotest.client.shared import error
from virttest import data_dir


def run(test, params, env):
    """
    Run a dropin test.
    """
    dropin_path = params.get("dropin_path")
    dropin_path = os.path.join(data_dir.get_root_dir(), "dropin",
                               dropin_path)
    try:
        utils.system(dropin_path)
    except error.CmdError:
        raise error.TestFail("Drop in test %s failed" % dropin_path)
