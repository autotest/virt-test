import logging, os, commands, threading, re, glob
from autotest.server.hosts.ssh_host import SSHHost
from autotest.client import utils
from autotest.client.virt import utils_test, utils_misc, remote


def run_netperf(test, params, env):
    """
    Network stress test with netperf.

    1) Boot up VM(s), setup SSH authorization between host
       and guest(s)/external host
    2) Prepare the test environment in server/client/host
    3) Execute netperf tests, collect and analyze the results

    @param test: KVM test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    if params.get("rh_perf_envsetup_script"):
        utils_test.service_setup(vm, session, test.virtdir)
    server = vm.get_address()
    server_ctl = vm.get_address(1)
    session.close()

    logging.debug(commands.getoutput("numactl --hardware"))
    logging.debug(commands.getoutput("numactl --show"))
    # pin guest vcpus/memory/vhost threads to last numa node of host by default
    if params.get('numa_node'):
        numa_node = int(params.get('numa_node'))
        node = utils_misc.NumaNode(numa_node)
        utils_test.pin_vm_threads(vm, node)

    if "vm2" in params["vms"]:
        vm2 = env.get_vm("vm2")
        vm2.verify_alive()
        session2 = vm2.wait_for_login(timeout=login_timeout)
        if params.get("rh_perf_envsetup_script"):
            utils_test.service_setup(vm2, session2, test.virtdir)
        client = vm2.get_address()
        session2.close()
        if params.get('numa_node'):
            utils_test.pin_vm_threads(vm2, node)

    if params.get("client"):
        client = params["client"]
    if params.get("host"):
        host = params["host"]
    else:
        cmd = "ifconfig %s|awk 'NR==2 {print $2}'|awk -F: '{print $2}'"
        host = commands.getoutput(cmd % params["netdst"])

    shell_port = int(params["shell_port"])
    password = params["password"]
    username = params["username"]

    def env_setup(ip):
        logging.debug("Setup env for %s" % ip)
        SSHHost(ip, user=username, port=shell_port, password=password)
        ssh_cmd(ip, "service iptables stop")
        ssh_cmd(ip, "echo 1 > /proc/sys/net/ipv4/conf/all/arp_ignore")

        netperf_dir = os.path.join(os.environ['AUTODIR'], "tests/netperf2")
        for i in params.get("netperf_files").split():
            remote.scp_to_remote(ip, shell_port, username, password,
                                      "%s/%s" % (netperf_dir, i), "/tmp/")
        ssh_cmd(ip, params.get("setup_cmd"))

    logging.info("Prepare env of server/client/host")

    env_setup(server_ctl)
    env_setup(client)
    env_setup(host)
    logging.info("Start netperf testing ...")
    start_test(server, server_ctl, host, client, test.resultsdir,
               l=int(params.get('l')),
               sessions_rr=params.get('sessions_rr'),
               sessions=params.get('sessions'),
               sizes_rr=params.get('sizes_rr'),
               sizes=params.get('sizes'),
               protocols=params.get('protocols'),
               ver_cmd=params.get('ver_cmd', "rpm -q qemu-kvm"),
               netserver_port=params.get('netserver_port', "12865"), test=test)


def start_test(server, server_ctl, host, client, resultsdir, l=60,
               sessions_rr="50 100 250 500", sessions="1 2 4",
               sizes_rr="64 256 512 1024 2048",
               sizes="64 256 512 1024 2048 4096",
               protocols="TCP_STREAM TCP_MAERTS TCP_RR", ver_cmd=None,
               netserver_port=None, test=None):
    """
    Start to test with different kind of configurations

    @param server: netperf server ip for data connection
    @param server_ctl: ip to control netperf server
    @param host: localhost ip
    @param client: netperf client ip
    @param resultsdir: directory to restore the results
    @param l: test duration
    @param sessions_rr: sessions number list for RR test
    @param sessions: sessions number list
    @param sizes_rr: request/response sizes (TCP_RR, UDP_RR)
    @param sizes: send size (TCP_STREAM, UDP_STREAM)
    @param protocols: test type
    @param ver_cmd: command to check kvm version
    @param netserver_port: netserver listen port
    """

    def parse_file(file_prefix, raw=""):
        """ Parse result files and reture throughput total """
        thu = 0
        for file in glob.glob("%s.*.nf" % file_prefix):
            o = commands.getoutput("cat %s |tail -n 1" % file)
            try:
                thu += float(o.split()[raw])
            except:
                logging.debug(commands.getoutput("cat %s.*" % file_prefix))
                return -1
        return thu

    fd = open("%s/netperf-result.RHS" % resultsdir, "w")

    category = 'size|sessions|throughput|%CPU|thr/%CPU|@tx-pkts|@rx-pkts|@tx-byts|@rx-byts|@re-trans|@tx-intr|@rx-intr|@io_exit|@irq_inj|@tpkt/@exit|@rpkt/@irq'

    test.write_test_keyval({ 'category': category })
    test.write_test_keyval({ 'kvm-userspace-ver': commands.getoutput(ver_cmd) })
    test.write_test_keyval({ 'guest-kernel-ver': ssh_cmd(server_ctl, "uname -r") })
    test.write_test_keyval({ 'session-length': l })

    fd.write('### kvm-userspace-ver : %s\n' % commands.getoutput(ver_cmd) )
    fd.write('### guest-kernel-ver : %s\n' % ssh_cmd(server_ctl, "uname -r") )
    fd.write('### kvm_version : %s\n' % os.uname()[2] )
    fd.write('### session-length : %s\n' % l )

    for protocol in protocols.split():
        logging.info(protocol)
        fd.write("Category:" + protocol+ "\n")
        row = "%5s|%8s|%10s|%6s|%9s|%10s|%10s|%12s|%12s|%9s|%8s|%8s|%10s|%10s" \
              "|%11s|%10s" % ("size", "sessions", "throughput", "%CPU",
              "thr/%CPU", "#tx-pkts", "#rx-pkts", "#tx-byts", "#rx-byts",
              "#re-trans", "#tx-intr", "#rx-intr", "#io_exit", "#irq_inj",
              "#tpkt/#exit", "#rpkt/#irq")
        logging.info(row)
        fd.write(row + "\n")
        if (protocol == "TCP_RR"):
            sessions_test = sessions_rr.split()
            sizes_test = sizes_rr.split()
        else:
            sessions_test = sessions.split()
            sizes_test = sizes.split()
        for i in sizes_test:
            for j in sessions_test:
                if (protocol == "TCP_RR"):
                    ret = launch_client(1, server, server_ctl, host, client, l,
                    "-t %s -v 0 -P -0 -- -r %s,%s -b %s" % (protocol, i, i, j),
                    netserver_port)
                    thu = parse_file("/tmp/netperf.%s" % ret['pid'], 0)
                else:
                    ret = launch_client(j, server, server_ctl, host, client, l,
                                     "-C -c -t %s -- -m %s" % (protocol, i),
                                     netserver_port)
                    thu = parse_file("/tmp/netperf.%s" % ret['pid'], 4)
                cpu = 100 - float(ret['mpstat'].split()[10])
                normal = thu / cpu
                pkt_rx_irq = float(ret['rx_pkts']) / float(ret['irq_inj'])
                pkt_tx_exit = float(ret['tx_pkts']) / float(ret['io_exit'])
                row = "%5d|%8d|%10.2f|%6.2f|%9.2f|%10d|%10d|%12d|%12d|%9d" \
                      "|%8d|%8d|%10d|%10d|%11.2f|%10.2f" % (int(i), int(j),
                      thu, cpu, normal, ret['tx_pkts'], ret['rx_pkts'],
                      ret['tx_byts'], ret['rx_byts'], ret['re_pkts'],
                      ret['tx_intr'], ret['rx_intr'], ret['io_exit'],
                      ret['irq_inj'], pkt_tx_exit, pkt_rx_irq)
                logging.info(row)
                fd.write(row + "\n")

                prefix = '%s--%s--%s' % (protocol, i, j)
                test.write_perf_keyval({ '%s--throughput' % prefix :thu })
                test.write_perf_keyval({ '%s--CPU' % prefix :cpu })
                test.write_perf_keyval({ '%s--normal' % prefix :normal })
                test.write_perf_keyval({ '%s--tx_pkts' % prefix :ret['tx_pkts'] })
                test.write_perf_keyval({ '%s--rx_pkts' % prefix :ret['rx_pkts'] })
                test.write_perf_keyval({ '%s--tx_byts' % prefix :ret['tx_byts'] })
                test.write_perf_keyval({ '%s--rx_byts' % prefix :ret['rx_byts'] })
                test.write_perf_keyval({ '%s--re_trans' % prefix :ret['re_pkts'] })
                test.write_perf_keyval({ '%s--tx_intr' % prefix :ret['tx_intr'] })
                test.write_perf_keyval({ '%s--rx_intr' % prefix :ret['rx_intr'] })
                test.write_perf_keyval({ '%s--io_exit' % prefix :ret['io_exit'] })
                test.write_perf_keyval({ '%s--irq_inj' % prefix :ret['irq_inj'] })
                test.write_perf_keyval({ '%s--tpkt_exit' % prefix :pkt_tx_exit })
                test.write_perf_keyval({ '%s--rpkt_irq' % prefix :pkt_rx_irq })

                fd.flush()
                logging.debug("Remove temporary files")
                commands.getoutput("rm -f /tmp/netperf.%s.*.nf" % ret['pid'])
    fd.close()


def ssh_cmd(ip, cmd, user="root"):
    """
    Execute remote command and return the output

    @param ip: remote machine IP
    @param cmd: executed command
    @param user: username
    """
    return utils.system_output('ssh -o StrictHostKeyChecking=no -o '
    'UserKnownHostsFile=/dev/null %s@%s "%s"' % (user, ip, cmd))


def launch_client(sessions, server, server_ctl, host, client, l, nf_args, port):
    """ Launch netperf clients """

    client_path="/tmp/netperf-2.4.5/src/netperf"
    server_path="/tmp/netperf-2.4.5/src/netserver"
    ssh_cmd(server_ctl, "pidof netserver || %s -p %s" % (server_path, port))
    ncpu = ssh_cmd(server_ctl, "cat /proc/cpuinfo |grep processor |wc -l")

    def count_interrupt(name):
        """
        @param name: the name of interrupt, such as "virtio0-input"
        """
        intr = 0
        stat = ssh_cmd(server_ctl, "cat /proc/interrupts |grep %s" % name)
        for cpu in range(int(ncpu)):
            intr += int(stat.split()[cpu+1])
        return intr

    def get_state():
        for i in ssh_cmd(server_ctl, "ifconfig").split("\n\n"):
            if server in i:
                nrx = int(re.findall("RX packets:(\d+)", i)[0])
                ntx = int(re.findall("TX packets:(\d+)", i)[0])
                nrxb = int(re.findall("RX bytes:(\d+)", i)[0])
                ntxb = int(re.findall("TX bytes:(\d+)", i)[0])
        nre = int(ssh_cmd(server_ctl, "grep Tcp /proc/net/snmp|tail -1"
                 ).split()[12])
        nrx_intr = count_interrupt("virtio0-input")
        ntx_intr = count_interrupt("virtio0-output")
        io_exit = int(ssh_cmd(host, "cat /sys/kernel/debug/kvm/io_exits"))
        irq_inj = int(ssh_cmd(host, "cat /sys/kernel/debug/kvm/irq_injections"))
        return [nrx, ntx, nrxb, ntxb, nre, nrx_intr, ntx_intr, io_exit, irq_inj]

    def netperf_thread(i):
        output = ssh_cmd(client, "numactl --hardware")
        n = int(re.findall("available: (\d+) nodes", output)[0]) - 1
        cmd = "numactl --cpunodebind=%s --membind=%s %s -H %s -l %s %s" % \
                                    (n, n, client_path, server, l, nf_args)
        output = ssh_cmd(client, cmd)
        f = file("/tmp/netperf.%s.%s.nf" % (pid, i), "w")
        f.write(output)
        f.close()

    start_state = get_state()
    pid = str(os.getpid())
    threads = []
    for i in range(int(sessions)):
        t = threading.Thread(target=netperf_thread, kwargs={"i": i})
        threads.append(t)
        t.start()
    ret = {}
    ret['pid'] = pid
    ret['mpstat'] = ssh_cmd(host, "mpstat 1 %d |tail -n 1" % (l - 1))
    for t in threads:
        t.join()

    end_state = get_state()
    items = ['rx_pkts', 'tx_pkts', 'rx_byts', 'tx_byts', 're_pkts',
             'rx_intr', 'tx_intr', 'io_exit', 'irq_inj']
    for i in range(len(items)):
        ret[items[i]] = end_state[i] - start_state[i]
    return ret
