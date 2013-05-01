import logging
from autotest.client import utils
from autotest.client.shared import error
from virttest import utils_test, utils_net


@error.context_aware
def run_nic_promisc(test, params, env):
    """
    Test nic driver in promisc mode:

    1) Boot up a VM.
    2) Repeatedly enable/disable promiscuous mode in guest.
    3) Transfer file from host to guest, and from guest to host in the same time

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """


    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session_serial = vm.wait_for_serial_login(timeout=timeout)
    error.context("Get NIC interface name in guest.", logging.info)
    ethname = utils_net.get_linux_ifname(session_serial,
                                              vm.get_mac_address(0))

    try:
        error.context("Transfer file between guest and host.", logging.info)
        transfer_thread = utils.InterruptedThread(
                                               utils_test.run_file_transfer,
                                               (test, params, env))
        transfer_thread.start()
        while transfer_thread.isAlive():
            txt = "Enable promiscuous mode in guest NIC interface %s" % ethname
            error.context(txt, logging.info) 
            session_serial.cmd("ip link set %s promisc on" % ethname)
            txt = "Disable promiscuous mode in guest interface %s" % ethname
            error.context(txt, logging.info)
            session_serial.cmd("ip link set %s promisc off" % ethname)
    except Exception:
        transfer_thread.join(suppress_exception=True)
        raise
    else:
        transfer_thread.join()
