import logging
import time
import random
from autotest.client.shared import error


@error.context_aware
def run_system_reset_bootable(test, params, env):
    """
    KVM reset test:
    1) Boot guest.
    2) Check the guest boot up time.(optional)
    3) Reset system by monitor command for several times. The interval time
       should can be configured by cfg file or based on the boot time get
       from step 2.
    4) Log into the guest to verify it could normally boot.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    timeout = float(params.get("login_timeout", 240))
    reset_times = int(params.get("reset_times", 20))
    interval = int(params.get("reset_interval", 10))
    wait_time = int(params.get("wait_time_for_reset", 60))

    if params.get("get_boot_time") == "yes":
        error.context("Check guest boot up time", logging.info)
        vm.create()
        vm.wait_for_login(timeout=timeout)
        bootup_time = time.time() - vm.start_time
        if params.get("reset_during_boot") == "yes":
            interval = int(bootup_time)
            wait_time = random.randint(0, int(bootup_time))
        vm.destroy()

    error.context("Boot the guest", logging.info)
    vm.create()
    logging.info("Wait for %d seconds before reset" % wait_time)
    time.sleep(wait_time)

    for i in range(reset_times):
        error.context("Reset guest system for %s times" % i, logging.info)

        vm.monitor.cmd("system_reset")

        interval_tmp = interval
        if params.get("fixed_interval", "yes") != "yes":
            interval_tmp = random.randint(0, interval)

        logging.debug("Reset the system by monitor cmd"
                      " after %ssecs" % interval_tmp)
        time.sleep(interval_tmp)

    error.context("Try to login guest after reset", logging.info)
    vm.wait_for_login(timeout=timeout)
