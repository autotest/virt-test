import time
import logging
from autotest.client.shared import error
from virttest import utils_misc, env_process


@error.context_aware
def run_shutdown(test, params, env):
    """
    KVM shutdown test:
    1) Log into a guest
    2) Send a shutdown command to the guest, or issue a system_powerdown
       monitor command (depending on the value of shutdown_method)
    3) Wait until the guest is down

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    timeout = int(params.get("login_timeout", 360))
    shutdown_count = int(params.get("shutdown_count", 1))
    shutdown_method = params.get("shutdown_method", "shell")
    sleep_time = float(params.get("sleep_before_powerdown", 10))
    shutdown_command = params.get("shutdown_command")

    for i in xrange(shutdown_count):
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)
        error.base_context("shutting down the VM %s/%s" % (i + 1,
                                                           shutdown_count),
                           logging.info)
        if shutdown_method == "shell":
            # Send a shutdown command to the guest's shell
            session.sendline(shutdown_command)
            error.context("waiting VM to go down (shutdown shell cmd)",
                          logging.info)
        elif shutdown_method == "system_powerdown":
            # Sleep for a while -- give the guest a chance to finish booting
            time.sleep(sleep_time)
            # Send a system_powerdown monitor command
            vm.monitor.cmd("system_powerdown")
            error.context("waiting VM to go down "
                          "(system_powerdown monitor cmd)", logging.info)

        if not utils_misc.wait_for(vm.is_dead, 360, 0, 1):
            raise error.TestFail("Guest refuses to go down")
        if i < shutdown_count - 1:
            env_process.preprocess_vm(test, params, env, params["main_vm"])
