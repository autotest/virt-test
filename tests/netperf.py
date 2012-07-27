import logging, os, commands, threading, re, glob
from autotest_lib.client.common_lib import error
from autotest_lib.client.bin import utils
from autotest_lib.client.virt import virt_utils
from autotest_lib.client.virt import virt_test_utils
try:
    from autotest_lib.server.hosts.ssh_host import SSHHost
except ImportError:
    pubkey = "%s/.ssh/id_dsa.pub" % os.environ['HOME']
    if not os.path.exists(os.path.expandvars(pubkey)):
        commands.getoutput('yes ""|ssh-keygen -t dsa -q -N ""')
    def SSHHost(ip, user, port, password):
        session = virt_utils.wait_for_login("ssh", ip, port, user, password,
                                            "^\[.*\][\#\$]\s*$")
        k = open(pubkey, "r")
        session.cmd('echo "%s" >> ~/.ssh/authorized_keys' % k.read())
        k.close()
        session.close()


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


def netperf_record(results, filter_list, headon=False, base="12", fbase="2"):
    """
    Record the results in a certain format.

    @param results: a dict include the results for the variables
    @param filter_list: variable list which is wanted to be shown in the
                        record file, also fix the order of variables
    @param headon: if record the variables as a column name before the results
    @param base: the length of a variable
    @param fbase: the decimal digit for float
    """
    key_list = []
    for key in filter_list:
        if results.has_key(key):
            key_list.append(key)

    record = ""
    if headon:
        for key in key_list:
            record += "%s|" % format_result(key, base=base, fbase=fbase)
        record += "\n"
    for key in key_list:
        record += "%s|" % format_result(results[key], base=base, fbase=fbase)
    return record


@error.context_aware
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
    def env_setup(ip, user, port, password):
        error.context("Setup env for %s" % ip)
        SSHHost(ip, user=user, port=port, password=password)
        ssh_cmd(ip, "service iptables stop")
        ssh_cmd(ip, "echo 1 > /proc/sys/net/ipv4/conf/all/arp_ignore")

        netperf_dir = os.path.join(os.environ['AUTODIR'], "tests/netperf2")
        for i in params.get("netperf_files").split():
            virt_utils.scp_to_remote(ip, shell_port, username, password,
                                     "%s/%s" % (netperf_dir, i), "/tmp/")
        ssh_cmd(ip, params.get("setup_cmd"))


    def _pin_vm_threads(vm, node):
        if node:
            if not isinstance(node, virt_utils.NumaNode):
                node = virt_utils.NumaNode(int(node))
            virt_test_utils.pin_vm_threads(vm, node)

        return node


    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))

    session = vm.wait_for_login(timeout=login_timeout)
    if params.get("rh_perf_envsetup_script"):
        virt_test_utils.service_setup(vm, session, test.virtdir)
    session.close()

    server = vm.get_address()
    server_ctl = server
    if len(params.get("nics", "").split()) > 1:
        server_ctl = vm.get_address(1)

    logging.debug(commands.getoutput("numactl --hardware"))
    logging.debug(commands.getoutput("numactl --show"))
    # pin guest vcpus/memory/vhost threads to last numa node of host by default
    numa_node = _pin_vm_threads(vm, params.get("numa_node"))

    if params.get("host"):
        host = params["host"]
    else:
        cmd = "ifconfig %s|awk 'NR==2 {print $2}'|awk -F: '{print $2}'"
        host = commands.getoutput(cmd % params["bridge"])

    client = params.get("client", "localhost")
    vms_list = params["vms"].split()
    if len(vms_list) > 1:
        vm2 = env.get_vm(vms_list[-1])
        vm2.verify_alive()
        session2 = vm2.wait_for_login(timeout=login_timeout)
        if params.get("rh_perf_envsetup_script"):
            virt_test_utils.service_setup(vm2, session2, test.virtdir)
        client = vm2.get_address()
        session2.close()
        _pin_vm_threads(vm2, numa_node)

    shell_port = int(params["shell_port"])
    password = params["password"]
    username = params["username"]

    error.context("Prepare env of server/client/host", logging.info)
    env_setup(server_ctl, username, shell_port, password)
    env_setup(client, username, shell_port, password)
    env_setup(host, username, shell_port, password)

    error.context("Start netperf testing", logging.info)
    start_test(server, server_ctl, host, client, test.resultsdir,
               l=int(params.get('l')),
               sessions_rr=params.get('sessions_rr'),
               sessions=params.get('sessions'),
               sizes_rr=params.get('sizes_rr'),
               sizes=params.get('sizes'),
               protocols=params.get('protocols'),
               ver_cmd=params.get('ver_cmd', "rpm -q qemu-kvm"),
               netserver_port=params.get('netserver_port', "12865"),
               params=params)

