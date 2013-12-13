import logging
import os
import re
from autotest.client import utils
from autotest.client.shared import error
from virttest import utils_net, utils_netperf, utils_misc, data_dir


@error.context_aware
def run_netperf_udp(test, params, env):
    """
    Run netperf on server and client side, we need run this case on two
    machines. If dsthost is not set will start netperf server on local
    host and log a error message.:
    1) Start one vm guest os as client or server
       (windows guest must using as server).
    2) Start a reference machine (dsthost) as server/client.
    3) Setup netperf on guest and reference machine (dsthost).
    4) Start netperf server on the server host.
    5) Run netperf client command in guest several time with different
       message size.
    6) Compare UDP performance to make sure it is acceptable.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def dlink_preprcess(download_link):
        """
        Preprocess the download link
        """
        if not download_link:
            raise error.TestNAError("Can not get the netperf download_link")
        if not utils.is_url(download_link):
            download_link = utils_misc.get_path(data_dir.get_deps_dir(),
                                                download_link)
        return download_link


    login_timeout = float(params.get("login_timeout", 360))
    dsthost = params.get("dsthost", "localhost")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    session.cmd("iptables -F", ignore_all_errors=True)

    if dsthost in params.get("vms", "vm1 vm2"):
        server_vm = env.get_vm(dsthost)
        server_vm.verify_alive()
        s_session = server_vm.wait_for_login(timeout=login_timeout)
        s_session.cmd("iptables -F", ignore_all_errors=True)
        dsthost_ip = server_vm.get_address()
        s_session.close()
    elif re.match(r"((\d){1,3}\.){3}(\d){1,3}", dsthost):
        dsthost_ip = dsthost
    else:
        server_interface = params.get("netdst", "switch")
        host_nic = utils_net.Interface(server_interface)
        dsthost_ip = host_nic.get_ip()

    error.context("Test env prepare", logging.info)
    download_link = dlink_preprcess(params.get("netperf_download_link"))
    md5sum = params.get("pkg_md5sum")
    server_download_link = params.get("server_download_link", download_link)
    server_download_link = dlink_preprcess(server_download_link)
    server_md5sum = params.get("server_md5sum", md5sum)
    server_path = params.get("server_path", "/var/tmp/server.tar.bz2")
    client_path = params.get("client_path", "/var/tmp/client.tar.bz2")
    guest_usrname = params.get("username", "")
    guest_passwd = params.get("password", "")
    host_passwd = params.get("hostpasswd")
    client = params.get("shell_client")
    port = params.get("shell_port")

    #main vm run as server when vm_as_server is 'yes'.
    if params.get("vm_as_server") == "yes":
        netserver_ip = vm.get_address()
        netperf_client_ip = dsthost_ip
    else:
        netserver_ip = dsthost_ip
        netperf_client_ip = vm.get_address()

    netperf_client = utils_netperf.NetperfClient(netperf_client_ip,
                                                 client_path,
                                                 md5sum, download_link,
                                                 password=host_passwd)

    netperf_server = utils_netperf.NetperfServer(netserver_ip,
                                                  server_path,
                                                  server_md5sum,
                                                  server_download_link,
                                                  client, port,
                                                  username=guest_usrname,
                                                  password=guest_passwd)

    # Get range of message size.
    message_size = params.get("message_size_range", "580 590 1").split()
    start_size = int(message_size[0])
    end_size = int(message_size[1])
    step = int(message_size[2])
    m_size = start_size
    throughput = []

    try:
        error.context("Start netperf_server", logging.info)
        netperf_server.start()
        # Run netperf with message size defined in range.
        msg = "Detail result of netperf test with different packet size.\n"
        while(m_size <= end_size):
            test_protocol = params.get("test_protocol", "UDP_STREAM")
            test_option = "-t %s -- -m %s" % (test_protocol, m_size)
            txt = "Run netperf client with protocol: '%s', packet size: '%s'"
            error.context(txt % (test_protocol, m_size), logging.info)
            output = netperf_client.start(netserver_ip, test_option)
            if test_protocol == "UDP_STREAM":
                speed_index = 6
            elif test_protocol == "UDP_RR":
                speed_index = 7
            else:
                error.TestNAError("Protocol %s is not support" % test_protocol)

            line_tokens = output.splitlines()[speed_index].split()
            if not line_tokens:
                raise error.TestError("Output format is not expected")
            throughput.append(float(line_tokens[5]))
            msg += output
            m_size += step
    finally:
        netperf_server.stop()

    file(os.path.join(test.debugdir, "udp_results"), "w").write(msg)
    failratio = float(params.get("failratio", 0.3))
    error.context("Compare UDP performance.", logging.info)
    for i in range(len(throughput) - 1):
        if abs(throughput[i] - throughput[i + 1]) > throughput[i] * failratio:
            txt = "The gap between adjacent throughput is greater than"
            txt += "%f." % failratio
            txt += "Please refer to log file for details:\n %s" % msg
            raise error.TestFail(txt)
    logging.info("The UDP performance as measured via netperf is ok.")
    logging.info("Throughput of netperf command: %s" % throughput)
    logging.debug("Output of netperf command:\n %s" % msg)
    error.context("Kill netperf server on server (dsthost).")

    try:
        if session:
            session.close()
    except Exception:
        pass
