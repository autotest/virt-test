import logging
import time
import re
from autotest.client.shared import error


@error.context_aware
def run_readonly_floppy(test, params, env):
    """
    KVM readonly_floppy test:
    1) pre_command on the host to generate the floppy media
       : "dd if=images/fd1.img bs=512 count=2880
       && dd if=images/fd2.img bs=512 count=2880"
    2) Boot and login into a guest;
    3) If the OS is linux, load the floppy module, or if
       it is a Windows,wait 20s until the floppies are ready to be used
    4) Make filesystem against the floppy and reads the output of the
       command,check if there is 'Read-only'(for linux) or
       'protected'(for windows) keyword,if not,fail the test;
    5) Close session to the VM

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error.context("Boot up guest with floppies", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    sleep = params.get("sleep")
    # if it is a windows OS,wait for 20 seconds until the floppies
    # are ready for testing
    if sleep:
        logging.info("Windows system being tested,sleep for 20"
                     " seconds until floppies are ready to be use")
        time.sleep(20)
    try:
    # if it is a linux OS,load the floppy module
        if not sleep:
            logging.info("Loading the floppy module...")
            status = session.get_command_status("modprobe floppy")
            logging.info("Sleep 5 seconds after loading the floppy module")
            time.sleep(5)
            if status:
                raise error.TestError("Unable to load the floppy module")

        # Format floppy disk to test if it is readonly
        floppy_count = len(params.get("floppies", "").split())
        format_cmd_list = [params.get("format_floppy0_cmd"),
                           params.get("format_floppy1_cmd")]

        for floppy_index in range(floppy_count):
            error.context("Format the %s floppy disk" % floppy_index,
                          logging.info)
            s, o = session.get_command_status_output(
                format_cmd_list[floppy_index],
                timeout=float(params.get("format_floppy_timeout", 60)))
            if s == 0:
                raise error.TestError("Floppy disk %s is not readonly and"
                                      " it's formatted successfully" % floppy_index)
            error.context("Check the %s floppy is readonly" % floppy_index,
                          logging.info)
            found = re.search('(Read-only)|(protected)', o)
            logging.debug("Output of format command: %s" % o)
            if not found:
                raise error.TestError("Floppy disk %s cannot be formatted"
                                      " for reasons other than readonly" % floppy_index)
            else:
                logging.info("Floppy disk %s is Read-only and cannot be"
                             " formatted" % floppy_index)

    finally:
        if session:
            session.close()