@error.context_aware
def start_test(server, server_ctl, host, client, resultsdir, l=60,
               sessions_rr="50 100 250 500", sessions="1 2 4",
               sizes_rr="64 256 512 1024 2048",
               sizes="64 256 512 1024 2048 4096",
               protocols="TCP_STREAM TCP_MAERTS TCP_RR", ver_cmd=None,
               netserver_port=None, params={}):
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
    @param params: Dictionary with the test parameters.
    """

    def parse_file(file_prefix, raw=""):
        """ Parse result files and reture throughput total """
        thu = 0
        for file in glob.glob("%s.*.nf" % file_prefix):
            o = commands.getoutput("cat %s |tail -n 1" % file)
            try:
                thu += float(o.split()[raw])
            except Exception:
                logging.debug(commands.getoutput("cat %s.*" % file_prefix))
                return -1
        return thu

    fd = open("%s/netperf-result.RHS" % resultsdir, "w")
    fd.write("#ver# %s\n#ver# host kernel: %s\n#ver# guest kernel:%s\n" % (
             commands.getoutput(ver_cmd),
             os.uname()[2], ssh_cmd(server_ctl, "uname -r")))
    desc = """#desc# The tests are %s seconds sessions of "Netperf". 'throughput' was taken from netperf's report.
#desc# other measurements were taken on the host.
#desc# How to read the results:
#desc# - The Throughput is measured in Mbit/sec.
#desc# - io_exit: io exits of KVM.
#desc# - irq_inj: irq injections of KVM.
#desc#
""" % (l)
    fd.write(desc)

    record_list = ['size', 'sessions', 'throughput', '%CPU', 'thr/%CPU',
                   'rx_pkts', 'tx_pkts', 'rx_byts', 'tx_byts', 're_pkts',
                   'rx_intr', 'tx_intr', 'io_exit', 'irq_inj', 'tpkt/exit',
                   'rpkt/irq']
    base = params.get("format_base", "12")
    fbase = params.get("format_fbase", "2")

    output = ssh_cmd(host, "mpstat 1 1 |grep CPU")
    mpstat_head = re.findall("CPU.*", output)[0].split()
    mpstat_key = params.get("mpstat_key", "%idle")
    if mpstat_key in mpstat_head:
        mpstat_index = mpstat_head.index(mpstat_key) + 1
    else:
        mpstat_index = 0

    for protocol in protocols.split():
        error.context("Testing %s protocol" % protocol, logging.info)
        fd.write("Category:" + protocol+ "\n\n")
        if (protocol == "TCP_RR"):
            sessions_test = sessions_rr.split()
            sizes_test = sizes_rr.split()
        else:
            sessions_test = sessions.split()
            sizes_test = sizes.split()
        record_headon = True
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
                cpu = 100 - float(ret['mpstat'].split()[mpstat_index])
                normal = thu / cpu

                if ret.get('rx_pkts') and ret.get('irq_inj'):
                    ret['tpkt/exit'] = float(ret['rx_pkts']) / float(ret['irq_inj'])
                if ret.get('tx_pkts') and ret.get('io_exit'):
                    ret['rpkt/irq'] = float(ret['tx_pkts']) / float(ret['io_exit'])
                ret['size'] = int(i)
                ret['sessions'] = int(j)
                ret['throughput'] = thu
                ret['%CPU'] = cpu
                ret['thr/%CPU'] = normal
                row =  netperf_record(ret, record_list, headon=record_headon,
                                      base=base, fbase=fbase)
                if record_headon:
                    record_headon = False

                logging.info(row)
                fd.write(row + "\n")
                fd.flush()
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
