import logging, time, re, os
from autotest.client.shared import error
from virttest import utils_misc
from virttest import utils_test
from virttest import env_process
from virttest import storage

@error.context_aware
def run_boot_time(test, params, env):
    """
    KVM boot time test:
    1) Backup guest image, then boot up guest.
    2) Set init run level to 1
    3) Send a shutdown command to the guest, or issue a system_powerdown
       monitor command (depending on the value of shutdown_method)
    4) Boot up the guest and measure the boot time
    5) Restore guest image.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    error.context("Set guest run level to 1")
    inittab = params.get("inittab", "/etc/inittab")
    tmp_path = params.get("tmp_path", "/tmp")

    vm.copy_files_from(inittab, tmp_path)
    tmp_inittab = os.path.join(tmp_path, "inittab")

    fd_r = open(tmp_inittab, "r")
    fd_w = open("%s_new" % tmp_inittab, "w")
    content = fd_r.read()
    fd_w.write(re.sub("id:\d+:initdefault", "id:1:initdefault", content))
    fd_r.close()
    fd_w.close()
    vm.copy_files_to("%s_new" % tmp_inittab, "%s" % inittab)

    error.context("Shut down guest")
    try:
        if params.get("shutdown_method") == "shell":
            # Send a shutdown command to the guest's shell
            session.sendline(vm.get_params().get("shutdown_command"))
            logging.info("Shutdown command sent; waiting for guest to go "
                         "down...")
        elif params.get("shutdown_method") == "system_powerdown":
            # Sleep for a while - give the guest a chance to finish booting
            time.sleep(float(params.get("sleep_before_powerdown", 10)))
            # Send a system_powerdown monitor command
            vm.monitor.cmd("system_powerdown")
            logging.info("system_powerdown monitor command sent;"
                          "waiting for guest to go down...")

        if not utils_misc.wait_for(vm.is_dead, timeout, 0, 1):
            raise error.TestFail("Guest refuses to go down")

        logging.info("Guest is down")

    finally:
        session.close()

    error.context("Boot up guest and measure the boot time")
    logging.info("Boot up guest again")
    vm.create()
    vm.verify_alive()
    start_time = time.time()
    session = vm.wait_for_serial_login(timeout=timeout)
    login_time = time.time()
    boot_time = login_time - start_time
    expect_time = int(params.get("expect_bootup_time", "16"))
    fluctuate = float(params.get("fluctuate", "1.1"))
    logging.info("Boot up time: %ss" % boot_time)

    if boot_time > expect_time * fluctuate:
        raise error.TestFail("Boot up takes too long time: %ss" % boot_time)

    session.close()
