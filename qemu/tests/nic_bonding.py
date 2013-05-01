import logging, time
from virttest import utils_test, aexpect
from autotest.client.shared import error, utils


def run_nic_bonding(test, params, env):
    """
    Nic bonding test in guest.

    1) Start guest with four nic models.
    2) Setup bond0 in guest by script nic_bonding_guest.py.
    3) Execute file transfer test between guest and host.
    4) Repeatedly put down/up interfaces by set_link
    5) Execute file transfer test between guest and host.

    @param test: Kvm test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    timeout = int(params.get("login_timeout", 1200))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session_serial = vm.wait_for_serial_login(timeout=timeout)

    # get params of bonding
    modprobe_cmd = "modprobe bonding"
    bonding_params = params.get("bonding_params")
    if bonding_params:
        modprobe_cmd += " %s" % bonding_params
    session_serial.cmd(modprobe_cmd)

    session_serial.cmd("ifconfig bond0 up")
    ifnames = [utils_test.get_linux_ifname(session_serial,
                                               vm.get_mac_address(vlan))
               for vlan, nic in enumerate(vm.virtnet)]
    setup_cmd = "ifenslave bond0 " + " ".join(ifnames)
    session_serial.cmd(setup_cmd)
    #do a pgrep to check if dhclient has already been running
    pgrep_cmd = "pgrep dhclient"
    try:
        session_serial.cmd(pgrep_cmd)
    #if dhclient is there, killl it
    except aexpect.ShellCmdError:
        logging.info("it's safe to run dhclient now")
    else:
        logging.info("dhclient already is running,kill it")
        session_serial.cmd("killall -9 dhclient")
        time.sleep(1)
    session_serial.cmd("dhclient bond0")

    try:
        logging.info("Test file transfering:")
        utils_test.run_file_transfer(test, params, env)

        logging.info("Failover test with file transfer")
        transfer_thread = utils.InterruptedThread(
                                              utils_test.run_file_transfer,
                                               (test, params, env))
        try:
            transfer_thread.start()
            while transfer_thread.isAlive():
                for vlan, nic in enumerate(vm.virtnet):
                    device_id = vm.get_peer(vm.netdev_id[vlan])
                    if not device_id:
                        raise error.TestError("Could not find peer device for"
                                              " nic device %s" % nic)
                    vm.set_link(device_id, up=False)
                    time.sleep(1)
                    vm.set_link(device_id, up=True)
        except Exception:
            transfer_thread.join(suppress_exception=True)
            raise
        else:
            transfer_thread.join()
    finally:
        session_serial.sendline("ifenslave -d bond0 " + " ".join(ifnames))
        session_serial.sendline("kill -9 `pgrep dhclient`")
