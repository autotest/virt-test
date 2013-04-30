import logging, time, re
from autotest.client import utils
from autotest.client.shared import error
from virttest import  remote, utils_misc

@error.context_aware
def run_virtual_nic_send_buffer(test, params, env):
    """
    Test Step:
        1. boot up guest with this option sndbuf=1048576,...
        2. Transfer file from guest to extrnal host by UDP
        3. boot up four guest in the same host, transfer files between them
        4. verify that it could not block other guests on the same host.
        5. Repeat 1-4, test with the sndbuf=0, and default value in 6.2

    Params:
        @param test: kvm test object
        @param params: Dictionary with the test parameters
        @param env: Dictionary with test environment.
    """

    timeout = int(params.get("login_timeout", '360'))
    transfer_timeout = int(params.get("transfer_timeout", '120'))
    password = params.get("password")
    username = params.get("username")
    shell_port = params.get("shell_port")
    tmp_dir = params.get("tmp_dir", "/tmp/")
    clean_cmd = params.get("clean_cmd", "rm -f")
    filesize = int(params.get("filesize", '100'))

    dd_cmd = params.get("dd_cmd", "dd if=/dev/urandom of=%s bs=1M count=%d")
    md5_check = params.get("md5_check", "md5sum %s")

    sessions = []
    addresses = []
    vms = []

    error.context("Init boot the vms")
    for vm in params.get("vms", "vm1 vm2 vm3 vm4").split():
        vms.append(env.get_vm(vm))
    for vm in vms :
        vm.verify_alive()
        sessions.append(vm.wait_for_login(timeout=timeout))
        addresses.append(vm.get_address())

    src_file = (tmp_dir + "src-%s" % utils_misc.generate_random_string(8))
    dst_file = (tmp_dir + "dst-%s" %  utils_misc.generate_random_string(8))
    data_port = params.get("data_port", "8888")

    prompt = params.get("shell_prompt", "[\#\$]")
    client = params.get("shell_client")

    logging.info("Creating %dMB file on every guest", filesize)
    for session in sessions :
        session.cmd(dd_cmd  % (src_file, filesize), timeout=timeout)

    #transfer datat form guest to host
    for vm in vms:
        error.context("Transfer date from %s to host" % vm, logging.info)
        vm.copy_files_from(src_file, dst_file, timeout=transfer_timeout)

    #transfer data between guest
    for vm_src in addresses:
        for vm_dst in addresses:
            if vm_src != vm_dst:
                error.context("Transfering data %s to %s" % (vm_src, vm_dst),
                              logging.info)
                remote.nc_copy_between_remotes(vm_src, vm_dst, shell_port,
                                               password, password,
                                               username, username,
                                               src_file, dst_file,
                                               client, prompt,
                                               data_port, "udp")
    for session in sessions:
        if session:
            session.close()
