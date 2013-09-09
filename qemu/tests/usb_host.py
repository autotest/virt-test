import logging
from autotest.client.shared import error
from autotest.client import utils


@error.context_aware
def run_usb_host(test, params, env):
    """
    Test usb host device passthrough

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    @error.context_aware
    def usb_dev_hotplug():
        error.context("Plugin usb device", logging.info)
        session.cmd_status("dmesg -c")
        vm.monitor.cmd(monitor_add)
        session.cmd_status("sleep 1")
        session.cmd_status("udevadm settle")
        messages_add = session.cmd("dmesg -c")
        for line in messages_add.splitlines():
            logging.debug("[dmesg add] %s" % line)
        if messages_add.find(match_add) == -1:
            raise error.TestFail("kernel didn't detect plugin")

    @error.context_aware
    def usb_dev_verify():
        error.context("Check usb device %s in guest" % device, logging.info)
        session.cmd(lsusb_cmd)

    @error.context_aware
    def usb_dev_unplug():
        error.context("Unplug usb device", logging.info)
        vm.monitor.cmd(monitor_del)
        session.cmd_status("sleep 1")
        messages_del = session.cmd("dmesg -c")
        for line in messages_del.splitlines():
            logging.debug("[dmesg del] %s" % line)
        if messages_del.find(match_del) == -1:
            raise error.TestFail("kernel didn't detect unplug")

    if params.get("usb_negative_test", "no") != "no":
        # Negative test.
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session = vm.wait_for_login()
        usb_host_device_list = params["usb_host_device_list"].split(",")
        for dev in usb_host_device_list:
            vid, pid = dev.split(":")
            monitor_add = "device_add usb-host,bus=usbtest.0,id=usbhostdev"
            monitor_add += ",vendorid=%s" % vid
            monitor_add += ",productid=%s" % pid
            reply = vm.monitor.cmd(monitor_add)
            if params["usb_reply_msg"] not in reply:
                raise error.TestFail("Could not get expected warning"
                                     " msg in negative test, monitor"
                                     " returns: '%s'" % reply)
        vm.reboot()
        return

    device = params["usb_host_device"]
    (vendorid, productid) = device.split(":")

    # compose strings
    lsusb_cmd = "lsusb -v -d %s" % device
    monitor_add = "device_add usb-host,bus=usbtest.0,id=usbhostdev"
    monitor_add += ",vendorid=%s" % vendorid
    monitor_add += ",productid=%s" % productid
    monitor_del = "device_del usbhostdev"
    match_add = "New USB device found, "
    match_add += "idVendor=%s, idProduct=%s" % (vendorid, productid)
    match_del = "USB disconnect"

    error.context("Check usb device %s on host" % device, logging.info)
    try:
        utils.system(lsusb_cmd)
    except:
        raise error.TestNAError("Device %s not present on host" % device)

    error.context("Log into guest", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    repeat_times = int(params.get("usb_repeat_times", "1"))
    for i in range(repeat_times):
        if params.get("usb_check_isobufs", "no") == "no":
            error.context("Hotplug (iteration %i)" % (i + 1), logging.info)
        else:
            # The value of isobufs could only be in '4, 8, 16'
            isobufs = (2 << (i % 3 + 1))
            monitor_add = "device_add usb-host,bus=usbtest.0,id=usbhostdev"
            monitor_add += ",vendorid=%s" % vendorid
            monitor_add += ",productid=%s" % productid
            monitor_add += ",isobufs=%d" % isobufs
            error.context("Hotplug (iteration %i), with 'isobufs' option"
                          " set to %d" % ((i + 1), isobufs), logging.info)
        usb_dev_hotplug()
        usb_dev_verify()
        usb_dev_unplug()

    session.close()
