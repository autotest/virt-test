import logging
from autotest.client import utils
from autotest.client.shared import error
from virttest import remote, utils_misc


@error.context_aware
def run_virtual_nic_send_buffer(test, params, env):
    """
    Test Steps:

    1. boot up guest with this option sndbuf=1048576,...
    2. Transfer file from host to guest.
    3. boot up four guest in the same host, transfer files between
       them via udp.
    4. verify that it could not block other guests on the same host.
    5. Repeat 1-4, test with the sndbuf=0, and default value in 6.2.

    Params:
        :param test: QEMU test object.
        :param params: Dictionary with the test parameters.
        :param env: Dictionary with test environment.
    """
    def env_setup(session):
        """
        Linux guest env setup, install udt, set env and iptables
        """
        lib_path = "/usr/lib64"
        if params.get("platform", 64) == 32:
            lib_path = "/usr/lib"
        cmd = r"git clone %s udt-git; " % params.get("udt_url")
        cmd += r"cd udt-git/udt4; make; make install; "
        cmd += r"cp -u src/*.so %s ; " % lib_path
        cmd += r"cp -u app/sendfile app/recvfile /usr/bin/; "
        cmd += r"iptables -I INPUT -p udp  -j ACCEPT; "
        cmd += r"iptables -I OUTPUT -p udp -j ACCEPT "
        if session.cmd_status(cmd):
            raise error.TestError("Install udt on guest failed")

    timeout = int(params.get("login_timeout", '360'))
    transfer_timeout = int(params.get("transfer_timeout", '120'))
    password = params.get("password")
    username = params.get("username")
    shell_port = params.get("shell_port")
    prompt = params.get("shell_prompt", "[\#\$]")
    client = params.get("shell_client")

    tmp_dir = params.get("tmp_dir", "/tmp/")
    host_file = (test.tmpdir + "tmp-%s" % utils_misc.generate_random_string(8))
    src_file = (tmp_dir + "src-%s" % utils_misc.generate_random_string(8))
    dst_file = (tmp_dir + "dst-%s" % utils_misc.generate_random_string(8))
    data_port = params.get("data_port", "9000")
    clean_cmd = params.get("clean_cmd", "rm -f")
    filesize = int(params.get("filesize", '100'))
    dd_cmd = params.get("dd_cmd", "dd if=/dev/urandom of=%s bs=1M count=%d")

    sessions = []
    addresses = []
    vms = []

    error.context("Init boot the vms")
    for vm in params.get("vms", "vm1 vm2 vm3 vm4").split():
        vms.append(env.get_vm(vm))
    for vm in vms:
        vm.verify_alive()
        sessions.append(vm.wait_for_login(timeout=timeout))
        addresses.append(vm.get_address())

    logging.info("Creating %dMb file on host", filesize)
    cmd = dd_cmd % (host_file, filesize)
    utils.run(cmd)

    try:
        error.context("Transfer data from host to each guest")
        for vm in vms:
            error.context("Transferring data from host to guest %s " % vm.name,
                          logging.info)
            vm.copy_files_to(host_file, src_file, timeout=transfer_timeout)

        error.context("Transfer data from guest to host")
        for vm in vms:
            error.context("Transfer date from guest %s to host" % vm.name,
                          logging.info)
            vm.copy_files_from(src_file, host_file, timeout=transfer_timeout)

        # transfer data between guest
        error.context("Transfer data between every guest")
        if params.get("os_type") == "linux":
            for session in sessions:
                env_setup(session)

        for vm_src in addresses:
            for vm_dst in addresses:
                if vm_src != vm_dst:
                    error.context("Transferring data %s to %s" %
                                  (vm_src, vm_dst), logging.info)
                    remote.udp_copy_between_remotes(vm_src, vm_dst,
                                                    shell_port,
                                                    password, password,
                                                    username, username,
                                                    src_file, dst_file,
                                                    client, prompt,
                                                    data_port, timeout=1200)
    finally:
        utils.run("rm -rf %s " % host_file)
        for session in sessions:
            if session:
                session.cmd("%s %s %s" % (clean_cmd, src_file, dst_file))
                session.close()
