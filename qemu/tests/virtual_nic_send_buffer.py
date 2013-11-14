import logging
from autotest.client import utils
from autotest.client.shared import error
from virttest import remote, utils_misc, utils_test


@error.context_aware
def run(test, params, env):
    """
    Test Steps:

    1. boot up guest with this option sndbuf=1048576,...
    2. Transfer file between host and guest (by tcp,udp or both).
    3. Run netperf_udp with burst, check the guest works well.

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
        if '64' not in params.get("vm_arch_name", 'x86_64'):
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
    for vm_name in params.get("vms", "vm1 vm2 vm3 vm4").split():
        vms.append(env.get_vm(vm_name))
    for vm in vms:
        vm.verify_alive()
        sessions.append(vm.wait_for_login(timeout=timeout))
        addresses.append(vm.get_address())

    if params.get("copy_protocol", ""):
        logging.info("Creating %dMb file on host", filesize)
        cmd = dd_cmd % (host_file, filesize)
        utils.run(cmd)
        orig_md5 = utils.hash_file(host_file, method="md5")
    try:
        if "tcp" in params.get("copy_protocol", ""):
            error.context("Transfer data from host to each guest")
            for vm in vms:
                error.context("Transfer data from host to guest %s via tcp" %
                              vm.name, logging.info)
                vm.copy_files_to(host_file, src_file, timeout=transfer_timeout)
            for session in sessions:
                output = session.cmd_output("md5sum %s" % src_file)
                if "such file" in output:
                    remote_hash = "0"
                elif output:
                    remote_hash = output.split()[0]
                else:
                    warn_msg = "MD5 check for remote path %s did not return."
                    logging.warning(warn_msg % src_file)
                    remote_hash = "0"
                if remote_hash != orig_md5:
                    raise error.TestError("Md5sum mismatch, ori:cur - %s:%s" %
                                          (orig_md5, remote_hash))

            error.context("Transfer data from guest to host by tcp")
            for vm in vms:
                error.context("Transfer date from guest %s to host" % vm.name,
                              logging.info)
                vm.copy_files_from(src_file, host_file,
                                   timeout=transfer_timeout)

                current_md5 = utils.hash_file(host_file, method="md5")
                if current_md5 != orig_md5:
                    raise error.TestError("Md5sum mismatch, ori:cur - %s:%s" %
                                          (orig_md5, remote_hash))

        if "udp" in params.get("copy_protocol", ""):
            # transfer data between guest
            error.context("Transfer data between every guest by udp protocol")
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
                                                        data_port,
                                                        timeout=1200)
        # do netperf test:
        sub_test = params.get("sub_test_name", 'netperf_udp')
        for vm in vms:
            params["main_vm"] = vm.name
            error.context("Run subtest %s " % sub_test, logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type=sub_test)
            vm.wait_for_login(timeout=timeout)

    finally:
        utils.system("rm -rf %s " % host_file, ignore_status=True)
        for session in sessions:
            if session:
                session.cmd("%s %s %s" % (clean_cmd, src_file, dst_file),
                            ignore_all_errors=True)
                session.close()
