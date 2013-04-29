"""
@author: Golita Yue <gyue@redhat.com>
@author: Amos Kong <akong@redhat.com>
"""
import string, logging, time, os, re
from autotest.client.shared import error


@error.context_aware
def run_iometer_windows(test, params, env):
    """
    Run Iometer for Windows on a Windows guest:

    1) Boot guest with additional disk
    2) Install Iometer
    3) Execute the Iometer test contained in the winutils.iso
    4) Copy result to host

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    def get_used_ids(session):
        """
        return used device letters;
        """
        cmd = "wmic logicaldisk get DeviceID"
        output = session.cmd(cmd, timeout=360)
        device_ids = re.findall(r'([a-zA-Z]):', output, re.M)
        if device_ids:
            device_ids = map(string.upper, device_ids)
            return set(device_ids)
        return set()


    def get_drive(session):
        """
        return drive letter of WIN_UTILS drive;
        """
        cmd = "wmic datafile where \"FileName='software_install_64' and "
        cmd += "extension='bat'\" get drive"
        info = session.cmd(cmd, timeout=600)
        device = re.search(r'(\w):', info, re.M)
        if not device:
            raise error.TestError("WIN_UTILS drive not found...")
        device = device.group(1)
        return device.upper()


    def get_free_letter(session):
        """
        return free letter which can use for new drive;
        """
        full_ids = set(string.uppercase)
        black_list = set (["A", "B", "C"])
        used_ids = get_used_ids(session)
        free_ids = (full_ids - used_ids - black_list)
        if free_ids:
            return free_ids.pop()
        else:
            raise error.TestError("No avaliable letter can use to new volume")


    def format_iometer_cfg(session, path, device_id="E"):
        """
        reformat Iometer cfg file;
        """
        tmp_path = "/tmp/iometer_windows.cfg"
        vm.copy_files_from(path, tmp_path)
        if not os.path.exists(tmp_path):
            raise error.TestError("Iometer configure file not found")
        cfg = ""
        with open(tmp_path, "r") as cfg_fd:
            cfg = cfg_fd.readlines()
            cfg = "".join(cfg)
            cfg = re.sub(r"[a-zA-Z]:local", "%s:local" % device_id, cfg)
        with open(tmp_path, "w") as cfg_fd:
            cfg_fd.write(cfg)
        vm.copy_files_to(tmp_path, path)


    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    # perpare test params
    cmd_timeout = int(params.get("cmd_timeout", 1200))
    sleep_before_test = int(params.get("sleep_before_test", 0))
    iometer_timeout = int(params.get("iometer_timeout", 1200))

    device_id = get_free_letter(session)
    cdrom = get_drive(session)
    create_partition_cmd = params.get("create_partition_cmd")
    format_cmd = params.get("format_cmd")
    install_iometer_cmd = params.get("iometer_installation_cmd")
    install_iometer_cmd = re.sub("WIN_UTILS", cdrom, install_iometer_cmd)
    create_partition_cmd = re.sub("DEVICEID", device_id, create_partition_cmd)
    format_cmd = re.sub("DEVICEID", device_id , format_cmd)
    cmd_reg = params.get("iometer_reg")
    iometer_cfg = params.get("iometer_cfg")
    guest_path = params.get("guest_path")
    cmd_run = params.get("iometer_run") % (iometer_cfg, guest_path)

    if sleep_before_test:
        logging.info("sleep %ss, wait vds service startup", sleep_before_test)
        time.sleep(sleep_before_test)

    error.context("Format data disk for Iometer test", logging.info)
    logging.debug("Create partition cmd: %s" % create_partition_cmd)
    (s, o) = session.get_command_status_output(cmd=create_partition_cmd,
                                               timeout=cmd_timeout)
    if s != 0:
        raise error.TestFail("Create partition failed with error: %s" % o)

    logging.debug("Format partition cmd: %s" % format_cmd)
    (s, o) = session.get_command_status_output(cmd=format_cmd,
                                               timeout=cmd_timeout)
    if s != 0:
        raise error.TestFail("Format disk failed with error: %s" % o)

    error.context("install iometer app", logging.info)
    (s, o) = session.get_command_status_output(cmd=install_iometer_cmd,
                                                timeout=cmd_timeout)
    if s != 0:
        raise error.TestFail("Install iometer failed with error: %s" % o)

    (s, o) = session.cmd_status_output(cmd=cmd_reg, timeout=cmd_timeout)
    if s != 0:
        raise error.TestFail("Register iometer failed with error: %s" % o)

    error.context("start iometer app", logging.info)
    format_iometer_cfg(session, iometer_cfg, device_id)
    logging.debug("start iometer cmd: %s" % cmd_run)
    (s, o) = session.cmd_status_output(cmd=cmd_run, timeout=iometer_timeout)
    if s != 0:
        raise error.TestFail("Run iometer failed with error: %s" % o)
    guest_path = params.get("guest_path")
    logging.info("Iometer test done, copy result to %s", test.resultsdir)
    vm.copy_files_from(guest_path, test.resultsdir)
    if session:
        session.close()
