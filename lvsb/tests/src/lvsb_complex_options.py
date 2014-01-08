import logging
from autotest.client.shared import error
from virttest.lvsb import make_sandboxes


def run(test, params, env):
    """
    Test complex options of the virt-sandbox command
    """
    status_error = bool("yes" == params.get("status_error", "no"))

    # list of sandbox agregation managers
    sb_list = make_sandboxes(params, env)
    if not sb_list:
        raise error.TestFail("Failed to return list of instantiated "
                             "lvsb_testsandboxes classes")

    # Run a sandbox until timeout or finished w/ output
    # store list of stdout's for the sandbox in aggregate type
    cmd_output_list = sb_list[0].results()
    # Remove all duplicate items from result list
    cmd_outputs = list(set(cmd_output_list[0].splitlines()))

    # To get exit codes of the command
    status = sb_list[0].are_failed()

    # positive and negative testing #########
    if not status_error:
        if status != 0:
            raise error.TestFail("%d not a expected command "
                                 "return value", status)
        else:
            logging.info(cmd_outputs)
