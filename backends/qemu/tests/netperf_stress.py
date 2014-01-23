import re
import logging
import time
from autotest.client.shared import error
from virttest import utils_net, utils_netperf, utils_misc


@error.context_aware
def run(test, params, env):
    """
    Run netperf on server and client side, we need run this case on two
    machines. if dsthost is not set will start netperf server on local
    host.
    Netperf stress test will keep running, until stress timeout or
    env["netperf_run"] is False

    1) Start one vm guest os as server.
    2) Start a reference machine (dsthost) as client.
    3) Run netperf stress test.
    4) Finish test until timeout or env["netperf_run"] is False.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    login_timeout = float(params.get("login_timeout", 360))
    dsthost = params.get("dsthost", "localhost")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    session.cmd("service iptables stop; iptables -F", ignore_all_errors=True)

    if dsthost in params.get("vms", "vm1 vm2"):
        server_vm = env.get_vm(dsthost)
        server_vm.verify_alive()
        server_vm.wait_for_login(timeout=login_timeout)
        dsthost_ip = server_vm.get_address()
    elif re.match(r"((\d){1,3}\.){3}(\d){1,3}", dsthost):
        dsthost_ip = dsthost
    else:
        server_interface = params.get("netdst", "switch")
        host_nic = utils_net.Interface(server_interface)
        dsthost_ip = host_nic.get_ip()

    download_link = params.get("netperf_download_link")
    md5sum = params.get("pkg_md5sum")
    server_download_link = params.get("server_download_link", download_link)
    server_md5sum = params.get("server_md5sum", md5sum)
    server_path = params.get("server_path", "/var/tmp")
    client_path = params.get("client_path", "/var/tmp")

    guest_usrname = params.get("username", "")
    guest_passwd = params.get("password", "")
    host_passwd = params.get("hostpasswd")
    client = params.get("shell_client")
    port = params.get("shell_port")

    #main vm run as server when vm_as_server is 'yes'.
    if params.get("vm_as_server", "yes") == "yes":
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
    try:
        netperf_server.start()
        # Run netperf with message size defined in range.
        stress_timeout = float(params.get("netperf_test_timeout", 1200))
        netperf_test_duration = float(params.get("netperf_test_duration", 60))
        netperf_para_sess = params.get("netperf_para_sessions", "1")
        test_protocol = params.get("test_protocol", "TCP_STREAM")
        netperf_cmd_prefix = params.get("netperf_cmd_prefix", "")
        test_option = "-t %s -l %s" % (test_protocol, netperf_test_duration)
        start_time = time.time()
        stop_time =  start_time + stress_timeout

        netperf_client.bg_start(netserver_ip, test_option,
                                netperf_para_sess, netperf_cmd_prefix)
        if utils_misc.wait_for(netperf_client.is_test_running, 10, 0, 1,
                               "Wait netperf test start"):
            logging.debug("Netperf test start successfully.")
            #here when set a run flag, when other case call this case as a
            #subprocess backgroundly, can set this run flag to False to stop
            #the stress test.
            env["netperf_run"] = True
        else:
            raise error.TestNAError("Can not start netperf test")

        while (env["netperf_run"] and time.time() < stop_time):
            run_left_time = stop_time - time.time()
            if netperf_client.is_test_running():
                if not utils_misc.wait_for(lambda: not
                                           netperf_client.is_test_running(),
                                           run_left_time, 0, 5,
                                           "Wait netperf test finish"):
                    logging.debug("Stress test timeout, finish it")
                    break
            netperf_client.bg_start(vm.get_address(), test_option,
                                    netperf_para_sess)

    finally:
        netperf_server.stop()
        netperf_server.env_cleanup(True)
        netperf_client.env_cleanup(True)
        env["netperf_run"] = False
        if session:
            session.close()
