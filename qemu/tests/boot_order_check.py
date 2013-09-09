import logging
import re
from autotest.client import utils
from virttest import utils_misc
from autotest.client.shared import error


@error.context_aware
def run_boot_order_check(test, params, env):
    """
    KVM Autotest set boot order for multiple NIC and block devices
    1) Boot the vm with deciding bootorder for multiple block and NIC devices
    2) Check the guest boot order, should try to boot guest os
       from the device whose bootindex=1, if this fails, it
       should try device whose bootindex=2, and so on, till
       the guest os succeeds to boot or fails to boot

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    error.context("Boot vm by passing boot order decided", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    vm.pause()

    # Disable nic device, boot fail from nic device except user model
    if params['nettype'] != 'user':
        for nic in vm.virtnet:
            utils.system("ifconfig %s down" % nic.ifname)

    vm.resume()

    timeout = int(params.get("login_timeout", 240))
    bootorder_type = params.get("bootorder_type")
    backspace_char = params.get("backspace_char")
    boot_fail_infos = params.get("boot_fail_infos")
    bootorder = params.get("bootorder")
    nic_addr_filter = params.get("nic_addr_filter")
    output = None
    list_nic_addr = []

    # As device id in the last line of info pci output
    # We need reverse the pci information to get the pci addr which is in the
    # front row.
    pci_info = vm.monitor.info("pci")
    pci_list = str(pci_info).split("\n")
    pci_list.reverse()
    pci_info = " ".join(pci_list)
    for nic in vm.virtnet:
        nic_addr = re.findall(nic_addr_filter % nic.device_id, pci_info)
        bootindex = "0%x" % int(params['bootindex_%s' % nic.nic_name])
        list_nic_addr.append((nic_addr, bootindex[-2]))

    list_nic_addr.sort(cmp=lambda x, y: cmp(x[1], y[1]))

    boot_fail_infos = boot_fail_infos % (list_nic_addr[0][0],
                                         list_nic_addr[1][0],
                                         list_nic_addr[2][0])

    error.context("Check the guest boot result", logging.info)
    if bootorder_type == "type2":
        session_serial = vm.wait_for_serial_login(timeout=timeout)
        output = vm.serial_console.get_output()
        session_serial.close()
    else:
        f = lambda: re.search("No bootable device.",
                              vm.serial_console.get_output())
        utils_misc.wait_for(f, timeout, 1)

        output = vm.serial_console.get_output()

    # find and replace some ascii characters to non-ascii char,
    # like as: '\b' (backspace)
    if backspace_char:
        data = re.sub(r".%s" % backspace_char, "", output)
    else:
        data = output
    result = re.findall(boot_fail_infos, data, re.S | re.M | re.I)

    if not result:
        raise error.TestFail("Got a wrong boot order, "
                             "Excepted order: '%s'" % bootorder)
