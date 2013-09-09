import logging
import os
import time
import re
import shutil
from autotest.client.shared import error, utils
from virttest import utils_test


def run_timedrift_monotonicity(test, params, env):
    """
    Check guest time monotonicity during migration:

    1) Log into a guest.
    2) Take time from guest.
    3) Migrate the guest.
    4) Keep guest running for a period after migration,
       and record the time log.
    5) Analyse log if it is exist.

    @param test: QEMU test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    def get_time(cmd, test_time, session):
        if os.path.isfile(host_path):
            os.remove(host_path)
        lasttv = "0"
        cmd_timeout = int(params.get("cmd_timeout"))
        start_time = time.time()
        while (time.time() - start_time) < test_time:
            tv = session.cmd_output(cmd, timeout=cmd_timeout)
            if params.get("os_type") == 'windows':
                list = re.split('[:]', tv)
                tv = str(int(list[0]) * 3600 + int(
                    list[1]) * 60 + float(list[2]))
            if float(tv) < float(lasttv):
                p_tv = "time value = " + tv + "\n"
                p_lasttv = "last time value = " + lasttv + "\n"
                time_log = file(host_path, 'a')
                time_log.write("time went backwards:\n" + p_tv + p_lasttv)
                time_log.close()
            lasttv = tv
            time.sleep(0.1)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    boot_option_added = params.get("boot_option_added")
    boot_option_removed = params.get("boot_option_removed")
    if boot_option_added or boot_option_removed:
        utils_test.update_boot_option(vm,
                                      args_removed=boot_option_removed,
                                      args_added=boot_option_added)

    timeout = int(params.get("login_timeout", 360))
    session1 = vm.wait_for_login(timeout=timeout)

    host_path = params.get("host_path")
    cmd = params.get("cmd_get_time")
    test_time = int(params.get("time_linger", "60"))

    try:
        # take time
        logging.info("Start take guest time")
        bg = utils.InterruptedThread(get_time, (cmd, test_time, session1))
        bg.start()

        # migration
        logging.info("Start migration")
        vm.migrate()

        # log in
        logging.info("Logging in after migration...")
        session2 = vm.wait_for_login(timeout=timeout)
        if not session2:
            raise error.TestFail("Could not log in after migration")
        logging.info("Logged in after migration")

        # linger a while
        time.sleep(test_time)

        # analyse the result
        if os.path.isfile(host_path):
            log_dir = os.path.join(test.outputdir,
                                   "timedrift-monotonicity-result.txt")
            shutil.copyfile(host_path, log_dir)
            myfile = file(host_path, 'r')
            for line in myfile:
                if "time went backwards" in line:
                    myfile.close()
                    raise error.TestFail("Failed Time Monotonicity testing, "
                                         "Please check log %s" % host_path)
    finally:
        session1.close()
        # remove flags add for this test.
        if boot_option_added or boot_option_removed:
            utils_test.update_boot_option(vm,
                                          args_removed=boot_option_added,
                                          args_added=boot_option_removed)
