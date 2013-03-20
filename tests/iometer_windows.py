import logging, time, re
from autotest.client.shared import error
from autotest.client.virt import virt_vm


def run_iometer_windows(test, params, env):
    """
    Run Iometer for windows on a windows guest:
    1) Boot guest with second disk
    2) Log into a guest
    3) Install Iometer
    4) Execute the Iometer test contained in the winutils.iso

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    def check_cdrom(timeout):
        cdrom_chk_cmd = "echo list volume > cmd && echo exit >>"
        cdrom_chk_cmd += " cmd && diskpart /s cmd"
        vols = []
        start_time = time.time()
        while time.time() - start_time < timeout:
            vols_str = session.cmd(cdrom_chk_cmd)
            logging.info("vols_str is %s" % vols_str)
            if len(re.findall("CDFS.*Healthy", vols_str)) >= 1:
                vols = re.findall(".*CDFS.*?Healthy.*\n", vols_str)
                logging.info("vols is %s" % vols)
                break
        return vols

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    cmd_timeout = int(params.get("cmd_timeout",1200))

    # Create a partition on disk
    time.sleep(120)
    create_partition_cmd = params.get("create_partition_cmd")
    (s, o) = session.get_command_status_output(cmd=create_partition_cmd,
                                                timeout=cmd_timeout)
    if s != 0:
        raise error.TestFail("Failed to create partition with error: %s" % o)
    logging.info("Output of command of create partition on disk: %s" % o)

    # Format the disk
    format_cmd = params.get("format_cmd")
    (s, o) = session.get_command_status_output(cmd=format_cmd,
                                                timeout=cmd_timeout)
    if s != 0:
        raise error.TestFail("Failed to format with error: %s" % o)
    logging.info("Output of format disk command: %s" % o)

    # Install Iometer
    init_timeout = int(params.get("init_timeout", "60"))
    volumes = check_cdrom(init_timeout)
    vol_utils = re.findall("Volume\s+\d+\s+(\w).*?\d+\s+\w+", volumes[0])[0]

    install_iometer_cmd = params.get("iometer_installation_cmd")
    install_iometer_cmd = re.sub("WIN_UTILS", vol_utils, install_iometer_cmd)
    (s, o) = session.get_command_status_output(cmd=install_iometer_cmd,
                                                timeout=cmd_timeout)
    if s !=0:
        raise error.TestFail("Failed to install iometer with error: %s" % o)
    else:
        logging.info("Complete installation of iometer")

    # Run Iometer
    cmd_reg = params.get("iometer_reg")
    cmd_run = params.get("iometer_run")
    t = int(params.get("iometer_timeout"))
    cmd_reg = re.sub("WIN_UTILS", vol_utils, cmd_reg)
    cmd_run = re.sub("WIN_UTILS", vol_utils, cmd_run)

    logging.info("Register Iometer on guest, timeout %ss", cmd_timeout)
    (s, o) = session.cmd_status_output(cmd=cmd_reg, timeout=cmd_timeout)
    if s !=0:
        raise error.TestFail("Failed to register iometer with error: %s" % o)
    else:
        logging.info("Complete iometer register")
    logging.info("Running Iometer command on guest, timeout %ss", cmd_timeout)
    (s, o) = session.cmd_status_output(cmd=cmd_run, timeout=t)
    if s !=0:
        raise error.TestFail("Failed to run iometer with error: %s" % o)
    else:
        logging.info("Completed iometer testing")
    guest_path = params.get("guest_path")
    vm.copy_files_from(guest_path,test.resultsdir)

    session.close()
