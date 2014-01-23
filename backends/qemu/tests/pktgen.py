import logging
import re
import time
import os
from autotest.client import utils
from autotest.client.shared import error
from virttest import remote, data_dir, utils_net, aexpect


@error.context_aware
def run(test, params, env):
    """
    Run Pktgen test between host/guest

    1) Boot the main vm, or just grab it if it's already booted.
    2) Configure pktgen server(only linux)
    3) Run pktgen test, finish when timeout or env["pktgen_run"] != True

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    login_timeout = float(params.get("login_timeout", 360))
    error.context("Init the VM, and try to login", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    error.context("Pktgen server environment prepare", logging.info)
    #pktgen server only support linux, since pktgen is a linux kernel module
    pktgen_server = params.get("pktgen_server", "localhost")
    params_server = params.object_params("pktgen_server")
    s_shell_client = params_server.get("shell_client", "ssh")
    s_shell_port = params_server.get("shell_port", "22")
    s_username = params_server.get("username", "root")
    s_passwd =  params_server.get("password", "123456")
    s_shell_prompt = params_server.get("shell_prompt")

    server_session = ""
    #pktgen server is autotest virtual guest(only linux)
    if pktgen_server in params.get("vms", "vm1 vm2"):
        vm_pktgen = env.get_vm(pktgen_server)
        vm_pktgen.verify_alive()
        server_session = vm_pktgen.wait_for_login(timeout=login_timeout)
        runner = server_session.cmd_output_safe
        pktgen_ip = vm_pktgen.get_address()
        pktgen_mac = vm_pktgen.get_mac_address()
        server_interface = utils_net.get_linux_ifname(server_session,
                                                      pktgen_mac)
    #pktgen server is a external host assigned
    elif re.match(r"((\d){1,3}\.){3}(\d){1,3}", pktgen_server):
        pktgen_ip = pktgen_server
        server_session = remote.wait_for_login(s_shell_client, pktgen_ip,
                                               s_shell_port, s_username,
                                               s_passwd, s_shell_prompt)
        runner = server_session.cmd_output_safe
        server_interface = params.get("server_interface")
        if not server_interface:
            raise error.TestNAError("Must config server interface before test")
    else:
        #using host as a pktgen server
        server_interface = params.get("netdst", "switch")
        host_nic = utils_net.Interface(server_interface)
        pktgen_ip = host_nic.get_ip()
        pktgen_mac = host_nic.get_mac()
        runner = utils.system

    #copy pktgen_test scipt to the test server.
    local_path = os.path.join(data_dir.get_root_dir(),
                              "shared/scripts/pktgen.sh")
    remote_path = "/tmp/pktgen.sh"
    remote.scp_to_remote(pktgen_ip, s_shell_port, s_username, s_passwd,
                         local_path, remote_path)

    error.context("Run pktgen test")
    run_threads = params.get("pktgen_threads", 1)
    pktgen_stress_timeout = float(params.get("pktgen_test_timeout", 600))
    exec_cmd = "%s %s %s %s %s" % (remote_path, vm.get_address(),
                                   vm.get_mac_address(),
                                   server_interface, run_threads)
    try:
        env["pktgen_run"] = True
        try:
            #Set a run flag in env, when other case call this case as a sub
            #backgroud process, can set run flag to False to stop this case.
            start_time = time.time()
            stop_time = start_time + pktgen_stress_timeout
            while (env["pktgen_run"] and time.time < stop_time):
                runner(exec_cmd, timeout= pktgen_stress_timeout)

        #using ping to kill the pktgen stress
        except aexpect.ShellTimeoutError:
            session.cmd("ping pktgen_ip")
    finally:
        env["pktgen_run"] = False

    if server_session:
        server_session.close()
    if session:
        session.close()
