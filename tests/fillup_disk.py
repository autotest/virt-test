import logging
from autotest.client.shared import error


@error.context_aware
def run_fillup_disk(test, params, env):
    """
    Fileup disk test:
    Purpose to expand the qcow2 file to its max size.
    Suggest to test rebooting vm after this test.
    1). Fillup guest disk (root mount point) using dd if=/dev/zero.
    2). Clean up big files in guest with rm command.


    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    session2 = vm.wait_for_serial_login(timeout=login_timeout)

    fillup_timeout = int(params.get("fillup_timeout"))
    fillup_size = int(params.get("fillup_size"))
    fill_dir = params.get("guest_testdir", "/tmp")
    filled = False
    number = 0

    try:
        error.context("Start filling the disk in %s" % fill_dir, logging.info)
        cmd = params.get("fillup_cmd")
        while not filled:
            # As we want to test the backing file, so bypass the cache
            tmp_cmd = cmd % (fill_dir, number, fillup_size)
            logging.debug(tmp_cmd)
            s, o = session.cmd_status_output(tmp_cmd, timeout=fillup_timeout)
            if "No space left on device" in o:
                logging.debug("Successfully filled up the disk")
                filled = True
            elif s != 0:
                raise error.TestFail("Command dd failed to execute: %s" % o)
            number += 1
    finally:
        error.context("Cleaning the temporary files...", logging.info)
        while number >= 0:
            cmd = "rm -f /%s/fillup.%d" % (fill_dir, number)
            logging.debug(cmd)
            s, o = session2.cmd_status_output(cmd)
            if s != 0:
                logging.error(o)
                raise error.TestFail("Failed to remove file %s: %s;"
                                     "guest may be unresponsive or "
                                     "command timeout" % (number, o))
            number -= 1
        if session:
            session.close()
        if session2:
            session2.close()
