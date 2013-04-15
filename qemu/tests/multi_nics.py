import logging, time, re, commands
from autotest.client.shared import error
from virttest import utils_test, utils_misc


def run_multi_nics(test, params, env):
    """
    KVM multi test:
    1) Log into guests
    2) Check the nics available
    3) ping among different nics
    4) Transfer files among different nics

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    def ping(src, dst, strick_check, flood_minutes):
        packet_size = [1, 4, 48, 512, 1440, 1500, 1505, 4054, 4055, 4096, 4192,
                   8878, 9000, 32767, 65507]
        nic = src[0]
        ip = dst[2]
        ses = src[3]
        for size in packet_size:
            logging.info("Ping with packet size %s" % size)
            status, output = utils_test.ping(ip, 10, interface = nic,
                                                packetsize = size,
                                                timeout = 30, session = ses)
            if strict_check:
                ratio = utils_test.get_loss_ratio(output)
                if ratio != 0:
                    raise error.TestFail(" Loss ratio is %s for packet size"
                                         " %s" % (ratio, size))
            else:
                if status != 0:
                    raise error.TestFail(" Ping returns non-zero value %s" %
                                         output)

        logging.info("Flood ping test")
        utils_test.ping(ip, None, interface = nic, flood = True,
                          output_func= None, timeout = flood_minutes * 60,
                          session = ses)
        logging.info("Final ping test")
        counts = params.get("ping_counts", 100)
        status, output = utils_test.ping(ip, counts, interface = nic,
                                            timeout = float(counts) * 1.5,
                                            session = ses)
        if strict_check:
            ratio = utils_test.get_loss_ratio(output)
            if ratio != 0:
                raise error.TestFail("Packet loss ratio is %s after flood"
                                     % ratio)
        else:
            if status != 0:
                raise error.TestFail(" Ping returns non-zero value %s" %
                                     output)

    def file_transfer(src_params, dst_params):
        src = src_params[2]
        dst = dst_params[2]
        session = src_params[3]
        username = params.get("username", "")
        password = params.get("password", "")
        src_path = "/tmp/1"
        dst_path = "/tmp/2"
        port = int(params.get("file_transfer_port"))

        cmd = "dd if=/dev/urandom of=/tmp/1 bs=100M count=1"
        logging.info("Create file by dd command, cmd: %s" % cmd)
        s, o = session.get_command_status_output(cmd)

        if s != 0:
            raise error.TestError("Fail to create file, output:%s" % o)

        transfer_timeout = int(params.get("transfer_timeout"))
        log_filename = "scp-from-%s-to-%s.log" % (src,dst)
        utils_misc.scp_between_remotes(src, dst, port, password, password,
                                       username, username, src_path, dst_path,
                                       log_filename=log_filename,
                                       timeout=transfer_timeout)

        src_path = dst_path
        dst_path = "/tmp/3"
        log_filename = "scp-from-%s-to-%s.log" % (dst, src)
        utils_misc.scp_between_remotes(dst, src, port, password, password,
                                       username, username, src_path, dst_path,
                                       log_filename=log_filename,
                                       timeout=transfer_timeout)

        # Check the file
        cmd = "diff /tmp/1 /tmp/3"
        s, o = session.get_command_status_output(cmd)
        if s != 0:
            raise error.TestError("Can not check files in guest")
        elif o:
            raise error.TestError("File changed after transfer: %s" % o)

    vm = utils_test.get_living_vm(env, params.get("main_vm"))
    vm_list = []
    session_list = []
    vms = re.split("\s+", params.get("vms"))
    timeout = float(params.get("login_timeout", 240))
    ip_filter = "(eth\d+).*?%s.*?%s" % (params.get("mac_filter"),
                                        params.get("ip_filter"))
    strict_check = params.get("strick_check")
    host_ip = params.get("srchost")
    flood_minutes = float(params.get("flood_minutes"))
    for i in vms:
        vm_name = "vm%s" % str(vms.index(i) + 1)
        vm_list.append(utils_test.get_living_vm(env, vm_name))
        session_list.append(vm_list[vms.index(i)].serial_login(timeout))

    time.sleep(10)
    # Build up guest ip pool it is a list make up by (interface, mac, ip,
    # session)
    ip_list = []
    for i in session_list:
        cmd = params.get("net_check_cmd")
        s, o = i.get_command_status_output(cmd)
        if s != 0:
            raise error.TestError("Can not get ip from guest")
        for ip in re.findall(ip_filter, o, re.S):
            ip_list.append(ip + (i,))
    # verify nic config
    ip_list_len = len(ip_list)
    if params.get("pci_assignable") == "no":
        count_nics = len(re.split("\s+", params.get("nics")))
    else:
        count_nics = params.get("devices_requested")

    if count_nics != ip_list_len:
        raise error.TestError("Not all nics get ip")

    # ping and file transfer test
    for src_ip_index in range(ip_list_len):
        # ping and transfer file from guest to host
        ping(ip_list[src_ip_index],("","",host_ip,""), strict_check,
             flood_minutes)
        file_transfer(ip_list[src_ip_index],("","",host_ip,""))
        # ping and transfer file among multi nics in guests
        for dst_ip in ip_list[src_ip_index:]:
            ping(ip_list[src_ip_index], dst_ip, strict_check, flood_minutes)
            file_transfer(ip_list[src_ip_index], dst_ip)
