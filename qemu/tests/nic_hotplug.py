import logging
import random
from autotest.client.shared import error
from virttest import utils_test, utils_net, virt_vm


@error.context_aware
def run(test, params, env):
    """
    Test hotplug of NIC devices

    1) Boot up guest with one or multi nics
    2) Add multi host network devices through monitor cmd and
       check if they are added
    3) Add multi nic devices through monitor cmd and check if they are added
    4) Check if new interface gets ip address
    5) Disable primary link of guest
    6) Ping guest new ip from host
    7) Delete nic device and netdev if user config "do_random_unhotplug"
    8) Ping guest's new ip address after guest pause/resume
    9) Re-enable primary link of guest and hotunplug the plug nics

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
    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)
    primary_nic = [ nic for nic in vm.virtnet ]

    run_dhclient = params.get("run_dhclient", "no")
    guest_is_linux = ("linux" ==  params.get("os_type", ""))

    if guest_is_linux:
        # Modprobe the module if specified in config file
        module = params.get("modprobe_module")
        if module:
            session.cmd_output_safe("modprobe %s" % module)

    nic_hotplug_count = int(params.get("nic_hotplug_count", 1))
    nic_hotplugged = []
    try:
        for nic_index in xrange(1, nic_hotplug_count + 1):
            nic_name = "hotplug_nic%s" % nic_index
            nic_params = params.object_params(nic_name)
            nic_model = nic_params["pci_model"]
            nic_params["nic_model"] = nic_model
            nic_params["nic_name"] = nic_name

            error.context("Disable other link(s) of guest", logging.info)
            disable_nic_list = primary_nic + nic_hotplugged
            for nic in disable_nic_list:
                vm.set_link(nic.device_id, up=False)

            error.context("Hotplug %sth '%s' nic named '%s'" % (nic_index,
                          nic_model, nic_name))
            hotplug_nic = vm.hotplug_nic(**nic_params)
            # Only run dhclient if explicitly set and guest is not windows.
            # Most modern Linux guests run NetworkManager,
            #and thus do not need this.
            s_session = vm.wait_for_serial_login(timeout=login_timeout)
            if guest_is_linux:
                if run_dhclient == "yes":
                    s_session.cmd_output_safe("killall -9 dhclient")
                    ifname = utils_net.get_linux_ifname(s_session,
                                                        hotplug_nic['mac'])
                    s_session.cmd_output_safe("dhclient %s &" % ifname)

                arp_clean = "arp -n|awk '/^[1-9]/{print \"arp -d \" $1}'|sh"
                s_session.cmd_output_safe(arp_clean)

            error.context("Check if new interface gets ip address",
                          logging.info)
            try:
                hotnic_ip = vm.wait_for_get_address(nic_name)
            except virt_vm.VMIPAddressMissingError, err:
                err_msg = "Could not get or verify nic ip address"
                err_msg += "error info: '%s' " % err
                raise error.TestFail(err_msg)
            logging.info("Got the ip address of new nic: %s", hotnic_ip)

            error.context("Ping guest's new ip from host", logging.info)
            status, output = utils_test.ping(hotnic_ip, 10, timeout=30)
            if status:
                err_msg = "New nic failed ping test, error info: '%s'"
                raise error.TestFail(err_msg % output)

            error.context("Ping guest's new ip after pasue/resume",
                          logging.info)
            vm.monitor.cmd("stop")
            vm.monitor.cmd("cont")
            status, output = utils_test.ping(hotnic_ip, 10, timeout=30)
            if status:
                err_msg = "New nic failed ping test after stop/cont, "
                err_msg += "error info: '%s'" % output
                raise error.TestFail(err_msg)

            # random hotunplug nic
            nic_hotplugged.append(hotplug_nic)
            if random.randint(0, 1) and params.get("do_random_unhotplug"):
                error.context("Detaching the previously attached nic from vm",
                              logging.info)
                unplug_nic_index = random.randint(0, len(nic_hotplugged) - 1)
                vm.hotunplug_nic(nic_hotplugged[unplug_nic_index].nic_name)
                nic_hotplugged.pop(unplug_nic_index)
    finally:
        for nic in nic_hotplugged:
            vm.hotunplug_nic(nic.nic_name)
        error.context("Re-enabling the primary link(s)", logging.info)
        for nic in primary_nic:
            vm.set_link(nic.device_id, up=True)
