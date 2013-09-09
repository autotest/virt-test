import logging
import time
import re
from autotest.client.shared import error
from virttest import utils_test, remote, utils_net


@error.context_aware
def run_multi_vms_nics(test, params, env):
    """
    KVM multi test:
    1) Log into guests
    2) Check all the nics available or not
    3) Ping among guest nic and host
       3.1) Ping with different packet size
       3.2) Flood ping test
       3.3) Final ping test
    4) Transfer files among guest nics and host
       4.1) Create file by dd command in guest
       4.2) Transfer file between nics
       4.3) Compare original file and transferred file
    5) ping among different nics
       5.1) Ping with different packet size
       5.2) Flood ping test
       5.3) Final ping test
    6) Transfer files among different nics
       6.1) Create file by dd command in guest
       6.2) Transfer file between nics
       6.3) Compare original file and transferred file
    7) Repeat step 3 - 6 on every nic.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def ping(session, nic, dst_ip, strick_check, flood_minutes):
        d_packet_size = [1, 4, 48, 512, 1440, 1500, 1505, 4054, 4055, 4096,
                         4192, 8878, 9000, 32767, 65507]
        packet_size = params.get("packet_size", "").split() or d_packet_size
        for size in packet_size:
            error.context("Ping with packet size %s" % size, logging.info)
            status, output = utils_test.ping(dst_ip, 10, interface=nic,
                                             packetsize=size,
                                             timeout=30, session=session)
            if strict_check:
                ratio = utils_test.get_loss_ratio(output)
                if ratio != 0:
                    raise error.TestFail("Loss ratio is %s for packet size"
                                         " %s" % (ratio, size))
            else:
                if status != 0:
                    raise error.TestFail("Ping returns non-zero value %s" %
                                         output)

        error.context("Flood ping test", logging.info)
        utils_test.ping(dst_ip, None, interface=nic, flood=True,
                        output_func=None, timeout=flood_minutes * 60,
                        session=session)
        error.context("Final ping test", logging.info)
        counts = params.get("ping_counts", 100)
        status, output = utils_test.ping(dst_ip, counts, interface=nic,
                                         timeout=float(counts) * 1.5,
                                         session=session)
        if strick_check == "yes":
            ratio = utils_test.get_loss_ratio(output)
            if ratio != 0:
                raise error.TestFail("Packet loss ratio is %s after flood"
                                     % ratio)
        else:
            if status != 0:
                raise error.TestFail("Ping returns non-zero value %s" %
                                     output)

    def file_transfer(session, src, dst):
        username = params.get("username", "")
        password = params.get("password", "")
        src_path = "/tmp/1"
        dst_path = "/tmp/2"
        port = int(params["file_transfer_port"])

        cmd = "dd if=/dev/urandom of=%s bs=100M count=1" % src_path
        cmd = params.get("file_create_cmd", cmd)

        error.context("Create file by dd command, cmd: %s" % cmd, logging.info)
        session.cmd(cmd)

        transfer_timeout = int(params.get("transfer_timeout"))
        log_filename = "scp-from-%s-to-%s.log" % (src, dst)
        error.context("Transfer file from %s to %s" % (src, dst), logging.info)
        remote.scp_between_remotes(src, dst, port, password, password,
                                   username, username, src_path, dst_path,
                                   log_filename=log_filename,
                                   timeout=transfer_timeout)
        src_path = dst_path
        dst_path = "/tmp/3"
        log_filename = "scp-from-%s-to-%s.log" % (dst, src)
        error.context("Transfer file from %s to %s" % (dst, src), logging.info)
        remote.scp_between_remotes(dst, src, port, password, password,
                                   username, username, src_path, dst_path,
                                   log_filename=log_filename,
                                   timeout=transfer_timeout)
        error.context("Compare original file and transferred file",
                      logging.info)

        cmd1 = "md5sum /tmp/1"
        cmd2 = "md5sum /tmp/3"
        md5sum1 = session.cmd(cmd1).split()[0]
        md5sum2 = session.cmd(cmd2).split()[0]
        if md5sum1 != md5sum2:
            raise error.TestError("File changed after transfer")

    vm_list = []
    session_list = []
    vms = params["vms"].split()
    timeout = float(params.get("login_timeout", 360))
    mac_ip_filter = params["mac_ip_filter"]
    strict_check = params.get("strick_check", "no")
    host_ip = utils_net.get_ip_address_by_interface(params.get("netdst"))
    host_ip = params.get("srchost", host_ip)
    flood_minutes = float(params["flood_minutes"])
    for vm_name in vms:
        vm = utils_test.get_living_vm(env, vm_name)
        vm_list.append(vm)
        session_list.append(vm.wait_for_login(timeout=timeout))

    ip_list = []

    error.context("Check all the nics available or not", logging.info)
    count_nics = len(params.get("nics").split())
    for i in session_list:
        ips = []
        cmd = params.get("net_check_cmd")
        end_time = time.time() + timeout
        while time.time() < end_time:
            status, output = i.get_command_status_output(cmd)
            if status:
                err_msg = "Can not get ip from guest."
                err_msg += " Cmd '%s' fail with output: %s" % (cmd, output)
                logging.error(err_msg)
            ips = re.findall(mac_ip_filter, output, re.S)
            if count_nics == len(ips):
                break
            time.sleep(2)
        else:
            err_log = "Not all nics get ip.  Set '%s' nics." % count_nics
            err_log += " Guest only get '%s' ip(s). " % len(ips)
            err_log += " Command '%s' output in guest:\n%s" % (cmd, output)
            raise error.TestFail(err_log)
        for ip in ips:
            ip_list.append(ip + (i,))
    ip_list_len = len(ip_list)
    # ping and file transfer test
    for src_ip_index in range(ip_list_len):
        error.context("Ping test from guest to host", logging.info)
        src_ip_info = ip_list[src_ip_index]
        ping(src_ip_info[3], src_ip_info[0], host_ip, strict_check,
             flood_minutes)
        error.context("File transfer test between guest and host",
                      logging.info)
        file_transfer(src_ip_info[3], src_ip_info[2], host_ip)
        for dst_ip in ip_list[src_ip_index:]:
            txt = "Ping test between %s and %s" % (src_ip_info[2], dst_ip[2])
            error.context(txt, logging.info)
            ping(src_ip_info[3], src_ip_info[0], dst_ip[2], strict_check,
                 flood_minutes)
            txt = "File transfer test between %s " % src_ip_info[2]
            txt += "and %s" % dst_ip[2]
            error.context(txt, logging.info)
            file_transfer(src_ip_info[3], src_ip_info[2], dst_ip[2])
