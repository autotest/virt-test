import logging, re, uuid
from autotest.client.shared import error
from autotest.client import utils

@error.context_aware
def run_usb_hotplug(test, params, env):
    """
    Test usb hotplug

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """

    device = params.get("usb_type_testdev")
    product = params.get("product")

    # compose strings
    monitor_add  = "device_add %s" % device
    monitor_add += ",bus=usbtest.0,id=usbplugdev"
    monitor_del  = "device_del usbplugdev"

    error.context("Log into guest", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    session.cmd_status("dmesg -c")

    error.context("Plugin usb device", logging.info)
    reply = vm.monitor.cmd(monitor_add)
    if reply.find("Parameter 'driver' expects a driver name") != -1:
        raise error.TestNAError("usb device %s not available" % device)

    session.cmd_status("sleep 1")
    session.cmd_status("udevadm settle")
    messages_add = session.cmd("dmesg -c")
    for line in messages_add.splitlines():
        logging.debug("[dmesg add] %s" % line)
    if messages_add.find("Product: %s" % product) == -1:
        raise error.TestFail("kernel didn't detect plugin")

    error.context("Unplug usb device", logging.info)
    vm.monitor.cmd(monitor_del)
    session.cmd_status("sleep 1")
    messages_del = session.cmd("dmesg -c")
    for line in messages_del.splitlines():
        logging.debug("[dmesg del] %s" % line)
    if messages_del.find("USB disconnect") == -1:
        raise error.TestFail("kernel didn't detect unplug")

    session.close()
