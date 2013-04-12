import re, logging, time
from autotest.client.shared import error
from virttest import utils_misc


@error.context_aware
def run_seabios(test, params, env):
    """
    KVM Seabios test:
    1) Start guest with sga bios
    2) Check the sgb bios messages
    3) Restart the vm, verify it's reset
    4) Display and check the boot menu order
    5) Start guest from the specified boot entry
    6) Log into the guest to verify it's up

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    error.context("Start guest with sga bios")
    vm = env.get_vm(params["main_vm"])
    # Since the seabios is displayed in the beginning of guest boot,
    # booting guest here so that we can check all of sgabios/seabios
    # info, especially the correct time of sending boot menu key.
    vm.create()

    timeout = float(params.get("login_timeout", 240))
    boot_menu_key = params.get("boot_menu_key", 'f12')
    restart_key = params.get("restart_key", "ctrl-alt-delete")
    boot_menu_hint = params.get("boot_menu_hint")
    boot_device = params.get("boot_device", "")
    sgabios_info = params.get("sgabios_info")
    info_list = sgabios_info.split(';')

    # Sleep 5 sec for waiting get sgabios infos.
    time.sleep(5)
    error.context("Display and check the SGABIOS info", logging.info)

    data = vm.serial_console.get_output()
    for i in info_list:
        if i not in data:
            raise error.TestFail("Cound not get sgabios message: '%s'" % i)

    error.context("Display and check the boot menu order", logging.info)

    f = lambda: re.search(boot_menu_hint, vm.serial_console.get_output())
    if not (boot_menu_hint and utils_misc.wait_for(f, timeout, 1)):
        raise error.TestFail("Could not get boot menu message.")

    error.context("Restart vm and check it's ok", logging.info)
    vm.send_key(restart_key)

    time.sleep(5)
    output = vm.serial_console.get_output()
    infos = re.findall("Press Ctrl-B to configure", output, re.M)
    if len(infos) != 2:
        raise error.TestFail("Could not restart the vm")

    # Send boot menu key in monitor.
    vm.send_key(boot_menu_key)

    _ = vm.serial_console.get_output()
    boot_list = re.findall("^\d+\. (.*)\s", _, re.M)

    if not boot_list:
        raise error.TestFail("Could not get boot entries list.")

    logging.info("Got boot menu entries: '%s'", boot_list)
    for i, v in enumerate(boot_list, start=1):
        if re.search(boot_device, v, re.I):
            error.context("Start guest from boot entry '%s'" % v,
                          logging.info)
            vm.send_key(str(i))
            break
    else:
        raise error.TestFail("Could not get any boot entry match "
                             "pattern '%s'" % boot_device)

    error.context("Log into the guest to verify it's up")
    session = vm.wait_for_login(timeout=timeout)
    session.close()
