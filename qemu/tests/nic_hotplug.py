import logging
from autotest.client.shared import error
from virttest import utils_test, utils_net, virt_vm


@error.context_aware
def run(test, params, env):
    """
    Test hotplug of NIC devices

    1) Boot up guest with one nic
    2) Add a host network device through monitor cmd and check if it's added
    3) Add nic device through monitor cmd and check if it's added
    4) Check if new interface gets ip address
    5) Disable primary link of guest
    6) Ping guest new ip from host
    7) Delete nic device and netdev
    8) Ping guest's new ip address after guest pause/resume
    9) Re-enable primary link of guest

    BEWARE OF THE NETWORK BRIDGE DEVICE USED FOR THIS TEST ("nettype=bridge"
    and "netdst=<bridgename>" param).  The KVM autotest default bridge virbr0,
    leveraging libvirt, works fine for the purpose of this test. When using
    other bridges, the timeouts which usually happen when the bridge
    topology changes (that is, devices get added and removed) may cause random
    failures.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    login_timeout = int(params.get("login_timeout", 360))
    pci_model = params.get("pci_model", "rtl8139")
    run_dhclient = params.get("run_dhclient", "no")

    nettype = params.get("nettype", "bridge")
    netdst = params.get("netdst", "virbr0")
    guest_is_not_windows = "Win" not in params.get("guest_name", "")

    session = vm.wait_for_login(timeout=login_timeout)

    if guest_is_not_windows:
        # Modprobe the module if specified in config file
        module = params.get("modprobe_module")
        if module:
            session.get_command_output("modprobe %s" % module)

    # hot-add the nic
    error.context("Add network devices through monitor cmd", logging.info)
    nic_name = 'hotadded'
    nic_info = vm.hotplug_nic(nic_model=pci_model, nic_name=nic_name,
                              netdst=netdst, nettype=nettype,
                              queues=params.get('queues'),
                              vectors=params.get('vectors'))

    # Only run dhclient if explicitly set and guest is not running Windows.
    # Most modern Linux guests run NetworkManager, and thus do not need this.
    if run_dhclient == "yes" and guest_is_not_windows:
        session_serial = vm.wait_for_serial_login(timeout=login_timeout)
        ifname = utils_net.get_linux_ifname(session, nic_info['mac'])
        session_serial.cmd("dhclient %s &" % ifname)

    error.context("Disable the primary link(s) of guest", logging.info)
    for nic in vm.virtnet:
        if not (nic.nic_name == nic_name):
            vm.set_link(nic.device_id, up=False)

    try:
        error.context("Check if new interface gets ip address", logging.info)
        try:
            ip = vm.wait_for_get_address(nic_name)
        except virt_vm.VMIPAddressMissingError:
            raise error.TestFail("Could not get or verify ip address of nic")
        logging.info("Got the ip address of new nic: %s", ip)

        error.context("Ping guest's new ip from host", logging.info)
        s, o = utils_test.ping(ip, 10, timeout=15)
        if s != 0:
            logging.error(o)
            raise error.TestFail("New nic failed ping test")
        error.context("Ping guest's new ip after pasue/resume", logging.info)
        vm.monitor.cmd("stop")
        vm.monitor.cmd("cont")
        s, o = utils_test.ping(ip, 10, timeout=15)
        if s != 0:
            logging.error(o)
            raise error.TestFail("New nic failed ping test after stop/cont")

        logging.info("Detaching the previously attached nic from vm")
        error.context("Detaching the previously attached nic from vm",
                      logging.info)
        vm.hotunplug_nic(nic_name)

    finally:
        error.context("Re-enabling the primary link(s)", logging.info)
        for nic in vm.virtnet:
            if not (nic.nic_name == nic_name):
                vm.set_link(nic.device_id, up=True)
