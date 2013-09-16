import time
import sys
import re
import logging
import os

from autotest.client.shared import error, utils
from virttest import utils_test
from virttest import utils_misc
from virttest import data_dir
from virttest import env_process


@error.context_aware
def run_win_virtio_update(test, params, env):
    """
    Update virtio driver:
    1) Boot up guest with default devices and virtio_win iso
    2) Install virtio driver
    3) Check dirver info

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def check_cdrom(timeout):
        cdrom_chk_cmd = "echo list volume > cmd && echo exit >>"
        cdrom_chk_cmd += " cmd && diskpart /s cmd"
        vols = []
        start_time = time.time()
        while time.time() - start_time < timeout:
            vols_str = session.cmd(cdrom_chk_cmd)

            if len(re.findall("CDFS.*Healthy", vols_str)) >= cdrom_num:
                vols = re.findall(".*CDFS.*?Healthy.*\n", vols_str)
                break
        return vols

    if params.get("case_type") == "driver_install":
        error.context("Update the device type to default.", logging.info)
        default_drive_format = params.get("default_drive_format", "ide")
        default_nic_model = params.get("default_nic_model", "rtl8139")
        images = params.get("images")
        main_image = re.split("\s+", images)[0]
        nics = params.get("nics")
        main_nic = re.split("\s+", nics)[0]
        default_display = params.get("default_display", "vnc")

        default_parameters = {"default_drive_format": default_drive_format,
                              "default_nic_model": default_nic_model,
                              "default_display": default_display}

        for key in default_parameters:
            params[key[8:]] = default_parameters[key]

    if params.get("prewhql_install") == "yes":
        error.context("Prepare the prewhql virtio_win driver iso")
        url_virtio_win = params.get("url_virtio_win")
        if os.path.isdir("/tmp/virtio_win"):
            utils.system("rm -rf /tmp/virtio_win")
        utils.system("mkdir /tmp/virtio_win")

        virtio_win = utils.unmap_url("/tmp/virtio_win", url_virtio_win,
                                     "/tmp/virtio_win")
        if re.findall("zip$", url_virtio_win):
            utils.system("cd /tmp/virtio_win; unzip *; rm -f *.zip")

        virtio_version = params.get("virtio_version", "unknown")
        virtio_iso = params.get("cdrom_virtio", "/tmp/prewhql.iso")
        utils.system("mkisofs -J -o %s /tmp/virtio_win" % virtio_iso)

    drivers_install = re.split(";", params.get("drivers_install"))

    timeout = float(params.get("login_timeout", 240))

    install_cmds = {}
    check_str = {}
    check_cmds = {}
    op_cmds = {}
    setup_ps = False

    error.context("Fill up driver install command line", logging.info)
    for driver in drivers_install:
        params_driver = params.object_params(driver)
        mount_point = params_driver.get("mount_point")
        storage_path = params_driver.get("cdrom_virtio")
        re_hw_id = params_driver.get("re_hw_id", "(PCI.{14,50})\r\n")
        driver_install_cmd = params_driver.get("driver_install_cmd")
        if "hwidcmd" in driver_install_cmd:
            pattern_drive = params.get("pattern_drive",
                                       "\s+\w:(.[^\s]+)\s+hwidcmd")
            driver_path = re.findall(pattern_drive, driver_install_cmd)[0]
            driver_path = "/".join(driver_path.split("\\\\")[1:])
            storage_path = utils_misc.get_path(
                data_dir.get_data_dir(), storage_path)
            hw_id = utils_test.get_driver_hardware_id(driver_path,
                                                      mount_point=mount_point,
                                                      storage_path=storage_path,
                                                      re_hw_id=re_hw_id)
            install_cmds[driver] = re.sub("hwidcmd", hw_id,
                                          driver_install_cmd)
        else:
            install_cmds[driver] = driver_install_cmd

        check_str[driver] = params_driver.get("check_str")
        check_cmds[driver] = params_driver.get("check_cmd")
        op_cmds[driver] = params_driver.get("op_cmd")

        if "pecheck.py" in check_cmds[driver]:
            setup_ps = True

        if params.get("check_info") == "yes":
            mount_point = params.get("virtio_mount_point",
                                     "/tmp/virtio_win")
            iso_path = utils_misc.get_path(data_dir.get_data_dir(),
                                           params.get("cdrom_virtio"))
            utils.system("mount -o loop %s %s" % (iso_path, mount_point))
            pattern_driver = params_driver.get("pattern_driver")
            driver_path = re.findall(pattern_driver,
                                     driver_install_cmd)[0]
            driver_path = "/".join(driver_path.split("\\\\")[1:])
            storage_path = utils_misc.get_path(mount_point, driver_path)
            storage_path = os.path.dirname(storage_path)
            files = " ".join(os.listdir(storage_path))
            file_name = re.findall("\s+(.*?\.inf)", files)
            if file_name:
                file_name = utils_misc.get_path(storage_path,
                                                file_name[0])
            else:
                raise error.TestError("Can not find .inf file.")
            inf = open(file_name)
            inf_context = inf.read()
            inf.close()
            utils.system("umount %s" % mount_point)
            patterns_check_str = params_driver.get("check_str")
            check_str[driver] = {}
            for i in patterns_check_str.split(";"):
                check_n, check_p = i.split("::")
                check_str[driver][check_n] = re.findall(check_p,
                                                        inf_context)[0]
            check_cmds[driver] = {}
            for i in params_driver.get("check_cmd").split(";"):
                cmd_n, cmd_c = i.split("::")
                cmd_c = re.sub("DRIVER_PATH",
                               params_driver.get("sys_file_path", ""),
                               cmd_c)
                cmd_c = re.sub("DRIVER_PATTERN_%s" % cmd_n,
                               params_driver.get("info_pattern_%s" % cmd_n,
                                                 ""),
                               cmd_c)
                check_cmds[driver][cmd_n] = cmd_c

    error.context("Boot up guest with setup parameters", logging.info)
    vm = "vm1"
    vm_params = params.copy()
    env_process.preprocess_vm(test, vm_params, env, vm)
    vm = env.get_vm(vm)
    session = vm.wait_for_login(timeout=timeout)

    cdroms = params.get("cdroms")
    cdrom_num = len(re.split("\s+", cdroms.strip()))
    init_timeout = int(params.get("init_timeout", "60"))

    error.context("Check the cdrom is available")
    volumes = check_cdrom(init_timeout)
    vol_info = []
    for volume in volumes:
        vol_info += re.findall("Volume\s+\d+\s+(\w).*?(\d+)\s+\w+", volume)
    if len(volumes) > 1:
        if int(vol_info[0][1]) > int(vol_info[1][1]):
            vol_utils = vol_info[0][0]
            vol_virtio = vol_info[1][0]
        else:
            vol_utils = vol_info[1][0]
            vol_virtio = vol_info[0][0]
    else:
        vol_utils = vol_info[0][0]

    error.context("Install drivers", logging.info)
    for driver in drivers_install:
        if params.get("kill_rundll", "no") == "yes":
            kill_cmd = 'tasklist | find /I "rundll32"'
            status, tasks = session.cmd_status_output(kill_cmd)
            if status == 0:
                for i in re.findall("rundll32.*?(\d+)", tasks):
                    session.cmd('taskkill /PID %s' % i)
        if install_cmds:
            cmd = re.sub("WIN_UTILS", vol_utils, install_cmds[driver])
            cmd = re.sub("WIN_VIRTIO", vol_virtio, cmd)
            session.cmd(cmd)
            session = vm.reboot(session)

    if params.get("check_info") == "yes":
        fail_log = "Details check failed in guest."
        fail_log += " Please check the error_log. "
    else:
        fail_log = "Failed to install:"
    error_log = open("%s/error_log" % test.resultsdir, "w")
    fail_flag = False
    error.context("Check driver available in guest", logging.info)
    if setup_ps:
        setup_cmd = params.get("python_scripts")
        session.cmd(setup_cmd)

    for driver in drivers_install:
        error_log.write("For driver %s:\n" % driver)
        if isinstance(check_str[driver], dict):
            for i in check_str[driver]:
                output = session.cmd(check_cmds[driver][i])
                if not re.findall(check_str[driver][i], output, re.I):
                    fail_flag = True
                    fail_log += " %s" % driver
                    fail_log += "(%s) is not right; " % i
                    error_log.write("inf:\t%s\n" % check_str[driver][i])
                    error_log.write("sys: \t%s\n" % output)
        else:
            output = session.cmd(check_cmds[driver])
            if not re.findall(check_str[driver], output, re.I):
                fail_falg = True
                fail_log += " %s" % driver
                error_log.write("Check command output: %s\n" % output)

    if fail_flag:
        raise error.TestFail(fail_log)

    if check_cmds:
        error.context("Do more operates in guest to check the driver",
                      logging.info)
        for driver in drivers_install:
            if isinstance(check_cmds[driver], str):
                session.cmd(cmd)
            else:
                for cmd in check_cmds[driver]:
                    session.cmd(cmd)
