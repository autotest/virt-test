import logging
import time
import re
from autotest.client.shared import error


@error.context_aware
def run_usb_hotplug(test, params, env):
    """
    Test usb hotplug

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    @error.context_aware
    def usb_dev_hotplug():
        error.context("Plugin usb device", logging.info)
        session.cmd(clear_guest_log_cmd)
        reply = vm.monitor.cmd(monitor_add)
        if params.get("usb_negative_test") == "yes":
            if params["usb_reply_msg"] not in reply:
                raise error.TestFail("Could not get expected warning"
                                     " msg in negative test, monitor"
                                     " returns: '%s'" % reply)
            return

        monitor_pattern = "Parameter 'driver' expects a driver name"
        if reply.find(monitor_pattern) != -1:
            raise error.TestNAError("usb device %s not available" % device)

    @error.context_aware
    def usb_dev_verify():
        error.context("Verify usb device is pluged on guest", logging.info)
        time.sleep(sleep_time)
        session.cmd(udev_refresh_cmd)
        messages_add = session.cmd(query_syslog_cmd)
        for line in messages_add.splitlines():
            logging.debug("[Guest add] %s" % line)
        if not re.search(match_add, messages_add, re.I):
            raise error.TestFail("Guest didn't detect plugin")

    @error.context_aware
    def usb_dev_unplug():
        error.context("Unplug usb device", logging.info)
        vm.monitor.cmd(monitor_del)
        time.sleep(sleep_time)
        messages_del = session.cmd(query_syslog_cmd)
        for line in messages_del.splitlines():
            logging.debug("[Guest del] %s" % line)
        if messages_del.find(match_del) == -1:
            raise error.TestFail("Guest didn't detect unplug")

    device = params.object_params("testdev")["usb_type"]
    vendor_id = params["vendor_id"]
    product_id = params["product_id"]

    # compose strings
    monitor_add = "device_add %s" % device
    monitor_add += ",bus=usbtest.0,id=usbplugdev"
    monitor_del = "device_del usbplugdev"
    match_add = params.get("usb_match_add", "idVendor=%s, idProduct=%s")
    match_add = match_add % (vendor_id, product_id)
    match_del = params.get("usb_match_del", "USB disconnect")
    clear_guest_log_cmd = params.get("usb_clear_guest_log_cmd", "dmesg -c")
    query_syslog_cmd = params.get("usb_query_syslog_cmd", "dmesg -c")
    sleep_time = float(params["usb_sleep_time"])
    udev_refresh_cmd = params.get("usb_udev_refresh_cmd", "udevadm settle")

    error.context("Log into guest", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    repeat_times = int(params["usb_repeat_times"])
    for i in range(repeat_times):
        error.context("Hotplug (iteration %i)" % (i + 1), logging.info)
        usb_dev_hotplug()
        usb_dev_verify()
        usb_dev_unplug()

    session.close()
