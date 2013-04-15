import logging, re
from autotest.client.shared import error
from virttest import utils_misc

def run_format_disk(test, params, env):
    """
    Format guest disk:
    1) Boot guest with second disk
    2) Log into guest
    3) Sent sequence commands which format disk1 and mount it to guest
    4) Write some random str into one file within guest disk1 and read it,
       make sure all right.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    cmd_timeout = int(params.get("cmd_timeout", 360))

    # Create a partition on disk
    create_partition_cmd = params.get("create_partition_cmd")
    if create_partition_cmd:
        if (params.get("os_type") == 'windows'
            and re.findall("diskpart", create_partition_cmd, re.I)):
            list_disk_cmd = params.get("list_disk_cmd")
            s, o = session.get_command_status_output(list_disk_cmd,
                                                     timeout=cmd_timeout)
            for i in re.findall("Disk*.(\d+)\s+Offline",o):
                set_online_cmd = params.get("set_online_cmd") % i
                s, o = session.get_command_status_output(set_online_cmd,
                                                     timeout=cmd_timeout)
                if s !=0:
                    raise error.TestFail("Can not set disk online %s" % o)

        s, o = session.get_command_status_output(create_partition_cmd,
                                                 timeout=cmd_timeout)
        if s != 0:
            raise error.TestFail("Failed to create partition with error: %s" % o)
        logging.info("Output of command of create partition on disk: %s" % o)

    # Format the disk
    format_cmd = params.get("format_cmd")
    if format_cmd:
        s, o = session.get_command_status_output(format_cmd,
                                                 timeout=cmd_timeout)
        if s != 0:
            raise error.TestFail("Failed to format with error: %s" % o)
        logging.info("Output of format disk command: %s" % o)

    # Mount the disk
    mount_cmd = params.get("mount_cmd")
    if mount_cmd:
        s, o = session.get_command_status_output(mount_cmd, timeout=cmd_timeout)
        if s != 0:
            raise error.TestFail("Failed to mount with error: %s" % o)
        logging.info("Output of mount disk command: %s" % o)

    # Write some random string to test file
    testfile_name = params.get("testfile_name")
    ranstr = utils_misc.generate_random_string(100)

    writefile_cmd = params.get("writefile_cmd")
    wfilecmd = writefile_cmd + " " + ranstr + " >" + testfile_name
    s, o = session.get_command_status_output(wfilecmd, timeout=cmd_timeout)
    if s != 0:
        raise error.TestFail("Write to file error: %s" % o)

    # Read in the file to see whether content is changed
    readfile_cmd = params.get("readfile_cmd")
    rfilecmd = readfile_cmd + " " + testfile_name
    s, o = session.get_command_status_output(rfilecmd, timeout=cmd_timeout)
    if s != 0:
        raise error.TestFail("Read file error: %s" % o)
    if o.strip() != ranstr:
        raise error.TestFail("The content writen to file is changed")
    session.close()
