import re
import logging
from autotest.client.shared import error


@error.context_aware
def run(test, params, env):
    """
    check kvm-clock using newer msrs test (only for Linux guest):

    1) boot guest with '-rtc base=utc,clock=host,driftfix=slew'
    2) verify guest using newer msrs set

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    msrs = str(params["msrs"]).split()
    dmesg = str(session.cmd_output("dmesg"))
    msrs_catch_re = params.get("msrs_catch_re",
                               "kvm-clock: Using msrs (\w+) and (\w+)")
    current_msrs = re.search(r"%s" % msrs_catch_re, dmesg, re.M | re.I)
    if current_msrs:
        current_msrs = set(current_msrs.groups())
        if current_msrs != set(msrs):
            raise error.TestFail("Except msrs (%s), " % msrs +
                                 "got (%s)" % current_msrs)
    else:
        logging.debug(dmesg)
        raise error.TestFail("No newer msr available for kvm-clock")
