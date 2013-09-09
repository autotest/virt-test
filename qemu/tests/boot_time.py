import logging
import time
from autotest.client.shared import error

try:
    from autotest.client.shared import utils_memory
except ImportError:
    from virttest.staging import utils_memory


@error.context_aware
def run_boot_time(test, params, env):
    """
    KVM boot time test:
    1) Set init run level to 1
    2) Send a shutdown command to the guest, or issue a system_powerdown
       monitor command (depending on the value of shutdown_method)
    3) Boot up the guest and measure the boot time
    4) set init run level back to the old one

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    error.context("Set guest run level to 1", logging.info)
    single_user_cmd = params['single_user_cmd']
    session.cmd(single_user_cmd)

    try:
        error.context("Shut down guest", logging.info)
        session.cmd('sync')
        vm.destroy()

        error.context("Boot up guest and measure the boot time", logging.info)
        utils_memory.drop_caches()
        vm.create()
        vm.verify_alive()
        session = vm.wait_for_serial_login(timeout=timeout)
        boot_time = time.time() - vm.start_time
        expect_time = int(params.get("expect_bootup_time", "17"))
        logging.info("Boot up time: %ss" % boot_time)

    finally:
        try:
            error.context("Restore guest run level", logging.info)
            restore_level_cmd = params['restore_level_cmd']
            session.cmd(restore_level_cmd)
            session.cmd('sync')
            vm.destroy()
            vm.create()
            vm.verify_alive()
            vm.wait_for_login(timeout=timeout)
        except Exception:
            logging.warning("Can not restore guest run level, "
                            "need restore the image")
            params["restore_image_after_testing"] = "yes"

    if boot_time > expect_time:
        raise error.TestFail(
            "Guest boot up is taking too long: %ss" % boot_time)

    session.close()
