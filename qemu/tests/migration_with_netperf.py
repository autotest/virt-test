import logging
from autotest.client.shared import error
from virttest import utils_netperf


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

    login_timeout = int(params.get("login_timeout", 360))
    mig_timeout = float(params.get("mig_timeout", "3600"))
    mig_protocol = params.get("migration_protocol", "tcp")
    mig_cancel_delay = int(params.get("mig_cancel") == "yes") * 2
    netperf_timeout = int(params.get("netperf_timeout", "300"))
    client_num = int(params.get("client_num", "100"))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)

    guest_address = vm.get_address()
    download_link = params.get("netperf_download_link")
    md5sum = params.get("pkg_md5sum")
    server_download_link = params.get("server_download_link", download_link)
    server_md5sum = params.get("server_md5sum", md5sum)
    server_path = params.get("server_path", "/tmp")
    client_path = params.get("client_path", "/tmp")

    username = params.get("username", "root")
    password = params.get("password", "redhat")
    passwd = params.get("hostpasswd", "redhat")
    client = params.get("shell_client", "ssh")
    port = params.get("shell_port", "22")

    netperf_client = utils_netperf.NetperfClient("localhost", client_path,
                                                 md5sum, download_link,
                                                 password=passwd)

    netperf_server = utils_netperf.NetperfServer(guest_address,
                                                 server_path,
                                                 server_md5sum,
                                                 server_download_link,
                                                 client, port,
                                                 username=username,
                                                 password=password)

    try:
        session.cmd("service iptables stop; iptables -F || true")
        error.base_context("Run netperf test between host and guest")
        error.context("Start netserver in guest.", logging.info)
        netperf_server.start()
        error.context("Start Netperf on host", logging.info)
        test_option = "-l %s" % netperf_timeout
        netperf_client.bg_start(guest_address, test_option, client_num)

        m_count = 0
        while netperf_client.is_test_running():
            m_count += 1
            error.context("Start migration iterations: %s " % m_count,
                          logging.info)
            vm.migrate(mig_timeout, mig_protocol, mig_cancel_delay)
    finally:
        netperf_server.stop()
        netperf_server.env_cleanup(True)
        netperf_client.env_cleanup(True)
        if session:
            session.close()
