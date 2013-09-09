import logging
import os
import re
from autotest.client import utils
from autotest.client.shared import error
from virttest import remote, utils_misc, utils_net


@error.context_aware
def run_transfer_file_over_ipv6(test, params, env):
    """
    Test Step
        1. boot up two virtual machine
        2. Transfer data: host <--> guest1 <--> guest2 <-->host via ipv6
        3. after data transfer, check data have no change
    Params:
        @param test: QEMU test object
        @param params: Dictionary with the test parameters
        @param env: Dictionary with test environment.
    """
    timeout = int(params.get("login_timeout", '360'))
    client = params.get("file_transfer_client")
    port = params.get("file_transfer_port")
    password = params.get("password")
    username = params.get("username")
    tmp_dir = params.get("tmp_dir", "/tmp/")
    filesize = int(params.get("filesize", '4096'))
    dd_cmd = params.get("dd_cmd")
    file_trans_timeout = int(params.get("file_trans_timeout", '1200'))
    file_md5_check_timeout = int(params.get("file_md5_check_timeout", '600'))

    def get_linux_ipv6_linklocal_address(ifname, session=None):
        """
        Get host/guest ipv6 linklocal address via ifname
        """
        if session is not None:
            o = session.cmd_output("ifconfig %s" % ifname)
        else:
            o = utils.system_output("ifconfig %s" % ifname)
        ipv6_address_reg = re.compile(r"(fe80::[^\s|/]*)")
        if o:
            ipv6_linklocal_address = ipv6_address_reg.findall(o)
            if not ipv6_linklocal_address:
                raise error.TestError("Can't get %s linklocal address"
                                      % ifname)
            return ipv6_linklocal_address[0]
        else:
            return None

    def get_file_md5sum(file_name, session, timeout):
        """
        Get file md5sum from guest.
        """
        logging.info("Get md5sum of the file:'%s'" % file_name)
        try:
            o = session.cmd_output("md5sum %s" % file_name, timeout=timeout)
            file_md5sum = re.findall("\w+", o)[0]
        except IndexError:
            raise error.TestError("Could not get file md5sum in guest")
        return file_md5sum

    sessions = {}
    addresses = {}
    inet_name = {}
    vms = []

    error.context("Boot vms for test", logging.info)
    for vm_name in params.get("vms", "vm1 vm2").split():
        vms.append(env.get_vm(vm_name))

    # config ipv6 address host and guest.
    host_ifname = params.get("netdst")

    for vm in vms:
        vm.verify_alive()
        sessions[vm] = vm.wait_for_login(timeout=timeout)
        inet_name[vm] = utils_net.get_linux_ifname(sessions[vm],
                                                   vm.get_mac_address())
        addresses[vm] = get_linux_ipv6_linklocal_address(inet_name[vm],
                                                         sessions[vm])

    # prepare test data
    guest_path = (tmp_dir + "src-%s" % utils_misc.generate_random_string(8))
    dest_path = (tmp_dir + "dst-%s" % utils_misc.generate_random_string(8))
    host_path = os.path.join(test.tmpdir, "tmp-%s" %
                             utils_misc.generate_random_string(8))
    logging.info("Test setup: Creating %dMB file on host", filesize)
    utils.run(dd_cmd % (host_path, filesize))

    try:
        src_md5 = (utils.hash_file(host_path, method="md5"))
        # transfer data
        for vm in vms:
            error.context("Transfer date from host to %s" % vm.name,
                          logging.info)
            remote.copy_files_to("%s%%%s" % (addresses[vm], host_ifname),
                                 client, username, password, port,
                                 host_path, guest_path,
                                 timeout=file_trans_timeout)
            dst_md5 = get_file_md5sum(guest_path, sessions[vm],
                                      timeout=file_md5_check_timeout)
            if dst_md5 != src_md5:
                raise error.TestFail("File changed after transfer host -> %s"
                                     % vm.name)

        for vm_src in addresses:
            for vm_dst in addresses:
                if vm_src != vm_dst:
                    error.context("Transferring data from %s to %s" %
                                  (vm_src.name, vm_dst.name), logging.info)
                    remote.scp_between_remotes("%s%%%s" % (addresses[vm_src],
                                                           host_ifname),
                                               "%s%%%s" % (addresses[vm_dst],
                                                           inet_name[vm_src]),
                                               port, password, password,
                                               username, username,
                                               guest_path, dest_path,
                                               timeout=file_trans_timeout)
                    dst_md5 = get_file_md5sum(dest_path, sessions[vm_dst],
                                              timeout=file_md5_check_timeout)
                    if dst_md5 != src_md5:
                        raise error.TestFail("File changed transfer %s -> %s"
                                             % (vm_src.name, vm_dst.name))

        for vm in vms:
            error.context("Transfer date from %s to host" % vm.name,
                          logging.info)
            remote.copy_files_from("%s%%%s" % (addresses[vm], host_ifname),
                                   client, username, password, port,
                                   dest_path, host_path,
                                   timeout=file_trans_timeout)
            error.context("Check whether the file changed after trans",
                          logging.info)
            dst_md5 = (utils.hash_file(host_path, method="md5"))
            if dst_md5 != src_md5:
                raise error.TestFail("File changed after transfer",
                                     "Files md5sum mismatch!")
            utils.system_output("rm -rf %s" % host_path, timeout=timeout)

    finally:
        utils.system_output("rm -rf %s" % host_path, timeout=timeout)
        for vm in vms:
            sessions[vm].cmd("rm -rf %s %s" % (guest_path, dest_path),
                             timeout=timeout)
            sessions[vm].close()
