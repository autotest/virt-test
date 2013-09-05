import logging, time, random
from virttest import utils_test, aexpect, utils_net
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
    def send_cmd_safe(session, cmd, timeout=60):
        logging.debug("Sending command: %s", cmd)
        session.sendline(cmd)
        output = ""
        start_time = time.time()
        # Wait for shell prompt until timeout.
        while (time.time() - start_time) < timeout:
            session.sendline()
            try:
                output += session.read_up_to_prompt(0.5)
                break
            except aexpect.ExpectTimeoutError:
                pass
        return output


    timeout = int(params.get("login_timeout", 1200))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session_serial = vm.wait_for_serial_login(timeout=timeout)
    ifnames = [utils_net.get_linux_ifname(session_serial,
                                          vm.get_mac_address(vlan))
               for vlan, nic in enumerate(vm.virtnet)]

    # get params of bonding
    nm_stop_cmd = "pidof NetworkManager && service NetworkManager stop; true"
    send_cmd_safe(session_serial, nm_stop_cmd)
    modprobe_cmd = "modprobe bonding"
    bonding_params = params.get("bonding_params")
    if bonding_params:
        modprobe_cmd += " %s" % bonding_params
    send_cmd_safe(session_serial, modprobe_cmd)
    send_cmd_safe(session_serial, "ifconfig bond0 up")
    setup_cmd = "ifenslave bond0 " + " ".join(ifnames)
    send_cmd_safe(session_serial, setup_cmd)
    #do a pgrep to check if dhclient has already been running
    pgrep_cmd = "pgrep dhclient"
    try:
        send_cmd_safe(session_serial, pgrep_cmd)
    #if dhclient is there, killl it
    except aexpect.ShellCmdError:
        logging.info("it's safe to run dhclient now")
    else:
        logging.info("dhclient already is running,kill it")
        send_cmd_safe(session_serial, "killall -9 dhclient")
        time.sleep(1)

    send_cmd_safe(session_serial, "dhclient bond0")

    #get_bonding_nic_mac and ip
    try:
        logging.info("Test file transferring:")
        utils_test.run_file_transfer(test, params, env)

        logging.info("Failover test with file transfer")
        transfer_thread = utils.InterruptedThread(utils_test.run_file_transfer,
                                                  (test, params, env))
        transfer_thread.start()
        try:
            while transfer_thread.isAlive():
                for vlan, nic in enumerate(vm.virtnet):
                    device_id = nic.device_id
                    if not device_id:
                        raise error.TestError("Could not find peer device for"
                                              " nic device %s" % nic)
                    vm.set_link(device_id, up=False)
                    time.sleep(random.randint(1, 30))
                    vm.set_link(device_id, up=True)
                    time.sleep(random.randint(1, 30))
        except Exception:
            transfer_thread.join(suppress_exception=True)
            raise
        else:
            transfer_thread.join()
    finally:
        session_serial.sendline("ifenslave -d bond0 " + " ".join(ifnames))
        session_serial.sendline("kill -9 `pgrep dhclient`")
