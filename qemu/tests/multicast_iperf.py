import logging
import os
import re
from autotest.client import utils
from autotest.client.shared import error


@error.context_aware
def run_multicast_iperf(test, params, env):
    """
    Multicast test using iperf.

    1) Boot up VM(s)
    2) Prepare the test environment in server/client/host,install iperf
    3) Execute iperf tests, analyze the results

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    def server_start(cmd, catch_data):
        """
        Start the iperf server in host, and check whether the guest have connected
        this server through multicast address of the server
        """
        try:
            utils.run(cmd)
        except error.CmdError, e:
            if not re.findall(catch_data, str(e)):
                raise error.TestFail("Client not connected '%s'" % str(e))
            logging.info("Client multicast test pass "
                         % re.findall(catch_data, str(e)))

    os_type = params.get("os_type")
    win_iperf_url = params.get("win_iperf_url")
    linux_iperf_url = params.get("linux_iperf_url")
    iperf_version = params.get("iperf_version", "2.0.5")
    transfer_timeout = int(params.get("transfer_timeout", 360))
    login_timeout = int(params.get("login_timeout", 360))

    dir_name = test.tmpdir
    tmp_dir = params.get("tmp_dir", "/tmp/")
    host_path = os.path.join(dir_name, "iperf")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)
    client_ip = vm.get_address(0)

    try:
        error.context("Test Env setup")
        iperf_url = linux_iperf_url
        utils.get_file(iperf_url, host_path)

        error.context("install iperf in host", logging.info)
        default_install_cmd = "tar zxvf %s; cd iperf-%s;"
        default_install_cmd += " ./configure; make; make install"
        install_cmd = params.get("linux_install_cmd", default_install_cmd)
        utils.system(install_cmd % (host_path, iperf_version))

        error.context("install iperf in guest", logging.info)
        if os_type == "linux":
            guest_path = (tmp_dir + "iperf.tgz")
            clean_cmd = "rm -rf %s iperf-%s" % (guest_path, iperf_version)
        else:
            guest_path = (tmp_dir + "iperf.exe")
            iperf_url = win_iperf_url
            utils.get_file(iperf_url, host_path)
            clean_cmd = "del %s" % guest_path
        vm.copy_files_to(host_path, guest_path, timeout=transfer_timeout)

        if os_type == "linux":
            session.cmd(install_cmd % (guest_path, iperf_version))

        muliticast_addr = params.get("muliticast_addr", "225.0.0.3")
        multicast_port = params.get("multicast_port", "5001")

        step_msg = "Start iperf server, bind host to multicast address %s "
        error.context(step_msg % muliticast_addr, logging.info)
        server_start_cmd = ("iperf -s -u -B %s -p %s " %
                            (muliticast_addr, multicast_port))

        default_flag = "%s port %s connected with %s"
        connected_flag = params.get("connected_flag", default_flag)
        catch_data = connected_flag % (muliticast_addr, multicast_port,
                                       client_ip)
        t = utils.InterruptedThread(server_start, (server_start_cmd,
                                                   catch_data))
        t.start()
        if not utils.process_is_alive("iperf"):
            raise error.TestError("Start iperf server failed cmd: %s"
                                  % server_start_cmd)
        logging.info("Server start successfully")

        step_msg = "In client try to connect server and transfer file "
        step_msg += " through multicast address %s"
        error.context(step_msg % muliticast_addr, logging.info)
        if os_type == "linux":
            client_cmd = "iperf"
        else:
            client_cmd = guest_path
        start_cmd = params.get("start_client_cmd", "%s -c %s -u -p %s")
        start_client_cmd = start_cmd % (client_cmd, muliticast_addr,
                                        multicast_port)
        session.cmd(start_client_cmd)
        logging.info("Client start successfully")

        error.context("Test finish, check the result", logging.info)
        utils.system("killall -9 iperf")
        t.join()

    finally:
        if utils.process_is_alive("iperf"):
            utils.system("killall -9 iperf")
        utils.system("rm -rf %s" % host_path)
        session.cmd(clean_cmd)
        if session:
            session.close()
