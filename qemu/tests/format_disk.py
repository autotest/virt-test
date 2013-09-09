import logging
import re
from autotest.client.shared import error
from virttest import utils_misc, aexpect


@error.context_aware
def run_format_disk(test, params, env):
    """
    Format guest disk:
    1) Boot guest with second disk
    2) Login to the guest
    3) Get disk list in guest
    4) Create partition on disk
    5) Format the disk
    6) Mount the disk
    7) Read in the file to see whether content has changed
    8) Umount the disk (Optional)
    9) Check dmesg output in guest (Optional)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error.context("Login to the guest", logging.info)
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    cmd_timeout = int(params.get("cmd_timeout", 360))

    # Create a partition on disk
    create_partition_cmd = params.get("create_partition_cmd")
    if create_partition_cmd:
        has_dispart = re.findall("diskpart", create_partition_cmd, re.I)
        if (params.get("os_type") == 'windows' and has_dispart):
            error.context("Get disk list in guest")
            list_disk_cmd = params.get("list_disk_cmd")
            s, o = session.cmd_status_output(list_disk_cmd,
                                             timeout=cmd_timeout)
            for i in re.findall("Disk*.(\d+)\s+Offline", o):
                error.context("Set disk '%s' to online status" % i,
                              logging.info)
                set_online_cmd = params.get("set_online_cmd") % i
                s, o = session.cmd_status_output(set_online_cmd,
                                                 timeout=cmd_timeout)
                if s != 0:
                    raise error.TestFail("Can not set disk online %s" % o)

        error.context("Create partition on disk", logging.info)
        s, o = session.cmd_status_output(create_partition_cmd,
                                         timeout=cmd_timeout)
        if s != 0:
            raise error.TestFail(
                "Failed to create partition with error: %s" % o)
        logging.info("Output of command of create partition on disk: %s" % o)

    format_cmd = params.get("format_cmd")
    if format_cmd:
        error.context("Format the disk with cmd '%s'" % format_cmd,
                      logging.info)
        s, o = session.cmd_status_output(format_cmd,
                                         timeout=cmd_timeout)
        if s != 0:
            raise error.TestFail("Failed to format with error: %s" % o)
        logging.info("Output of format disk command: %s" % o)

    mount_cmd = params.get("mount_cmd")
    if mount_cmd:
        error.context("Mount the disk with cmd '%s'" % mount_cmd, logging.info)
        s, o = session.cmd_status_output(mount_cmd, timeout=cmd_timeout)
        if s != 0:
            raise error.TestFail("Failed to mount with error: %s" % o)
        logging.info("Output of mount disk command: %s" % o)

    testfile_name = params.get("testfile_name")
    if testfile_name:
        error.context("Write some random string to test file", logging.info)
        ranstr = utils_misc.generate_random_string(100)

        writefile_cmd = params["writefile_cmd"]
        writefile_cmd = writefile_cmd % (ranstr, testfile_name)
        s, o = session.cmd_status_output(writefile_cmd, timeout=cmd_timeout)
        if s != 0:
            raise error.TestFail("Write to file error: %s" % o)

        error.context("Read in the file to see whether content has changed",
                      logging.info)
        readfile_cmd = params["readfile_cmd"]
        readfile_cmd = readfile_cmd % testfile_name
        s, o = session.cmd_status_output(readfile_cmd, timeout=cmd_timeout)
        if s != 0:
            raise error.TestFail("Read file error: %s" % o)
        if o.strip() != ranstr:
            raise error.TestFail("The content written to file has changed")

    umount_cmd = params.get("umount_cmd")
    if umount_cmd:
        error.context("Unmounting disk(s) after file write/read operation")
        session.cmd(umount_cmd)

    output = ""
    try:
        output = session.cmd("dmesg -c")
        error.context("Checking if there are I/O error messages in dmesg")
    except aexpect.ShellCmdError:
        pass

    io_error_msg = []
    for line in output.splitlines():
        if "Buffer I/O error" in line:
            io_error_msg.append(line)
        if re.search("reset \w+ speed USB device", line):
            io_error_msg.append(line)

    if io_error_msg:
        e_msg = "IO error found on guest's dmesg when formatting USB device"
        logging.error(e_msg)
        for line in io_error_msg:
            logging.error(line)
        raise error.TestFail(e_msg)

    session.close()
