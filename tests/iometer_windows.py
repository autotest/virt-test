"""
@author: Golita Yue <gyue@redhat.com>
@author: Amos Kong <akong@redhat.com>
"""
import logging
import time
import re
from autotest.client.shared import error
from virttest import utils_test, utils_misc


@error.context_aware
def run_iometer_windows(test, params, env):
    """
    Run Iometer for Windows on a Windows guest:

    1) Boot guest with additional disk
    2) Format the additional disk
    3) Install and register Iometer
    4) Perpare icf to Iometer.exe
    5) Run Iometer.exe with icf
    6) Copy result to host

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    # format the target disk
    utils_test.run_virt_sub_test(test, params, env, "format_disk")

    error.context("Install Iometer", logging.info)
    cmd_timeout = int(params.get("cmd_timeout", 360))
    ins_cmd = params["install_cmd"]
    vol_utils = utils_misc.get_winutils_vol(session)
    if not vol_utils:
        raise error.TestError("WIN_UTILS CDROM not found")
    ins_cmd = re.sub("WIN_UTILS", vol_utils, ins_cmd)
    session.cmd(cmd=ins_cmd, timeout=cmd_timeout)
    time.sleep(0.5)

    error.context("Register Iometer", logging.info)
    reg_cmd = params["register_cmd"]
    reg_cmd = re.sub("WIN_UTILS", vol_utils, reg_cmd)
    session.cmd_output(cmd=reg_cmd, timeout=cmd_timeout)

    error.context("Prepare icf for Iometer", logging.info)
    icf_name = params["icf_name"]
    ins_path = params["install_path"]
    res_file = params["result_file"]
    icf_file = utils_misc.get_path(test.virtdir, "deps/%s" % icf_name)
    vm.copy_files_to(icf_file, "%s\\%s" % (ins_path, icf_name))

    # Run Iometer
    error.context("Start Iometer", logging.info)
    session.cmd("cd %s" % ins_path)
    logging.info("Change dir to: %s" % ins_path)
    run_cmd = params["run_cmd"]
    run_timeout = int(params.get("run_timeout", 1000))
    logging.info("Set Timeout: %ss" % run_timeout)
    run_cmd = run_cmd % (icf_name, res_file)
    logging.info("Execute Command: %s" % run_cmd)
    session.cmd(cmd=run_cmd, timeout=run_timeout)

    error.context("Copy result '%s' to host" % res_file, logging.info)
    vm.copy_files_from(res_file, test.resultsdir)
