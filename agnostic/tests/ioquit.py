import logging
import time
import random
from autotest.client.shared import error


@error.context_aware
def run(test, params, env):
    """
    Emulate the poweroff under IO workload(dd so far) with signal SIGKILL.

    1) Boot a VM
    2) Add IO workload for guest OS
    3) Sleep for a random time
    4) Kill the VM

    :param test: Kvm test object
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    session2 = vm.wait_for_login(timeout=login_timeout)

    bg_cmd = params.get("background_cmd")
    error.context("Add IO workload for guest OS.", logging.info)
    session.cmd_output(bg_cmd, timeout=60)

    error.context("Verify the background process is running")
    check_cmd = params.get("check_cmd")
    session2.cmd(check_cmd, timeout=60)

    error.context("Sleep for a random time", logging.info)
    time.sleep(random.randrange(30, 100))
    session2.cmd(check_cmd, timeout=60)

    error.context("Kill the VM", logging.info)
    vm.process.close()
