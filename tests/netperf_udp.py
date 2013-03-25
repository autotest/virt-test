import logging, os
from autotest.client.shared import error
from autotest.client.virt import utils_misc


def run_netperf_udp(test, params, env):
    """
    Run netperf2 on two guests:
    1) Start one vm guest os as client.
    2) Start a reference machine as server.
    3) Setup netperf on client and server.
    4) Run netserver on server using control.server.
    5) Run netperf on client several time with different message size.
    6) Compare UDP performance to make sure it is acceptable.

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """

    def get_remote_host_session():
        dsthostssh = utils_misc.remote_login("ssh", dsthost, 22, "root",
                                            PASSWD, "#", timeout=30)
        if dsthostssh:
            dsthostssh.set_status_test_command("echo $?")
            return dsthostssh
        else:
            return None


    def scp_to_remote(local_path="", remote_path=""):
        utils_misc.scp_to_remote(dsthost, 22, "root",PASSWD, local_path,
                                remote_path)
        vm.copy_files_to(local_path,remote_path)


    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    dsthost = params.get("dsthost")
    logging.info("Dest host is %s" % dsthost)
    PASSWD = params.get("hostpasswd")
    test_timeout = float(params.get("test_timeout", "1200"))

    # Create session connection to remote machine
    dsthostssh = utils_misc.wait_for(get_remote_host_session, 120, 0, 2)
    if not dsthostssh:
        raise error.TestError("Could not login into remote host %s " % dsthost)

    # Get range of message size.
    message_size_range = params.get("message_size_range")
    message_size = message_size_range.split()
    logging.debug(message_size)
    st_size = int(message_size[0])
    end_size = int(message_size[1])
    step = int(message_size[2])
    m_size = st_size

    # Copy netperf to dsthsot and guest vm.
    local_path = params.get("netperf_path") % test.bindir
    scp_to_remote(local_path,"")
    local_path = params.get("patch_path") % test.bindir
    scp_to_remote(local_path,"")

    # Setup netpref.
    cmd = params.get("setup_cmd")
    (s, output) = dsthostssh.get_command_status_output(cmd,
                                                       timeout=test_timeout)
    if s != 0:
        raise error.TestFail("Fail to setup netperf on remote machine.")
    (s, output) = session.get_command_status_output(cmd,
                                                   timeout=test_timeout)
    if s != 0:
        raise error.TestFail("Fail to setup netperf on guest os.")

    # Start netperf server in dsthost.
    cmd = "killall netserver"
    dsthostssh.get_command_status_output(cmd)
    cmd = params.get("netserver_cmd")
    (s, output) = dsthostssh.get_command_status_output(cmd)
    if s != 0:
        raise error.TestFail("Failt to start netperf server on remote machine")

    throughput = []

    # Run netperf with message size defined in range.
    msg = "Detail result for netperf udp test with different message size.\n"
    file(os.path.join(test.debugdir, "udp_results"),"w").write(msg)
    while(m_size <= end_size):
        cmd = params.get("netperf_cmd")% (dsthost, m_size)
        (s,output) = session.get_command_status_output(cmd)
        if s != 0:
            raise error.TestFail("Fail to execute netperf client side command")
        line_tokens = output.splitlines()[6].split()
        throughput.append(float(line_tokens[5]))
        file(os.path.join(test.debugdir, "udp_results"),"a+").write(output)
        m_size += step

    failratio = float(params.get("failratio"))
    for i in range(len(throughput) - 1):
        if abs(throughput[i] - throughput[i + 1]) > throughput[i] * failratio:
            raise error.TestFail("The gap between adjacent throughput is"
                                 " greater than %f. Please refer to log"
                                 " for details information!" % failratio)
    logging.debug("The UDP performance as measured via netperf is ok")
    cmd = "killall netserver"
    dsthostssh.get_command_status_output(cmd)

    session.close()
    dsthostssh.close()
