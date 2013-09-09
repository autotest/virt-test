import logging
import os
import commands
import threading
import re
import glob
import time
import shutil
from autotest.client import utils
from autotest.client.shared import error
from virttest import utils_test, utils_misc, remote, data_dir


def format_result(result, base="12", fbase="2"):
    """
    Format the result to a fixed length string.

    @param result: result need to convert
    @param base: the length of converted string
    @param fbase: the decimal digit for float
    """
    if isinstance(result, str):
        value = "%" + base + "s"
    elif isinstance(result, int):
        value = "%" + base + "d"
    elif isinstance(result, float):
        value = "%" + base + "." + fbase + "f"
    return value % result


def netperf_record(results, filter_list, header=False, base="12", fbase="2"):
    """
    Record the results in a certain format.

    @param results: a dict include the results for the variables
    @param filter_list: variable list which is wanted to be shown in the
                        record file, also fix the order of variables
    @param header: if record the variables as a column name before the results
    @param base: the length of a variable
    @param fbase: the decimal digit for float
    """
    key_list = []
    for key in filter_list:
        if results.has_key(key):
            key_list.append(key)

    record = ""
    if header:
        for key in key_list:
            record += "%s|" % format_result(key, base=base, fbase=fbase)
        record = record.rstrip("|")
        record += "\n"
    for key in key_list:
        record += "%s|" % format_result(results[key], base=base, fbase=fbase)
    record = record.rstrip("|")
    return record, key_list


def start_netserver_win(session, start_cmd, pattern):
    """
    Start netserver in Windows guest through a cygwin session.

    @param session: remote session for cygwin
    @param start_cmd: command to start netserver
    @param pattern: pattern to judge the status of netserver
    """
    output = session.cmd_output(start_cmd)
    try:
        re.findall(pattern, output)[0]
    except IndexError:
        logging.debug("Can not start netserver: %s" % output)
    return bool(re.findall(pattern, output))


