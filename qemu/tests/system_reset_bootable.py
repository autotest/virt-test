import logging, time, random
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

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    reset_times = int(params.get("reset_times",20))
    interval = int(params.get("reset_interval",10))
    wait_time = int(params.get("wait_time_for_reset",60))

    if params.get("get_boot_time") == "yes":
        error.context("Check guest boot up time.", logging.info)
        session = vm.wait_for_login(timeout=timeout)
        bootup_time = time.time() - vm.start_time
        if params.get("reset_during_boot") == "yes":
            interval = int(bootup_time)
            wait_time = random.randint(0, int(bootup_time))
        vm.destroy()
        vm.create()

    logging.info("Wait for %d seconds before reset" % wait_time)
    time.sleep(wait_time)

    for _ in range(reset_times):
        vm.monitor.cmd("system_reset")

        if params.get("fixed_interval", "yes") == "yes":
            interval_tmp = interval
        else:
            interval_tmp = random.randint(0, interval)

        logging.info("Reset the system by monitor cmd"
                     " after %ss" % interval_tmp)
        time.sleep(interval_tmp)

    logging.info("Try to login guest after reset")
    session = vm.wait_for_login(timeout=timeout)
