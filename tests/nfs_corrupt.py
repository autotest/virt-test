import logging, commands, re
from autotest_lib.client.common_lib import error
from autotest_lib.client.virt import virt_utils

def run_nfs_corrupt(test, params, env):
    """
    Test if VM paused when image NFS shutdown, the drive option 'werror' should
    be stop, the drive option 'cache' should be none.

    1) Setup NFS service on host
    2) Boot up a VM using another disk on NFS server and write the disk by dd
    3) Check if VM status is 'running'
    4) Stop NFS service on host
    5) Check if VM status is 'paused'
    6) Start NFS service on host and continue VM by monitor command
    7) Check if VM status is 'running'

    @param test: kvm test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """

    def get_vm_status():
        status = re.findall("VM status: (.*)", vm.monitor.info("status"))
        if not status:
            logging.info("Could not get VM status")
            return None
        return status[0]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    nfs_devname = params.get("nfs_devname")
    if params.get("drive_format") == "virtio":
        nfs_devname = "/dev/vdb"

    # Write disk on NFS server
    write_disk_cmd = "dd if=/dev/urandom of=%s" % nfs_devname
    logging.info("Write disk on NFS server, cmd: %s" % write_disk_cmd)
    session.sendline(write_disk_cmd)
    try:
        # Read some command output, it will be timeout
        logging.debug(session.read_up_to_prompt(timeout=30))
    except Exception:
        pass

    if get_vm_status() != "running":
        raise error.TestError("Guest is not running before stop NFS")
    try:
        logging.info("Stop NFS service")
        commands.getoutput("service nfs stop")
        if not "stopped" in commands.getoutput("service nfs status"):
            raise error.TestError("Could not stop NFS service")
        if not virt_utils.wait_for(lambda: get_vm_status() == "paused",
                                  int(params.get('wait_paused_timeout', 120))):
            raise error.TestError("Guest is not paused after stop NFS")
    finally:
        logging.info("Restart NFS service")
        commands.getoutput("service nfs restart")
        if not "running" in commands.getoutput("service nfs status"):
            raise error.TestError("Could not start NFS service")

    logging.info("Send monitor cmd: cont")
    vm.monitor.cmd("cont")

    if not virt_utils.wait_for(lambda: get_vm_status() != "running", 20):
        raise error.TestError("Guest does not restore to 'running' status")

    session.close()
