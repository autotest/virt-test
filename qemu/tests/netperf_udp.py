import logging
import os
from autotest.client.shared import error
from virttest import utils_misc, remote, utils_net


@error.context_aware
def run_netperf_udp(test, params, env):
    """
    Run netperf on server and client side, we need run this case on two
    machines. If dsthost is not set will start netperf server on local
    host and log a error message.:
    1) Start one vm guest os as client.
    2) Start a reference machine (dsthost) as server.
    3) Setup netperf on guest and reference machine (dsthost).
    4) Run netserver on server using control.server.
    5) Run netperf client command in guest several time with different
       message size.
    6) Compare UDP performance to make sure it is acceptable.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_remote_host_session():
        dsthostssh = remote.remote_login("ssh", dsthost, 22, "root",
                                         passwd, "#", timeout=30)
        if dsthostssh:
            dsthostssh.set_status_test_command("echo $?")
            return dsthostssh
        else:
            return None

    def scp_to_remote(local_path="", remote_path=""):
        remote.scp_to_remote(dsthost, 22, "root", passwd, local_path,
                             remote_path)
        vm.copy_files_to(local_path, remote_path)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    dsthost = params.get("dsthost")
    if not dsthost:
        dsthost = utils_net.get_ip_address_by_interface(params.get("netdst"))
        logging.error("dsthost is not set, use localhost ip %s" % dsthost)
    else:
        logging.info("Dest host is %s" % dsthost)
    passwd = params.get("hostpasswd")
    test_timeout = float(params.get("test_timeout", "1200"))

    error.context("Create session connection to remote machine")
    dsthostssh = utils_misc.wait_for(get_remote_host_session, 120, 0, 2)
    if not dsthostssh:
        raise error.TestError("Could not login into remote host %s " % dsthost)

    # Get range of message size.
    message_size_range = params.get("message_size_range")
    message_size = message_size_range.split()
    start_size = int(message_size[0])
    end_size = int(message_size[1])
    step = int(message_size[2])
    m_size = start_size

    error.context("Copy netperf to dsthost and guest vm.")
    netperf_dir = os.path.join(os.environ['AUTODIR'], "tests/netperf2")
    for i in params.get("netperf_files").split():
        scp_to_remote("%s/%s" % (netperf_dir, i), "/tmp/")

    # Setup netpref.
    error.context("Set up netperf on reference machine.", logging.info)
    cmd = params.get("setup_cmd")
    (s, output) = dsthostssh.get_command_status_output(cmd,
                                                       timeout=test_timeout)
    if s != 0:
        raise error.TestError("Fail to setup netperf on reference machine.")
    error.context("Setup netperf on guest os.", logging.info)
    (s, output) = session.get_command_status_output(cmd,
                                                    timeout=test_timeout)
    if s != 0:
        raise error.TestError("Fail to setup netperf on guest os.")

    # Start netperf server in dsthost.
    cmd = "killall netserver"
    dsthostssh.get_command_status_output(cmd)
    cmd = params.get("netserver_cmd")
    txt = "Run netserver on server (dsthost) using control.server."
    error.context(txt, logging.info)
    (s, output) = dsthostssh.get_command_status_output(cmd)
    if s != 0:
        txt = "Fail to start netperf server on remote machine."
        txt += " Command output: %s" % output
        raise error.TestError(txt)

    throughput = []

    # Run netperf with message size defined in range.
    msg = "Detail result for netperf udp test with different message size.\n"
    while(m_size <= end_size):
        cmd = params.get("netperf_cmd") % (dsthost, m_size)
        txt = "Run netperf client command in guest: %s" % cmd
        error.context(txt, logging.info)
        (s, output) = session.get_command_status_output(cmd)
        if s != 0:
            txt = "Fail to execute netperf client side command in guest."
            txt += " Command output: %s" % output
            raise error.TestError(txt)
        line_tokens = output.splitlines()[6].split()
        throughput.append(float(line_tokens[5]))
        msg += output
        m_size += step
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

    cmd = "killall -9 netserver"
    try:
        dsthostssh.get_command_status_output(cmd)
    except Exception:
        pass
