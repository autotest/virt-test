import logging, time, os
from autotest.client.shared import error
from autotest.client import utils
from virttest import data_dir


@error.context_aware
def run_floppy(test, params, env):
    """
    Test virtual floppy of guest:

    1) Create a floppy disk image on host
    2) Start the guest with this floppy image.
    3) Make a file system on guest virtual floppy.
    4) Calculate md5sum value of a file and copy it into floppy.
    5) Verify whether the md5sum does match.

    @param test: KVM test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    def master_floppy(params):
        error.context("creating test floppy")
        floppy = params.get("floppy_name")
        if not os.path.isabs(floppy):
            floppy = os.path.join(data_dir.get_data_dir(), floppy)
        utils.run("dd if=/dev/zero of=%s bs=512 count=2880" % floppy)


    master_floppy(params)
    vm = env.get_vm(params["main_vm"])
    vm.create()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    dest_dir = params.get("mount_dir")
    # If mount_dir specified, treat guest as a Linux OS
    # Some Linux distribution does not load floppy at boot and Windows
    # needs time to load and init floppy driver
    if dest_dir:
        lsmod = session.cmd("lsmod")
        if not 'floppy' in lsmod:
            session.cmd("modprobe floppy")
    else:
        time.sleep(20)

    error.context("Formating floppy disk before using it")
    format_cmd = params.get("format_floppy_cmd")
    session.cmd(format_cmd, timeout=120)
    logging.info("Floppy disk formatted successfully")

    source_file = params.get("source_file")
    dest_file = params.get("dest_file")

    if dest_dir:
        error.context("Mounting floppy")
        session.cmd("mount /dev/fd0 %s" % dest_dir)
    error.context("Testing floppy")
    session.cmd(params.get("test_floppy_cmd"))

    try:
        error.context("Copying file to the floppy")
        md5_cmd = params.get("md5_cmd")
        if md5_cmd:
            md5_source = session.cmd("%s %s" % (params.get("md5_cmd"),
                                                source_file))
            try:
                md5_source = md5_source.split(" ")[0]
            except IndexError:
                error.TestError("Failed to get md5 from source file, output: "
                                "'%s'" % md5_source)
        else:
            md5_source = None

        session.cmd("%s %s %s" % (params.get("copy_cmd"), source_file,
                    dest_file))
        logging.info("Succeed to copy file '%s' into floppy disk" % source_file)

        error.context("Checking if the file is unchanged after copy")
        if md5_cmd:
            md5_dest = session.cmd("%s %s" % (params.get("md5_cmd"),
                                              dest_file))
            try:
                md5_dest = md5_dest.split(" ")[0]
            except IndexError:
                error.TestError("Failed to get md5 from dest file, output: "
                                "'%s'" % md5_dest)
            if md5_source != md5_dest:
                raise error.TestFail("File changed after copy to floppy")
        else:
            md5_dest = None
            session.cmd("%s %s %s" % (params.get("diff_file_cmd"), source_file,
                        dest_file))
    finally:
        clean_cmd = "%s %s" % (params.get("clean_cmd"), dest_file)
        session.cmd(clean_cmd)
        if dest_dir:
            session.cmd("umount %s" % dest_dir)
        session.close()
