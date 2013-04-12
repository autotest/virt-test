import logging, time
from autotest.client.shared import error
from virttest import utils_test, virt_vm, aexpect, utils_misc, utils_net
@error.context_aware
def run_nic_hotplug(test, params, env):
    """
    Test hotplug of NIC devices

    1) Boot up guest with one nic
    2) Backup udev file
    3) Add a host network device through monitor cmd and check if it's added
    4) Add nic device through monitor cmd and check if it's added
    5) Check if new interface gets ip address
    6) Disable primary link of guest
    7) Ping guest's new ip from host
    8) Ping guest's new ip address after guest pause/resume
    9) Delete nic device and netdev
    10) Re-enable primary link of guest

    BEWARE OF THE NETWORK BRIDGE DEVICE USED FOR THIS TEST ("bridge" param).
    The KVM autotest default bridge virbr0, leveraging libvirt, works fine
    for the purpose of this test. When using other bridges, the timeouts
    which usually happen when the bridge topology changes (that is, devices
    get added and removed) may cause random failures.

    @param test:   QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env:    Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    login_timeout = int(params.get("login_timeout", 360))
    guest_delay = int(params.get("guest_delay", 20))
    pci_model = params.get("pci_model", "rtl8139")
    run_dhclient = params.get("run_dhclient", "no")
    guest_is_not_windows = (params.get("os_type") != 'windows')

    session = vm.wait_for_login(timeout=login_timeout)

    udev_rules_path = "/etc/udev/rules.d/70-persistent-net.rules"
    udev_rules_bkp_path = "/tmp/70-persistent-net.rules"

    def guest_path_isfile(session, path):
        try:
            session.cmd("test -f %s" % path)
        except aexpect.ShellError:
            return False
        return True

    def _backup_udev_file():
        if (guest_is_not_windows
            and guest_path_isfile(session, udev_rules_path)):
            error.context("Backup udev file.", logging.info)
            session.cmd("/bin/cp  %s %s" % (udev_rules_path, udev_rules_bkp_path))

    def _restore_udev_file():
        # Attempt to put back udev network naming rules, even if the command to
        # disable the rules failed. We may be undoing what was done in a
        # previous (failed) test that never reached this point.
        try:
            if vm.serial_console:
                sess = vm.serial_console
            else:
                sess = vm.wait_for_serial_login(timeout=login_timeout)
            if (guest_is_not_windows
                and guest_path_isfile(sess, udev_rules_bkp_path)):
                sess.cmd("/bin/cp %s %s" % (udev_rules_bkp_path,
                                          udev_rules_path))
        except Exception, e:
            logging.warn("Could not restore udev file: '%s'", e)


    _backup_udev_file()

    # Modprobe the module if specified in config file
    module = params.get("modprobe_module")
    if guest_is_not_windows and module:
        session.cmd("modprobe %s" % module)

    # hot-add the nic
    error.context("Add network devices through monitor cmd", logging.info)
    nic_name = 'hotadded'
    nic_info = vm.hotplug_nic(nic_model=pci_model, nic_name=nic_name)
    nic_mac = nic_info['mac']

    # Only run dhclient if explicitly set and guest is not running Windows.
    # Most modern Linux guests run NetworkManager, and thus do not need this.
    if run_dhclient == "yes" and guest_is_not_windows:
        session_serial = vm.wait_for_serial_login(timeout=login_timeout)
        ifname = utils_net.get_linux_ifname(session, nic_mac)
        utils_net.restart_guest_network(session_serial, ifname)
        # Guest need to take quite a long time to set the ip addr, sleep a
        # while to wait for guest done.
        time.sleep(60)

    error.context("Disable the primary link of guest", logging.info)
    # Close existed session first.
    session.close()
    for nic in vm.virtnet:
        if nic.nic_name == nic_name:
            continue
        else:
            vm.set_link(nic.device_id, up=False)

    try:
        error.context("Check if new interface gets ip address", logging.info)
        try:
            ip = vm.wait_for_get_address(nic_name)
        except virt_vm.VMIPAddressMissingError:
            raise error.TestFail("Could not get or verify ip address of nic")
        logging.info("Got the ip address of new nic: %s", ip)
    except Exception:
        try:
            vm.hotunplug_nic(nic_name)
        except Exception, e:
            logging.warn("Fail to delete nic card from guest: '%s'", e)
        _restore_udev_file()
        raise

    try:
        error.context("Ping guest's new ip from host", logging.info)
        s, _ = utils_test.ping(ip, 10, timeout=15)
        if s != 0:
            logging.error(_)
            raise error.TestFail("New nic failed ping test")
        error.context("Ping guest's new ip after pasue/resume", logging.info)
        vm.pause()
        vm.resume()
        s, _ = utils_test.ping(ip, 10, timeout=15)
        if s != 0:
            logging.error(_)
            raise error.TestFail("Ping new nic ip addr failed after stop/cont")
    finally:
        try:
            error.context("Delete nic device and netdev from guest",
                          logging.info)
            vm.hotunplug_nic(nic_name)
        finally:
            error.context("Re-enabling the primary link of guest", logging.info)
            for nic in vm.virtnet:
                if nic.nic_name == nic_name:
                    continue
                else:
                    vm.set_link(nic.device_id, up=True)
            _restore_udev_file()
