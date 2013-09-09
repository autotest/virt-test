import logging
from autotest.client.shared import error
from autotest.client import utils


@error.context_aware
def run_timerdevice_tscwrite(test, params, env):
    """
    Timer device tscwrite test:

    1) Check for an appropriate clocksource on host.
    2) Boot the guest.
    3) Download and compile the newest msr-tools.
    4) Execute cmd in guest.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    error.context("Check for an appropriate clocksource on host", logging.info)
    host_cmd = "cat /sys/devices/system/clocksource/"
    host_cmd += "clocksource0/current_clocksource"
    if not "tsc" in utils.system_output(host_cmd):
        raise error.TestNAError("Host must use 'tsc' clocksource")

    error.context("Boot the guest", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    error.context("Download and compile the newest msr-tools", logging.info)
    msr_tools_install_cmd = params["msr_tools_install_cmd"]
    session.cmd(msr_tools_install_cmd)

    error.context("Execute cmd in guest", logging.info)
    cmd = "dmesg -c > /dev/null"
    session.cmd(cmd)

    date_cmd = "strace date 2>&1 | egrep 'clock_gettime|gettimeofday' | wc -l"
    output = session.cmd(date_cmd)
    if not '0' in output:
        raise error.TestFail("Test failed before run msr tools."
                             " Output: '%s'" % output)

    msr_tools_cmd = params["msr_tools_cmd"]
    session.cmd(msr_tools_cmd)

    cmd = "dmesg"
    session.cmd(cmd)

    output = session.cmd(date_cmd)
    if not "1" in output:
        raise error.TestFail("Test failed after run msr tools."
                             " Output: '%s'" % output)
