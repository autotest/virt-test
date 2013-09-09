import logging
import os
from autotest.client.shared import utils, error
from virttest import utils_misc


@error.context_aware
def run_migration_with_netperf(test, params, env):
    """
    KVM migration test:
    1) Start a guest.
    2) Start netperf server in guest.
    3) Start multi netperf clients in host.
    4) Migrate the guest in local during netperf clients working.
    5) Repeatedly migrate VM and wait until netperf clients stopped.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def start_netperf_server():
        netserver_cmd = params.get("netserver_cmd")
        (status, output) = session.cmd_status_output(netserver_cmd,
                                                     timeout=netperf_timeout)
        if status:
            raise error.TestFail("Fail to start netserver:\n %s" % output)

    def start_netperf_client(i=0):
        logging.info("Netperf_%s" % i)
        try:
            netperf_output = utils.system_output(netperf_cmd)
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
    cleanup_cmd = params.get("cleanup_cmd")
    netperf_timeout = int(params.get("netperf_timeout", "300"))
    client_num = int(params.get("client_num", "100"))
    bg_list = []
    m_count = 0
    try:
        session.cmd("service iptables stop")
        error.context("Setup netperf server in guest.", logging.info)
        netperf_dir = os.path.join(os.environ['AUTODIR'], "tests/netperf2")
        for i in params.get("netperf_files").split():
            vm.copy_files_to("%s/%s" % (netperf_dir, i), "/tmp")
            utils.get_file("%s/%s" % (netperf_dir, i), "/tmp/%s" % i)
        setup_cmd = params.get("setup_cmd")
        session.cmd(setup_cmd, timeout=cmd_timeout)
        error.context("Setup netperf client in host.", logging.info)
        utils.system(setup_cmd)
        netperf_cmd = params.get("netperf_cmd") % (vm.get_address(),
                                                   netperf_timeout)
        error.context("Start netserver in guest.", logging.info)
        bg_list.append(utils.InterruptedThread(start_netperf_server))
        if bg_list[0]:
            bg_list[0].start()
        # Wait netserver start in guest.
        ses = vm.wait_for_login(timeout=login_timeout)
        n_cmd = params.get("netserver_check_cmd", "ps -a | grep netserver")
        utils_misc.wait_for(lambda: not ses.cmd_status(n_cmd), 30, 2, 2)
        if ses:
            ses.close()
        for i in xrange(1, client_num + 1):
            bg_list.append(utils.InterruptedThread(start_netperf_client, (i,)))
            bg_list[i].start()
        while True:
            m_count += 1
            error.context("Start migration iterations: %s " % m_count,
                          logging.info)
            vm.migrate(mig_timeout, mig_protocol, mig_cancel_delay)
            if not bg_list[-1].isAlive():
                logging.info("Background Netperf finished.")
                break
    finally:
        try:
            for b in bg_list:
                if b:
                    b.join(timeout=10, suppress_exception=True)
        finally:
            session.cmd("killall -9 netserver ; echo 1", timeout=cmd_timeout)
            if cleanup_cmd:
                utils.system(cleanup_cmd)
                session.cmd(cleanup_cmd)
            if session:
                session.close()
