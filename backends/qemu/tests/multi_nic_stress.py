import logging
import os
import re
from autotest.client import utils
from autotest.client.shared import error
from virttest import utils_test, utils_net, utils_misc, remote, data_dir


def ssh_cmd(session, cmd, timeout=60):
    """
    Execute remote command and return the output

    :param session: a remote shell session or tag for localhost
    :param cmd: executed command
    :param timeout: timeout for the command
    """
    if session == "localhost":
        return utils.system_output(cmd, timeout=timeout)
    else:
        return session.cmd_output(cmd, timeout=timeout)


@error.context_aware
def run(test, params, env):
    """
    Network stress with multi nics test with netperf.

    1) Boot up VM(s), setup SSH authorization between host
       and guest(s)/external host
    2) Prepare the test environment in server/client
    3) Execute netperf  stress on multi nics
    4) After the stress do ping, check the nics works

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def env_setup(session, ip_addr, username, shell_port, password):
        """
        Test env setup
        """
        error.context("Setup env for %s" % ip_addr)
        ssh_cmd(session, "service iptables stop; true")
        netperf_links = params["netperf_links"].split()
        remote_dir = params.get("remote_dir", "/var/tmp")
        for netperf_link in netperf_links:
            if utils.is_url(netperf_link):
                download_dir = data_dir.get_download_dir()
                md5sum = params.get("pkg_md5sum")
                netperf_dir = utils.unmap_url_cache(download_dir,
                                                    netperf_link, md5sum)
            elif netperf_link:
                netperf_dir = os.path.join(data_dir.get_root_dir(),
                                           "shared/%s" % netperf_link)
            remote.scp_to_remote(ip_addr, shell_port, username, password,
                                 netperf_dir, remote_dir)
        ssh_cmd(session, params.get("setup_cmd"))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))

    server_ips = []
    server_ctl = vm.wait_for_login(timeout=login_timeout)
    server_ip = vm.get_address()
    server_ips.append(server_ip)
    server_ctl_ip = server_ip
    server_ctl_mac = vm.get_mac_address()

    # the first nic used for server control.
    params_server_nic = params.object_params(vm.name)
    nics_count = len(params_server_nic.get("nics", "").split())
    if nics_count > 1:
        server_ips = []
        for i in range(nics_count)[1:]:
            vm.wait_for_login(nic_index=i, timeout=login_timeout)
            server_ips.append(vm.get_address(index=i))

    clients = params.get("client", "localhost")
    clients_ips = []
    clients_sessions = []
    # client session 1 for control, session 2 for data communication
    for client in clients.split():
        for i in range(2):
            if client in params.get("vms"):
                vm = env.get_vm(client)
                vm.verify_alive()
                tmp = vm.wait_for_login()
                client_ip = vm.get_address()
            elif client == "localhost":
                client_ip = client
                tmp = "localhost"
            else:
                client_ip == client
                tmp = remote.wait_for_login(params.get("shell_client_client"),
                                            client_ip,
                                            params.get("shell_port_client"),
                                            params.get("username_client"),
                                            params.get("password_client"),
                                            params.get("shell_prompt_client"),
                                            params.get("shell_linesep_client"))
            clients_sessions.append(tmp)

        clients_ips.append(client_ip)

    client_ctl_session = clients_sessions[::2]
    clients = clients_sessions[1::2]

    if params.get("os_type") == "linux":
        nics_list = utils_net.get_linux_ifname(server_ctl)
        if len(nics_list) > 1:
            ctl_nic = utils_net.get_linux_ifname(server_ctl, server_ctl_mac)
            nics_list.remove(ctl_nic)
        for ip in clients_ips:
            index = clients_ips.index(ip) % len(nics_list)
            server_ctl.cmd("route add  -host %s %s" % (ip, nics_list[index]))

    error.context("Prepare env of server/client", logging.info)
    client_ctl_session.append(server_ctl)
    clients_ips.append(server_ctl_ip)

    for session in client_ctl_session:
        if session == server_ctl:
            para_tag = "server"
        else:
            para_tag = "client"
        params_tmp = params.object_params(para_tag)
        if params_tmp.get("os_type") == "linux":
            shell_port = int(params_tmp["shell_port"])
            password = params_tmp["password"]
            username = params_tmp["username"]
            env_setup(session, clients_ips[client_ctl_session.index(session)],
                      username, shell_port, password)

    error.context("Start netperf testing", logging.info)
    try:
        start_test(server_ips, server_ctl, clients,
                   l=int(params.get('l', 60)),
                   sessions_rr=params.get('sessions_rr'),
                   sessions=params.get('sessions'),
                   sizes_rr=params.get('sizes_rr'),
                   sizes=params.get('sizes'),
                   protocols=params.get('protocols'),
                   netserver_port=params.get('netserver_port', "12865"),
                   params=params)

    finally:
        for session in clients_sessions:
            if session:
                session.close()
        if server_ctl:
            server_ctl.close()


@error.context_aware
def start_test(servers, server_ctl, clients, l=60,
               sessions_rr="100", sessions="1 2 4",
               sizes_rr="1024", sizes="512",
               protocols="TCP_STREAM TCP_MAERTS TCP_RR TCP_CRR",
               netserver_port=None, params={}):
    """
    Start to test with different kind of configurations

    :param servers: netperf server ips for data connection
    :param server_ctl: ip to control netperf server
    :param clients: netperf clients' ip
    :param l: test duration
    :param sessions_rr: sessions number list for RR test
    :param sessions: sessions number list
    :param sizes_rr: request/response sizes (TCP_RR, UDP_RR)
    :param sizes: send size (TCP_STREAM, UDP_STREAM)
    :param protocols: test type
    :param netserver_port: netserver listen port
    :param params: Dictionary with the test parameters.
    """
    for protocol in protocols.split():
        error.context("Testing %s protocol" % protocol, logging.info)
        if protocol in ("TCP_RR", "TCP_CRR"):
            sessions_test = sessions_rr.split()
            sizes_test = sizes_rr.split()
        else:
            sessions_test = sessions.split()
            sizes_test = sizes.split()
        for i in sizes_test:
            for j in sessions_test:
                if protocol in ("TCP_RR", "TCP_CRR"):
                    launch_client(j, servers, server_ctl, clients, l,
                                  "-t %s -v 1 -- -r %s,%s" % (protocol, i, i),
                                  netserver_port, params)
                else:
                    launch_client(j, servers, server_ctl, clients, l,
                                  "-C -c -t %s -- -m %s" % (protocol, i),
                                  netserver_port, params)


@error.context_aware
def launch_client(sessions, servers, server_ctl, clients,
                  l, nf_args, port, params):
    """
    Launch netperf clients
    """
    # Start netserver
    error.context("Start Netserver on guest", logging.info)
    remote_dir = params.get("remote_dir", "/var/tmp")
    client_path = os.path.join(remote_dir, "netperf-2.6.0/src/netperf")
    server_path = os.path.join(remote_dir, "netperf-2.6.0/src/netserver")

    if params.get("os_type") == "windows":
        winutils_vol = utils_misc.get_winutils_vol(server_ctl)
        client_path = "%s:\\netperf" % winutils_vol
        netserv_start_cmd = params.get("netserv_start_cmd") % winutils_vol

        logging.info("Netserver start cmd is '%s'" % netserv_start_cmd)
        if "NETSERVER.EXE" not in server_ctl.cmd_output("tasklist"):
            server_ctl.cmd_output(netserv_start_cmd)
            o_tasklist = server_ctl.cmd_output("tasklist")
            if "NETSERVER.EXE" not in o_tasklist.upper():
                msg = "Can not start netserver in Windows guest"
                raise error.TestError(msg)

    else:
        logging.info("Netserver start cmd is '%s'" % server_path)
        ssh_cmd(server_ctl, "pidof netserver || %s" % server_path)
    logging.info("Netserver start successfully")

    # start netperf
    error.context("Start netperf client threads", logging.info)
    client_threads = []

    for client in clients:
        test_timeout = len(clients) * l
        server = servers[clients.index(client) % len(servers)]
        netperf_cmd = "%s -H %s -l %s %s" % (client_path, server,
                                             int(l), nf_args)
        client_threads.append([ssh_cmd, (client, netperf_cmd, test_timeout)])

    result_info = utils_misc.parallel(client_threads)

    counts = 5
    for server in servers:
        if not re.findall("TEST.*to %s" % server, str(result_info)):
            raise error.TestError("Nerperf stress on nic %s failed" % server)
        logging.info("Network stress on %s successfully" % server)

        status, output = utils_test.ping(server, counts,
                                         timeout=float(counts) * 1.5)
        if status != 0:
            raise error.TestFail("Ping returns non-zero value %s" % output)

        package_lost = utils_test.get_loss_ratio(output)
        if package_lost != 0:
            raise error.TestFail("%s packeage lost when ping server ip %s " %
                                 (package_lost, server))
