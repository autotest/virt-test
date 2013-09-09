import re
import logging
from autotest.client.shared import error
from virttest import utils_misc


@error.context_aware
def run_seabios(test, params, env):
    """
    KVM Seabios test:
    1) Start guest with sga bios
    2) Check the sgb bios messages(optional)
    3) Restart the vm, verify it's reset(optional)
    4) Display and check the boot menu order
    5) Start guest from the specified boot entry
    6) Log into the guest to verify it's up

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error.context("Start guest with sga bios")
    vm = env.get_vm(params["main_vm"])
    # Since the seabios is displayed in the beginning of guest boot,
    # booting guest here so that we can check all of sgabios/seabios
    # info, especially the correct time of sending boot menu key.
    vm.create()

    timeout = float(params.get("login_timeout", 240))
    boot_menu_key = params.get("boot_menu_key", 'f12')
    restart_key = params.get("restart_key")
    boot_menu_hint = params.get("boot_menu_hint")
    boot_device = params.get("boot_device", "")
    sgabios_info = params.get("sgabios_info")

    seabios_session = vm.logsessions['seabios']

    if sgabios_info:
        info_list = sgabios_info.split(';')
        error.context("Display and check the SGABIOS info", logging.info)
        info_check = lambda: (len(info_list) ==
                              len([x for x in info_list
                                   if x in vm.serial_console.get_output()]))

        if not utils_misc.wait_for(info_check, timeout, 1):
            raise error.TestFail("Cound not get sgabios message. The output"
                                 " is %s" % vm.serial_console.get_output())

    if restart_key:
        error.context("Restart vm and check it's ok", logging.info)
        boot_menu = lambda: re.search(boot_menu_hint,
                                      seabios_session.get_output())
        if not (boot_menu_hint and utils_misc.wait_for(boot_menu, timeout, 1)):
            raise error.TestFail("Could not get boot menu message.")

        seabios_text = seabios_session.get_output()
        headline = seabios_text.split("\n")[0] + "\n"
        headline_count = seabios_text.count(headline)

        vm.send_key(restart_key)
        reboot_check = lambda: (seabios_session.get_output().count(headline)
                                > headline_count)

        if not utils_misc.wait_for(reboot_check, timeout, 1):
            raise error.TestFail("Could not restart the vm")

    error.context("Display and check the boot menu order", logging.info)
    boot_menu = lambda: re.search(boot_menu_hint,
                                  seabios_session.get_output())
    if not (boot_menu_hint and utils_misc.wait_for(boot_menu, timeout, 1)):
        raise error.TestFail("Could not get boot menu message.")

    # Send boot menu key in monitor.
    vm.send_key(boot_menu_key)

    get_list = lambda: re.findall("^\d+\. (.*)\s",
                                  seabios_session.get_output(), re.M)
    boot_list = utils_misc.wait_for(get_list, timeout, 1)

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
