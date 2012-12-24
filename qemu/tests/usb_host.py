import logging, re, uuid
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

    device = params.get("usb_host_device")
    if device == None:
        raise error.TestNAError("not configured (use 'usb_host_device = "
                                "<vendor>:<product>')")
    (vendorid,productid) = device.split(":")

    # compose strings
    lsusb_cmd    = "lsusb -v -d %s" % device;
    monitor_add  = "device_add usb-host,bus=usbtest.0,id=usbhostdev"
    monitor_add += ",vendorid=%s" % vendorid
    monitor_add += ",productid=%s" % productid
    monitor_del  = "device_del usbhostdev"
    match_add    = "New USB device found, "
    match_add   += "idVendor=%s, idProduct=%s" % (vendorid,productid)
    match_del    = "USB disconnect"

    error.context("Check usb device %s on host" % device, logging.info)
    try:
        utils.system(lsusb_cmd)
    except:
        raise error.TestNAError("Device %s not present on host" % device)

    error.context("Log into guest", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    session.cmd_status("dmesg -c")

    error.context("Plugin usb device", logging.info)
    vm.monitor.cmd(monitor_add)
    session.cmd_status("sleep 1")
    session.cmd_status("udevadm settle")
    messages_add = session.cmd("dmesg -c")
    for line in messages_add.splitlines():
        logging.debug("[dmesg add] %s" % line)
    if messages_add.find(match_add) == -1:
        raise error.TestFail("kernel didn't detect plugin")

    error.context("Check usb device %s in guest" % device, logging.info)
    session.cmd(lsusb_cmd)

    error.context("Unplug usb device", logging.info)
    vm.monitor.cmd(monitor_del)
    session.cmd_status("sleep 1")
    messages_del = session.cmd("dmesg -c")
    for line in messages_del.splitlines():
        logging.debug("[dmesg del] %s" % line)
    if messages_del.find(match_del) == -1:
        raise error.TestFail("kernel didn't detect unplug")

    session.close()
