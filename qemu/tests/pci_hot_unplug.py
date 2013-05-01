import re, logging
from autotest.client.shared import error
from virttest import utils_misc, utils_test

@error.context_aware
def run_pci_hot_unplug(test, params, env):
    """
    Test hot unplug of PCI devices.

    1) Set up sr-iov test environment in host if test sr-iov.
    2) Start VM.
    3) Get the device id that want to unplug.
    4) Delete the device, verify whether could remove the PCI device.

    @param test:   QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env:    Dictionary with test environment.
    """

    def find_pci(device_model):
        output = vm.monitor.info("qtree")
        devices = re.findall(match_string, output)
        return devices

    # Hot delete a pci device
    def pci_del(device, ignore_failure=False):
        def _device_removed():
            after_del = vm.monitor.info("pci")
            return after_del != before_del

        before_del = vm.monitor.info("pci")
        if cmd_type == "pci_add":
            slot_id = int(pci_info[pci_num][1].split(",")[2].split()[1])
            cmd = "pci_del pci_addr=%s" % hex(slot_id)
            vm.monitor.send_args_cmd(cmd, convert=False)
        elif cmd_type == "device_add":
            cmd = "device_del id=%s" % device
            vm.monitor.send_args_cmd(cmd)

        if (not utils_misc.wait_for(_device_removed, test_timeout, 0, 1)
            and not ignore_failure):
            raise error.TestFail("Failed to hot remove PCI device: %s. "
                                 "Monitor command: %s" %
                                 (pci_model, cmd))


    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    test_timeout = int(params.get("test_timeout", 360))
    # Test if it is nic or block
    pci_num = int(params.get("unplug_pci_num", 1))
    pci_model = params.get("pci_model", "pci-assign")
    # Need udpate match_string if you use a card other than 82576
    match_string = params.get("match_string", "dev: %s, id \"(.*)\"")
    match_string = match_string % pci_model

    # Modprobe the module if specified in config file
    module = params.get("modprobe_module")
    if module:
        error.context("modprobe the module %s" %module, logging.info)
        session.cmd("modprobe %s" % module)

    # Probe qemu to verify what is the supported syntax for PCI hotplug
    if vm.monitor.protocol == 'qmp':
        cmd_output = vm.monitor.info("commands")
    else:
        cmd_output = vm.monitor.send_args_cmd("help")

    cmd_type = utils_test.find_substring(str(cmd_output), "device_add",
                                         "pci_add")
    if not cmd_output:
        raise error.TestError("Unknow version of qemu")

    devices = find_pci(pci_model)
    if devices:
        for device in devices[:pci_num]:
            error.context("Hot unplug device %s" % device, logging.info)
            pci_del(device)
