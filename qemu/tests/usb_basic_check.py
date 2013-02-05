import time, re, logging
from autotest.client.shared import error


def check_usb_device(test, params, env):
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    o = vm.monitor.info("usb")
    if isinstance(o, dict):
        o = o.get("return")
    info_usb_name = params.get("info_usb_name")
    if info_usb_name and (info_usb_name not in o):
        raise error.TestFail("Could not find '%s' device, monitor "
                             "returns: \n%s" % (params.get("product"), o))

    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    chk_list = ["%s:%s" % (params.get("vendor_id"), params.get("product_id"))]
    if params.get("vendor"):
        chk_list.append(params.get("vendor"))
    if params.get("product"):
        chk_list.append(params.get("product"))

    o = session.cmd("lsusb -v")
    for item in chk_list:
        if not re.findall(item, o):
            raise error.TestFail("Could not find item '%s' in guest, "
                                 "'lsusb -v' output:\n %s" % (item, o))


@error.context_aware
def run_usb_basic_check(test, params, env):
    """
    KVM usb_basic_check test:
    1) Log into a guest
    2) Verify device(s) work well in guest (optional)
    3) Send a reboot command or a system_reset monitor command (optional)
    4) Wait until the guest is up again
    5) Log into the guest to verify it's up again
    6) Verify device(s) again after guest reboot (optional)

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """

    def _check_dev():
        try:
            check_usb_device(test, params, env)
        except Exception:
            session.close()
            raise

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    error.context("Try to log into guest.", logging.info)
    session = vm.wait_for_login(timeout=timeout)

    error.context("Verify device(s) before rebooting.")
    _check_dev()

    if params.get("reboot_method"):
        error.context("Reboot guest.")
        if params["reboot_method"] == "system_reset":
            time.sleep(int(params.get("sleep_before_reset", 10)))
        session = vm.reboot(session, params["reboot_method"], 0, timeout)

        error.context("Verify device(s) after rebooting.")
        _check_dev()

    session.close()