@error.context_aware
def run_netperf(test, params, env):
    """
    Network stress test with netperf.

    1) Boot up VM(s), setup SSH authorization between host
       and guest(s)/external host
    2) Prepare the test environment in server/client/host
    3) Execute netperf tests, collect and analyze the results

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    def env_setup(session, ip, user, port, password):
        error.context("Setup env for %s" % ip)
        ssh_cmd(session, "service iptables stop; true")
        ssh_cmd(session, "echo 1 > /proc/sys/net/ipv4/conf/all/arp_ignore")

        netperf_dir = os.path.join(data_dir.get_root_dir(), "shared/deps")
        for i in params.get("netperf_files").split():
            remote.scp_to_remote(ip, shell_port, username, password,
                                 "%s/%s" % (netperf_dir, i), "/tmp/")
        ssh_cmd(session, params.get("setup_cmd"))

        agent_path = os.path.join(test.virtdir, "scripts/netperf_agent.py")
        remote.scp_to_remote(ip, shell_port, username, password,
                             agent_path, "/tmp/")

    def _pin_vm_threads(vm, node):
        if node:
            if not isinstance(node, utils_misc.NumaNode):
                node = utils_misc.NumaNode(int(node))
            utils_test.pin_vm_threads(vm, node)

        return node

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))

    session = vm.wait_for_login(timeout=login_timeout)
    config_cmds = params.get("config_cmds")
    if config_cmds:
        for config_cmd in config_cmds.split(","):
            cmd = params.get(config_cmd.strip())
            if cmd:
                s, o = session.cmd_status_output(cmd)
                if s:
                    msg = "Config command %s failed. Output: %s" % (cmd, o)
                    raise error.TestError(msg)
        if params.get("reboot_after_config", "yes") == "yes":
            session = vm.reboot(session=session, timeout=login_timeout)

    if params.get("rh_perf_envsetup_script"):
        utils_test.service_setup(vm, session, test.virtdir)
    session.close()

    server_ip = vm.get_address()
    server_ctl = vm.wait_for_login(timeout=login_timeout)
    server_ctl_ip = server_ip
    if (params.get("os_type") == "windows"
            and params.get("use_cygwin") == "yes"):
        cygwin_prompt = params.get("cygwin_prompt", "\$\s+$")
        cygwin_start = params.get("cygwin_start")
        server_cyg = vm.wait_for_login(timeout=login_timeout)
        server_cyg.set_prompt(cygwin_prompt)
        server_cyg.cmd_output(cygwin_start)
    else:
        server_cyg = None

    if len(params.get("nics", "").split()) > 1:
        server_ctl = vm.wait_for_login(nic_index=1, timeout=login_timeout)
        server_ctl_ip = vm.get_address(1)

    logging.debug(commands.getoutput("numactl --hardware"))
    logging.debug(commands.getoutput("numactl --show"))
    # pin guest vcpus/memory/vhost threads to last numa node of host by default
    numa_node = _pin_vm_threads(vm, params.get("numa_node"))

    host = params.get("host", "localhost")
    host_ip = host
    if host != "localhost":
        params_host = params.object_params("host")
        host = remote.wait_for_login(params_host.get("shell_client"),
                                     host_ip,
                                     params_host.get("shell_port"),
                                     params_host.get("username"),
                                     params_host.get("password"),
                                     params_host.get("shell_prompt"))

    client = params.get("client", "localhost")
    client_ip = client
    clients = []
    # client session 1 for control, session 2 for data communication
    for i in range(2):
        if client in params.get("vms"):
            vm_client = utils_test.get_living_vm(env, client)
            tmp = vm_client.wait_for_login(timeout=login_timeout)
            client_ip = vm_client.get_address()
        elif client != "localhost":
            tmp = remote.wait_for_login(params.get("shell_client_client"),
                                        client_ip,
                                        params.get("shell_port_client"),
                                        params.get("username_client"),
                                        params.get("password_client"),
                                        params.get("shell_prompt_client"))
        else:
            tmp = "localhost"
        clients.append(tmp)
    client = clients[0]

    vms_list = params["vms"].split()
    if len(vms_list) > 1:
        vm2 = env.get_vm(vms_list[-1])
        vm2.verify_alive()
        session2 = vm2.wait_for_login(timeout=login_timeout)
        if params.get("rh_perf_envsetup_script"):
            utils_test.service_setup(vm2, session2, test.virtdir)
        client = vm2.wait_for_login(timeout=login_timeout)
        client_ip = vm2.get_address()
        session2.close()
        _pin_vm_threads(vm2, numa_node)

    error.context("Prepare env of server/client/host", logging.info)
    prepare_list = set([server_ctl, client, host])
    tag_dict = {server_ctl: "server", client: "client", host: "host"}
    ip_dict = {server_ctl: server_ctl_ip, client: client_ip, host: host_ip}
    for i in prepare_list:
        params_tmp = params.object_params(tag_dict[i])
        if params_tmp.get("os_type") == "linux":
            shell_port = int(params_tmp["shell_port"])
            password = params_tmp["password"]
            username = params_tmp["username"]
            env_setup(i, ip_dict[i], username, shell_port, password)

    if "tcpdump" in env and env["tcpdump"].is_alive():
        # Stop the background tcpdump process
        try:
            logging.debug("Stopping the background tcpdump")
            env["tcpdump"].close()
        except Exception:
            pass

    error.context("Start netperf testing", logging.info)
    start_test(server_ip, server_ctl, host, clients, test.resultsdir,
               l=int(params.get('l')),
               sessions_rr=params.get('sessions_rr'),
               sessions=params.get('sessions'),
               sizes_rr=params.get('sizes_rr'),
               sizes=params.get('sizes'),
               protocols=params.get('protocols'),
               ver_cmd=params.get('ver_cmd', "rpm -q qemu-kvm"),
               netserver_port=params.get('netserver_port', "12865"),
               params=params, server_cyg=server_cyg, test=test)


@error.context_aware
def start_test(server, server_ctl, host, clients, resultsdir, l=60,
               sessions_rr="50 100 250 500", sessions="1 2 4",
               sizes_rr="64 256 512 1024 2048",
               sizes="64 256 512 1024 2048 4096",
               protocols="TCP_STREAM TCP_MAERTS TCP_RR TCP_CRR", ver_cmd=None,
               netserver_port=None, params={}, server_cyg=None, test=None):
    """
    Start to test with different kind of configurations

    @param server: netperf server ip for data connection
    @param server_ctl: ip to control netperf server
    @param host: localhost ip
    @param clients: netperf clients' ip
    @param resultsdir: directory to restore the results
    @param l: test duration
    @param sessions_rr: sessions number list for RR test
    @param sessions: sessions number list
    @param sizes_rr: request/response sizes (TCP_RR, UDP_RR)
    @param sizes: send size (TCP_STREAM, UDP_STREAM)
    @param protocols: test type
    @param ver_cmd: command to check kvm version
    @param netserver_port: netserver listen port
    @param params: Dictionary with the test parameters.
    @param server_cyg: shell session for cygwin in windows guest
    """

    guest_ver_cmd = params.get("guest_ver_cmd", "uname -r")
    fd = open("%s/netperf-result.%s.RHS" % (resultsdir, time.time()), "w")

    test.write_test_keyval({'kvm-userspace-ver':
                            commands.getoutput(ver_cmd).strip()})
    test.write_test_keyval({'guest-kernel-ver': ssh_cmd(server_ctl,
                                                        guest_ver_cmd).strip()})
    test.write_test_keyval({'session-length': l})

    fd.write('### kvm-userspace-ver : %s\n' %
             commands.getoutput(ver_cmd).strip())
    fd.write('### guest-kernel-ver : %s\n' % ssh_cmd(server_ctl,
                                                     guest_ver_cmd).strip())
    fd.write('### kvm_version : %s\n' % os.uname()[2])
    fd.write('### session-length : %s\n' % l)

    record_list = ['size', 'sessions', 'throughput', 'trans.rate', 'CPU',
                   'thr_per_CPU', 'rx_pkts', 'tx_pkts', 'rx_byts', 'tx_byts',
                   're_pkts', 'rx_intr', 'tx_intr', 'io_exit', 'irq_inj',
                   'tpkt_per_exit', 'rpkt_per_irq']
    base = params.get("format_base", "12")
    fbase = params.get("format_fbase", "2")

    output = ssh_cmd(host, "mpstat 1 1 |grep CPU")
    mpstat_head = re.findall("CPU\s+.*", output)[0].split()
    mpstat_key = params.get("mpstat_key", "%idle")
    if mpstat_key in mpstat_head:
        mpstat_index = mpstat_head.index(mpstat_key) + 1
    else:
        mpstat_index = 0

    for protocol in protocols.split():
        error.context("Testing %s protocol" % protocol, logging.info)
        if protocol in ("TCP_RR", "TCP_CRR"):
            sessions_test = sessions_rr.split()
            sizes_test = sizes_rr.split()
            protocol_log = protocol
        else:
            sessions_test = sessions.split()
            sizes_test = sizes.split()
            if protocol == "TCP_STREAM":
                protocol_log = protocol + " (RX)"
            elif protocol == "TCP_MAERTS":
                protocol_log = protocol + " (TX)"
        fd.write("Category:" + protocol_log + "\n")

        record_header = True
        for i in sizes_test:
            for j in sessions_test:
                if protocol in ("TCP_RR", "TCP_CRR"):
                    ret = launch_client(
                        j, server, server_ctl, host, clients, l,
                        "-t %s -v 1 -- -r %s,%s" % (protocol, i, i),
                        netserver_port, params, server_cyg)
                else:
                    ret = launch_client(
                        j, server, server_ctl, host, clients, l,
                        "-C -c -t %s -- -m %s" % (protocol, i),
                        netserver_port, params, server_cyg)

                thu = float(ret['thu'])
                cpu = 100 - float(ret['mpstat'].split()[mpstat_index])
                normal = thu / cpu
                if ret.get('rx_pkts') and ret.get('irq_inj'):
                    ret['tpkt_per_exit'] = float(
                        ret['rx_pkts']) / float(ret['irq_inj'])
                if ret.get('tx_pkts') and ret.get('io_exit'):
                    ret['rpkt_per_irq'] = float(
                        ret['tx_pkts']) / float(ret['io_exit'])
                ret['size'] = int(i)
                ret['sessions'] = int(j)
                if protocol in ("TCP_RR", "TCP_CRR"):
                    ret['trans.rate'] = thu
                else:
                    ret['throughput'] = thu
                ret['CPU'] = cpu
                ret['thr_per_CPU'] = normal
                row, key_list = netperf_record(ret, record_list,
                                               header=record_header,
                                               base=base,
                                               fbase=fbase)
                if record_header:
                    record_header = False
                    category = row.split('\n')[0]

                test.write_test_keyval({'category': category})
                prefix = '%s--%s--%s' % (protocol, i, j)
                for key in key_list:
                    test.write_perf_keyval(
                        {'%s--%s' % (prefix, key): ret[key]})

                logging.info(row)
                fd.write(row + "\n")

                fd.flush()
                logging.debug("Remove temporary files")
                commands.getoutput("rm -f /tmp/netperf.%s.nf" % ret['pid'])
    fd.close()


def ssh_cmd(session, cmd, timeout=120):
    """
    Execute remote command and return the output

    @param session: a remote shell session or tag for localhost
    @param cmd: executed command
    @param timeout: timeout for the command
    """
    if session == "localhost":
        return utils.system_output(cmd, timeout=timeout)
    else:
        return session.cmd_output(cmd, timeout=timeout)


@error.context_aware
def launch_client(sessions, server, server_ctl, host, clients, l, nf_args,
                  port, params, server_cyg):
    """ Launch netperf clients """

    client_path = "/tmp/netperf-2.6.0/src/netperf"
    server_path = "/tmp/netperf-2.6.0/src/netserver"
    # Start netserver
    error.context("Start Netserver on guest", logging.info)
    if params.get("os_type") == "windows":
        timeout = float(params.get("timeout", "240"))
        cdrom_drv = utils_test.get_windows_disk_drive(server_ctl, "netserver")
        netserv_start_cmd = params.get("netserv_start_cmd") % cdrom_drv

        logging.info("Netserver start cmd is '%s'" % netserv_start_cmd)
        if params.get("use_cygwin") == "yes":
            netperf_src = params.get("netperf_src")
            cygwin_root = params.get("cygwin_root")
            netserv_pattern = params.get("netserv_pattern")
            netperf_install_cmd = params.get("netperf_install_cmd")
            if "netserver" not in server_ctl.cmd_output("tasklist"):
                if not start_netserver_win(server_cyg, netserv_start_cmd,
                                           netserv_pattern):
                    logging.info("Install netserver in Windows guest")
                    output = server_ctl.cmd("dir %s" % cygwin_root)
                    if "netperf" not in output:
                        cmd = "xcopy %s %s /S /I" % (netperf_src, cygwin_root)
                        server_ctl.cmd(cmd)
                    server_cyg.cmd_output(netperf_install_cmd,
                                          timeout=timeout)
                    if not start_netserver_win(server_cyg, netserv_start_cmd,
                                               netserv_pattern):
                        msg = "Can not start netserver in Windows guest"
                        raise error.TestError(msg)
        else:
            if "NETSERVER.EXE" not in server_ctl.cmd_output("tasklist"):
                server_ctl.cmd_output(netserv_start_cmd)
                o_tasklist = server_ctl.cmd_output("tasklist")
                if "NETSERVER.EXE" not in o_tasklist.upper():
                    msg = "Can not start netserver in Windows guest"
                    raise error.TestError(msg)

        get_status_flag = False
    else:
        logging.info("Netserver start cmd is '%s'" % server_path)
        ssh_cmd(server_ctl, "pidof netserver || %s" % server_path)
        get_status_flag = True
        ncpu = ssh_cmd(server_ctl, "cat /proc/cpuinfo |grep processor |wc -l")
        ncpu = re.findall("\d+", ncpu)[0]

    logging.info("Netserver start successfully")

    def count_interrupt(name):
        """
        @param name: the name of interrupt, such as "virtio0-input"
        """
        intr = 0
        stat = ssh_cmd(server_ctl, "cat /proc/interrupts |grep %s" % name)
        stat = stat.strip().split("\n")[-1]
        for cpu in range(int(ncpu)):
            intr += int(stat.split()[cpu + 1])
        return intr

    def get_state():
        for i in ssh_cmd(server_ctl, "ifconfig").split("\n\n"):
            if server in i:
                ifname = re.findall("(\w+\d+)[:\s]", i)[0]

        path = "find /sys/devices|grep net/%s/statistics" % ifname
        cmd = "%s/rx_packets|xargs cat;%s/tx_packets|xargs cat;" \
            "%s/rx_bytes|xargs cat;%s/tx_bytes|xargs cat" % (path,
                                                             path, path, path)
        output = ssh_cmd(server_ctl, cmd).split()[-4:]

        nrx = int(output[0])
        ntx = int(output[1])
        nrxb = int(output[2])
        ntxb = int(output[3])

        nre = int(ssh_cmd(server_ctl, "grep Tcp /proc/net/snmp|tail -1"
                          ).split()[12])
        state_list = ['rx_pkts', nrx, 'tx_pkts', ntx, 'rx_byts', nrxb,
                      'tx_byts', ntxb, 're_pkts', nre]
        try:
            nrx_intr = count_interrupt("virtio.-input")
            ntx_intr = count_interrupt("virtio.-output")
            state_list.append('rx_intr')
            state_list.append(nrx_intr)
            state_list.append('tx_intr')
            state_list.append(ntx_intr)
        except IndexError:
            ninit = count_interrupt("virtio.")
            state_list.append('intr')
            state_list.append(ninit)

        io_exit = int(ssh_cmd(host, "cat /sys/kernel/debug/kvm/io_exits"))
        irq_inj = int(
            ssh_cmd(host, "cat /sys/kernel/debug/kvm/irq_injections"))
        state_list.append('io_exit')
        state_list.append(io_exit)
        state_list.append('irq_inj')
        state_list.append(irq_inj)
        return state_list

    def netperf_thread(i, numa_enable, client_s):
        cmd = ""
        fname = "/tmp/netperf.%s.nf" % pid
        if numa_enable:
            output = ssh_cmd(client_s, "numactl --hardware")
            n = int(re.findall("available: (\d+) nodes", output)[0]) - 1
            cmd += "numactl --cpunodebind=%s --membind=%s " % (n, n)
        cmd += "/tmp/netperf_agent.py %d %s -D 1 -H %s -l %s %s" % (i,
               client_path, server, int(l) * 1.5, nf_args)
        cmd += " >> %s" % fname
        logging.info("Start netperf thread by cmd '%s'" % cmd)
        ssh_cmd(client_s, cmd)

        logging.info("Netperf thread completed successfully")

    def parse_demo_result(fname, sessions):
        """
        Process the demo result, remove the noise from head,
        and compute the final throughout.

        @param fname: result file name
        @param sessions: sessions' number
        """
        fd = open(fname)
        lines = fd.readlines()
        fd.close()

        for i in range(1, len(lines) + 1):
            if "AF_INET" in lines[-i]:
                break
        nresult = i - 1
        if nresult < int(sessions):
            raise error.TestError("We couldn't expect this parallism,"
                                  "expect %s get %s" % (sessions, nresult))

        niteration = nresult / sessions
        result = 0.0
        for this in lines[-sessions * niteration:]:
            if "Interim" in this:
                result += float(re.findall("Interim result: *(\S+)", this)[0])
        result = result / niteration
        logging.debug("niteration: %s" % niteration)
        return result

    error.context("Start netperf client threads", logging.info)
    pid = str(os.getpid())
    fname = "/tmp/netperf.%s.nf" % pid
    ssh_cmd(clients[-1], "rm -f %s" % fname)
    numa_enable = params.get("netperf_with_numa", "yes") == "yes"
    client_thread = threading.Thread(target=netperf_thread,
                                     kwargs={"i": int(sessions),
                                             "numa_enable": numa_enable,
                                             "client_s": clients[0]})
    client_thread.start()

    ret = {}
    ret['pid'] = pid

    while True:
        try:
            content = ssh_cmd(clients[-1], "cat %s" % fname)
        except:
            content = ""
        if int(sessions) == len(re.findall("MIGRATE", content)):
            logging.debug("All netperf clients start to work.")
            break

    # real & effective test starts
    if get_status_flag:
        start_state = get_state()
    ret['mpstat'] = ssh_cmd(host, "mpstat 1 %d |tail -n 1" % (l - 1))
    finished_result = ssh_cmd(clients[-1], "cat %s" % fname)

    # real & effective test ends
    if get_status_flag:
        end_state = get_state()
        if len(start_state) != len(end_state):
            msg = "Initial state not match end state:\n"
            msg += "  start state: %s\n" % start_state
            msg += "  end state: %s\n" % end_state
            logging.warn(msg)
        else:
            for i in range(len(end_state) / 2):
                ret[end_state[i * 2]] = (end_state[i * 2 + 1]
                                         - start_state[i * 2 + 1])

    client_thread.join()

    error.context("Testing Results Treatment and Report", logging.info)
    f = open(fname, "w")
    f.write(finished_result)
    f.close()
    ret['thu'] = parse_demo_result(fname, int(sessions))
    return ret
