import logging
import os
import re
import time
from autotest.client.shared import error
from virttest import utils_misc


def run(test, params, env):
    """
    KVM windows virtio driver signed status check test:
    1) Start a windows guest with virtio driver iso/floppy
    2) Install windows SDK in guest.
    3) use SignTool.exe to verify whether block driver digital signed

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    def is_sdksetup_finished():
        s, o = session.cmd_status_output("tasklist | find \"SDK\"")
        if s:
            return True
        else:
            return False

    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)
    signtool_install = params.get("signtool_install")
    au3_link = params.get("winsdk_au3", "autoit/winsdk.au3")
    au3_link = os.path.join(test.bindir, au3_link)
    signtool_cmd = params.get("signtool_cmd")
    list_files_cmd = params.get("list_files_cmd")
    drive_list = params.get("drive_list")
    vm.copy_files_to(au3_link, "c:\\")
    drivers = {}
    logging.info("Install sdk in guest if signtool is not available.")
    session.cmd_status_output(signtool_install, timeout=360)
    # Wait until guest start install sdk.
    time.sleep(10)
    logging.info("Waiting for guest sdk setup ...")
    utils_misc.wait_for(is_sdksetup_finished, timeout=1800)
    results_all = """All the signature check log:\n"""
    fails_log = """Failed signature check log:\n"""
    fail_num = 0
    fail_drivers = []
    logging.info("Running SignTool command in guest...")
    try:
        for drive in drive_list.split():
            for type in ['.cat', '.sys']:
                driver = session.cmd_output(list_files_cmd % (drive, type)).\
                    splitlines()[1:-1]
                drivers[type] = driver
            files = zip(drivers['.cat'], drivers['.sys'])
            for cat, sys in files:
                cmd = signtool_cmd % (cat, sys)
                s, result = session.cmd_status_output(cmd)
                if s:
                    msg = "Fail command: %s. Output: %s" % (cmd, result)
                    raise error.TestFail(msg)
                results_all += result
                re_suc = "Number of files successfully Verified: ([0-9]*)"
                try:
                    suc_num = re.findall(re_suc, result)[0]
                except IndexError:
                    msg = "Fail to get Number of files successfully Verified"
                    raise error.TestFail(msg)

                if int(suc_num) != 1:
                    fails_log += result
                    fail_num += 1
                    fail_driver = cat + " " + sys
                    fail_drivers.append(fail_driver)
        if fail_num > 0:
            msg = "Following %s driver(s) signature checked failed." % fail_num
            msg += " Please refer to fails.log for details error log:\n"
            msg += "\n".join(fail_drivers)
            raise error.TestFail(msg)

    finally:
        open("fails.log", "w").write(fails_log)
        open("results.log", "w").write(results_all)
