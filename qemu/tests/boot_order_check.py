import logging, re
from autotest.client import utils
from autotest.client.virt import utils_misc
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

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment
    """

    def get_nic_device_addr(device_id, index, list):
        """
        Get nic addr from info pci, and change to hex num.
        Add the (nic_addr, bootindex) into list
        """

        for i, v in enumerate(pci_list, start=0):
            if re.search(device_id, v):
                patt = re.compile(r'%s' % nic_addr_filter)
                nic_addr = patt.findall(pci_list[i-6])
                if nic_addr:
                    nic_addr_num = int(nic_addr[0])
                    # if the num <16, prepend '0' to the num
                    # e.g. '3' -> '03'
                    if nic_addr_num < 16:
                        num = "0%s" % hex(nic_addr_num)[2:]
                        list.append((num, index))
                    else:
                        num = hex(nic_addr_num)[2:]
                        list.append((num, index))


    error.context("Boot vm by passing boot order decided", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    vm.pause()

    # Disable nic device, boot fail from nic device
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
    pci_info = vm.monitor.info("pci")
    pci_list = str(pci_info).split("\n")

    for i in xrange(1, 4):
       get_nic_device_addr(params.get("device_id_nic%s" % str(i)),
                           params.get("bootindex_nic%s" % str(i)),
                           list_nic_addr)

    list_nic_addr.sort(cmp = lambda x,y: cmp(x[1], y[1]))

    boot_fail_infos = boot_fail_infos % (list_nic_addr[0][0],
                                         list_nic_addr[1][0],
                                         list_nic_addr[2][0])

    error.context("Check the guest boot result", logging.info)
    if bootorder_type == "type2":
        session_serail = vm.wait_for_serial_login(timeout=timeout)
        output = vm.serial_console.get_output()
        session_serail.close()
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
    result = re.findall(boot_fail_infos, data, re.S|re.M|re.I)

    if not result:
        raise error.TestFail("Got a wrong boot order, "
                             "Excepted order: '%s'" % bootorder)
