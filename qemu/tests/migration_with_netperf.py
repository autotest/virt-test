import logging, time, os, commands
from autotest.client.shared import utils, error
from autotest.client import utils as client_utils

@error.context_aware
def run_migration_with_netperf(test, params, env):
    """
    KVM migration test:
    1) Start a guest.
    2) Start netperf server in guest.
    3) Start multi netperf clients in host.
    4) Migrate the guest in local during netperf clients working.
    5) Repeatedly migrate VM and wait until netperf clients stopped.

    @param test: QEMU test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """

    def start_netperf_server():
        logging.info("Start netserver in guest.")
        netserver_cmd = params.get("netserver_cmd") % "/tmp"
        (s, o) = session.cmd_status_output(netserver_cmd,
                                             timeout=netperf_timeout)
        if s:
            raise error.TestFail("Fail to start netserver:\n %s" % o)

    def start_netperf_client(i=0):
        logging.info("Netperf_%s" % i)
        cmd = "cd %s && %s" % (netperf_path, netperf_cmd)
        try:
            netperf_output = commands.getoutput(cmd)
            open("Netperf_%s" % i, "w").write(netperf_output)
        except OSError:
            pass

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    mig_timeout = float(params.get("mig_timeout", "3600"))
    cmd_timeout = int(params.get("cmd_timeout", "360"))
    mig_protocol = params.get("migration_protocol", "tcp")
    mig_cancel_delay = int(params.get("mig_cancel") == "yes") * 2
    netperf_path = params.get("netperf_path")
    if not netperf_path.startswith("/"):
        netperf_path = os.path.join(test.bindir, netperf_path)

    netperf_timeout = int(params.get("netperf_timeout", "300"))
    client_num = int(params.get("client_num", "100"))
    bg_list = []
    m_count = 0
    try:
        session.cmd("service iptables stop")
        logging.info("Setup netperf server in guest.")
        vm.copy_files_to(netperf_path, "/tmp")
        setup_cmd = params.get("setup_cmd")
        cmd = "cd /tmp/netperf2 && %s" % setup_cmd
        session.cmd(cmd, timeout=cmd_timeout)
        logging.info("Setup netperf client in host.")
        setup_cmd = params.get("setup_cmd")
        netperf_cmd = params.get("netperf_cmd") % (vm.get_address(),
                                                       netperf_timeout)
        cmd = "cd %s && %s" % (netperf_path, setup_cmd)
        utils.system(cmd)

        bg = utils.InterruptedThread(start_netperf_server)
        bg.start()
        # Wait netserver start in guest.
        time.sleep(20)
        for i in range(client_num):
            bg_list.append(utils.InterruptedThread(start_netperf_client, (i,)))
            bg_list[i].start()
        while True:
            m_count += 1
            logging.info("Start migration iterations: %s " % m_count)
            vm.migrate(mig_timeout, mig_protocol, mig_cancel_delay)
            if not bg_list[0].isAlive():
                logging.info("Background Netperf finished.")
                break

    finally:
        try:
            for b in bg_list:
                if b:
                    b.join(timeout=10, suppress_exception=True)
        finally:
            session.cmd("killall netserver", timeout=cmd_timeout)
            bg.join(timeout=10, suppress_exception=True)
            session.close()
