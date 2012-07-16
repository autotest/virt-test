import time
import sys
import re

from autotest_lib.client.common_lib import error
from autotest_lib.client.virt import virt_test_utils


def _get_function(func_name):
    """
    Find function with given name in this module.

    @param func_name: function name.

    @return funciton object.
    """
    if not func_name:
        return None

    import types
    items = sys.modules[__name__].__dict__.items()
    for key, value in items:
        if key == func_name and isinstance(value, types.FunctionType):
            return value

    return None


@error.context_aware
def check_usb_device_monitor(test, params, env):
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error.context("Verify USB device in monitor.")
    o = vm.monitor.info("usb")
    if isinstance(o, dict):
        o = o.get("return")
    info_usb_name = params.get("info_usb_name")
    if info_usb_name and (info_usb_name not in o):
        raise error.TestFail("Could not find '%s' device, monitor "
                             "returns: \n%s" % (params.get("product"), o))

@error.context_aware
def check_usb_device(test, params, env):
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    check_usb_device_monitor(test, params, env)

    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    deviceid_str = params.get("deviceid_str")
    vendor_id = params.get("vendor_id")
    product_id = params.get("product_id")
    vendor = params.get("vendor")
    product = params.get("product")

    chk_list = [deviceid_str % (vendor_id, product_id)]
    if vendor:
        chk_list.append(vendor)
    if product:
        chk_list.append(product)

    error.context("Verify USB device in guest.")
    o = session.cmd_output(params.get("chk_usb_info_cmd"))
    for item in chk_list:
        if not re.findall(item, o):
            raise error.TestFail("Could not find item '%s' in guest, "
                                 "Output:\n %s" % (item, o))


@error.context_aware
def run_boot(test, params, env):
    """
    KVM reboot test:
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

    def _check_device(check_func):
        func = _get_function(check_func)
        if not func:
            raise error.TestError("Could not find function %s" % check_func)
        func(test, params, env)


    error.context("Try to log into guest.")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    check_func = params.get("check_func")
    if check_func:
        error.context("Verify device(s) before rebooting.")
        _check_device(check_func)

    if params.get("rh_perf_envsetup_script"):
        virt_test_utils.service_setup(vm, session, test.virtdir)

    if params.get("reboot_method"):
        error.context("Reboot guest.")
        if params["reboot_method"] == "system_reset":
            time.sleep(int(params.get("sleep_before_reset", 10)))
        try:
            # Reboot the VM
            for i in range(int(params.get("reboot_count", 1))):
                session = vm.reboot(session, params["reboot_method"], 0,
                                                                timeout)
        finally:
            session.close()


        if check_func:
            error.context("Verify device(s) after rebooting.")
            _check_device(check_func)
