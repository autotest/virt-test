import time
import os
import re
import logging
from autotest.client.shared import error
from virttest import utils_misc
from virttest import utils_test
from virttest import env_process
from virttest import data_dir
from autotest.client import utils


@error.context_aware
def run_whql_env_setup(test, params, env):
    """
    KVM whql env setup test:
    1) Log into a guest
    2) Update Windows kernel to the newest version
    3) Un-check Automatically restart in system failure
    4) Disable UAC
    5) Get the symbol files
    6) Set VM to physical memory + 100M
    7) Update the nic configuration
    8) Install debug view and make it auto run

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    log_path = "%s/../debug" % test.resultsdir
    # Prepare the tools iso
    error.context("Prepare the tools iso", logging.info)
    src_list = params.get("src_list")
    src_path = params.get("src_path", "%s/whql_src" % test.tmpdir)
    if not os.path.exists(src_path):
        os.makedirs(src_path)
    if src_list is not None:
        for i in re.split(",", src_list):
            utils.unmap_url(src_path, i, src_path)

    # Make iso for src
    cdrom_whql = params.get("cdrom_whql")
    cdrom_whql = utils_misc.get_path(data_dir.get_data_dir(), cdrom_whql)
    cdrom_whql_dir = os.path.split(cdrom_whql)[0]
    if not os.path.exists(cdrom_whql_dir):
        os.makedirs(cdrom_whql_dir)
    cmd = "mkisofs -J -o %s %s" % (cdrom_whql, src_path)
    utils.system(cmd)
    params["cdroms"] += " whql"

    vm = "vm1"
    vm_params = params.object_params(vm)
    env_process.preprocess_vm(test, vm_params, env, vm)
    vm = env.get_vm(vm)

    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)
    error_log = utils_misc.get_path(log_path, "whql_setup_error_log")
    run_guest_log = params.get(
        "run_guest_log", "%s/whql_qemu_comman" % test.tmpdir)

    # Record qmmu command line in a log file
    error.context("Record qemu command line", logging.info)
    if os.path.isfile(run_guest_log):
        fd = open(run_guest_log, "r+")
        fd.read()
    else:
        fd = open(run_guest_log, "w")
    fd.write("%s\n" % vm.qemu_command)
    fd.close()

    # Get set up commands
    update_cmd = params.get("update_cmd", "")
    timezone_cmd = params.get("timezone_cmd", "")
    auto_restart = params.get("auto_restart", "")
    qxl_install = params.get("qxl_install", "")
    debuggers_install = params.get("debuggers_install", "")
    disable_uas = params.get("disable_uas", "")
    symbol_files = params.get("symbol_files", "")
    vm_size = int(params.get("mem")) + 100
    nic_cmd = params.get("nic_config_cmd", "")
    dbgview_cmd = params.get("dbgview_cmd", "")
    format_cmd = params.get("format_cmd", "")
    disable_firewall = params.get("disable_firewall", "")
    disable_update = params.get("disable_update", "")
    setup_timeout = int(params.get("setup_timeout", "7200"))
    disk_init_cmd = params.get("disk_init_cmd", "")
    disk_driver_install = params.get("disk_driver_install", "")

    vm_ma_cmd = "wmic computersystem set AutomaticManagedPagefile=False"
    vm_cmd = "wmic pagefileset where name=\"C:\\\\pagefile.sys\" set "
    vm_cmd += "InitialSize=%s,MaximumSize=%s" % (vm_size, vm_size)
    vm_ma_cmd = ""
    vm_cmd = ""
    if symbol_files:
        symbol_cmd = "del  C:\\\\symbols &&"
        symbol_cmd += "git clone %s C:\\\\symbol_files C:\\\\symbols" % \
                      symbol_files
    else:
        symbol_cmd = ""
    wmic_prepare_cmd = "echo exit > cmd && cmd /s wmic"

    error.context("Configure guest system", logging.info)
    cmd_list = [wmic_prepare_cmd, auto_restart, disable_uas, symbol_cmd,
                vm_ma_cmd, vm_cmd, dbgview_cmd, qxl_install, disable_firewall,
                timezone_cmd]
    if nic_cmd:
        for index, nic in enumerate(re.split("\s+", params.get("nics"))):
            setup_params = params.get("nic_setup_params_%s" % nic, "")
            if params.get("vm_arch_name", "") == "x86_64":
                nic_cmd = re.sub("set", "set_64", nic_cmd)
            cmd_list.append("%s %s %s" % (nic_cmd, str(index + 1),
                                          setup_params))
    if disk_init_cmd:
        disk_num = len(re.split("\s+", params.get("images")))
        if disk_driver_install:
            cmd_list.append(disk_driver_install + str(disk_num - 1))
        labels = "IJKLMNOPQRSTUVWXYZ"
        for index, images in enumerate(re.split("\s+", params.get("images"))):
            if index > 0:
                cmd_list.append(disk_init_cmd % (str(index),
                                                 labels[index - 1]))
                format_cmd_image = format_cmd % (labels[index - 1],
                                                 params.get("win_format_%s" % images))
                if params.get("win_extra_%s" % images):
                    format_cmd_image += " %s" % params.get(
                        "win_extra_%s" % images)
                cmd_list.append(format_cmd_image)

    cmd_list += [update_cmd, disable_update]

    failed_flag = 0

    # Check symbol files in guest
    if symbol_files:
        error.context("Update symbol files", logging.info)
        install_check_tool = False
        check_tool_chk = params.get("check_tool_chk",
                                    "C:\debuggers\symchk.exe")
        output = session.cmd_output(check_tool_chk)
        if "cannot find" in output:
            install_check_tool = True

        if install_check_tool:
            output = session.cmd_output(debuggers_install)
        symbol_file_check = params.get("symbol_file_check")
        symbol_file_download = params.get("symbol_file_download")

        symbol_check_pattern = params.get("symbol_check_pattern")
        symbol_pid_pattern = params.get("symbol_pid_pattern")
        download = utils_test.BackgroundTest(session.cmd,
                                            (symbol_file_download,
                                             setup_timeout))

        sessioncheck = vm.wait_for_login(timeout=timeout)
        download.start()
        while download.is_alive():
            o = sessioncheck.cmd_output(symbol_file_check, setup_timeout)
            if symbol_check_pattern in o:
                # Check is done kill download process
                cmd = "tasklist /FO list"
                s, o = sessioncheck.cmd_status_output(cmd)
                pid = re.findall(symbol_pid_pattern, o, re.S)
                if pid:
                    cmd = "taskkill /PID %s /F" % pid[0]
                    try:
                        sessioncheck.cmd(cmd)
                    except Exception:
                        pass
                    break
            time.sleep(5)
        sessioncheck.close()
        download.join()

    for cmd in cmd_list:
        if len(cmd) > 0:
            s = 0
            try:
                s, o = session.cmd_status_output(cmd, timeout=setup_timeout)
            except Exception, err:
                failed_flag += 1
                utils_misc.log_line(
                    error_log, "Unexpected exception: %s" % err)
            if s != 0:
                failed_flag += 1
                utils_misc.log_line(error_log, o)

    if failed_flag != 0:
        raise error.TestFail("Have %s setup fialed. Please check the log."
                             % failed_flag)
