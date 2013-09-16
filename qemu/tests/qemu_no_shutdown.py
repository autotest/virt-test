import logging
import time
from autotest.client.shared import error
from virttest import utils_misc


@error.context_aware
def run_qemu_no_shutdown(test, params, env):
    """
    KVM -no-shutdown flag test:
    1. Boot a guest, with -no-shutdown flag on command line
    2. Run 'system_powerdown' command in monitor
    3. Wait for guest OS to shutdown down and issue power off to the VM
    4. Run 'system_reset' qemu monitor command
    5. Run 'cont' qemu monitor command
    6. Wait for guest OS to boot up
    7. Repeat step 2-6 for 5 times.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    timeout = int(params.get("login_timeout", 360))
    repeat_times = int(params.get("repeat_times", 5))

    error.base_context("Qemu -no-shutdown test")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    qemu_process_id = vm.get_pid()
    session = vm.wait_for_login(timeout=timeout)
    logging.info("The guest bootup successfully.")

    for i in xrange(repeat_times):
        error.context("Round %s : Send monitor cmd system_powerdown."
                      % str(i + 1), logging.info)
        # Send a system_powerdown monitor command
        vm.monitor.cmd("system_powerdown")
        # Wait for the session to become unresponsive and close it
        if not utils_misc.wait_for(lambda: not session.is_responsive(),
                                   timeout, 0, 1):
            raise error.TestFail("Oops, Guest refuses to go down!")
        if session:
            session.close()
        # Check the qemu id is not change
        if not utils_misc.wait_for(lambda: vm.is_alive(), 5, 0, 1):
            raise error.TestFail("VM not responsive after system_"
                                 "powerdown with -no-shutdown!")
        if vm.get_pid() != qemu_process_id:
            raise error.TestFail("Qemu pid changed after system_powerdown!")
        logging.info("Round %s -> System_powerdown successfully.", str(i + 1))

        # Send monitor command system_reset and cont
        error.context("Round %s : Send monitor command system_reset and cont."
                      % str(i + 1), logging.info)
        vm.monitor.cmd("system_reset")
        vm.resume()

        session = vm.wait_for_login(timeout=timeout)
        logging.info("Round %s -> Guest is up successfully." % str(i + 1))
        if vm.get_pid() != qemu_process_id:
            raise error.TestFail("Qemu pid changed after system_reset & cont!")
    if session:
        session.close()
