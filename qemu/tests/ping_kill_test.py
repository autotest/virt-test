import logging
import time
from autotest.client.shared import error
from virttest import aexpect, utils_net


@error.context_aware
def run(test, params, env):
    """
    Run two vms on same host, then  ifdown on the one side,
    ping -b -s 1472 on the other, check the guest not be locked

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def kill_and_check(vm):
        """
        Kill the vm and check vm is dead
        """
        vm.destroy(gracefully=False)
        if not vm.wait_until_dead(timeout=10):
            raise error.TestFail("VM is not dead, 10 secure after vm.destroy")
        logging.info("Vm is dead as expected")

    def guest_ping(session, dst_ip, count=None):
        """
        Do ping test in guest
        """
        os_type = params.get("os_type")
        packetsize = params.get("packetsize", 1472)
        test_runner = session.sendline
        if count:
            test_runner = session.cmd
        ping_cmd = "ping"
        if os_type == "linux":
            if count:
                ping_cmd += " -c %s" % count
            ping_cmd += " -s %s %s" % (packetsize, dst_ip)
        else:
            if not count:
                ping_cmd += " -t "
            ping_cmd += " -l %s %s" % (packetsize, dst_ip)
        try:
            test_runner(ping_cmd)
        except aexpect.ShellTimeoutError, err:
            if count:
                raise error.TestError("Error during ping guest ip, %s" % err)

    def manage_guest_nic(session, ifname, disabled=True):
        """
        Enable or disable guest nic
        """
        os_type = params.get("os_type", "linux")
        if os_type == "linux":
            shut_down_cmd = "ifconfig %s " % ifname
            if disabled:
                shut_down_cmd += " down"
            else:
                shut_down_cmd += " up"
            session.cmd_output_safe(shut_down_cmd)
        else:
            if disabled:
                utils_net.disable_windows_guest_network(session, ifname)
            else:
                utils_net.enable_windows_guest_network(session, ifname)

    error.context("Init boot the vms")
    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)

    dsthost = params.get("dsthost", "vm2")
    if dsthost not in params.get("vms", "vm1 vm2"):
        raise error.TestNAError("This test must boot two vms")
    dst_vm = env.get_vm(dsthost)
    dst_vm.verify_alive()
    dst_vm.wait_for_login(timeout=login_timeout)
    dst_ip = dst_vm.get_address()
    session_serial = dst_vm.wait_for_serial_login(timeout=login_timeout)

    try:
        error.context("Ping dst guest", logging.info)
        guest_ping(session, dst_ip, count=4)
        error.context("Disable the dst guest nic interface", logging.info)
        macaddress = dst_vm.get_mac_address()
        if params.get("os_type") == "linux":
            ifname = utils_net.get_linux_ifname(session_serial, macaddress)
        else:
            ifname = utils_net.get_windows_nic_attribute(session_serial,
                    "macaddress", macaddress, "netconnectionid")
        manage_guest_nic(session_serial, ifname)
        error.context("Ping dst guest after disabling it's nic", logging.info)
        ping_timeout = float(params.get("ping_timeout", 21600))
        guest_ping(session, dst_ip)
        time.sleep(ping_timeout)
        error.context("Kill the guest after ping", logging.info)
        kill_and_check(vm)
    finally:
        if session_serial:
            manage_guest_nic(session_serial, ifname, False)
            session_serial.close()
        if session:
            session.close()
