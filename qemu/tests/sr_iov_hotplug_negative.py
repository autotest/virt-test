import logging
import os
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_test, utils_misc


@error.context_aware
def run_sr_iov_hotplug_negative(test, params, env):
    """
    KVM sr-iov hotplug negatvie test:
    1) Boot up VM.
    2) Try to remove sr-iov device driver module (optional)
    3) Hotplug sr-iov device to VM with negative parameters
    4) Verify that qemu could handle the negative parameters
       check hotplug error message (optional)

    @param test: qemu test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """

    def make_pci_add_cmd(pa_pci_id, pci_addr="auto"):
        pci_add_cmd = ("pci_add pci_addr=%s host host=%s,if=%s" %
                       (pci_addr, pa_pci_id, pci_model))
        if params.get("hotplug_params"):
            assign_param = params.get("hotplug_params").split()
            for param in assign_param:
                value = params.get(param)
                if value:
                    pci_add_cmd += ",%s=%s" % (param, value)
        return pci_add_cmd

    def make_device_add_cmd(pa_pci_id, pci_addr=None):
        device_id = "%s" % pci_model + "-" + utils_misc.generate_random_id()
        pci_add_cmd = ("device_add id=%s,driver=pci-assign,host=%s" %
                       (device_id, pa_pci_id))
        if pci_addr is not None:
            pci_add_cmd += ",addr=%s" % pci_addr
        if params.get("hotplug_params"):
            assign_param = params.get("hotplug_params").split()
            for param in assign_param:
                value = params.get(param)
                if value:
                    pci_add_cmd += ",%s=%s" % (param, value)
        return pci_add_cmd

    neg_msg = params.get("negative_msg")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    rp_times = int(params.get("repeat_times", 1))
    pci_model = params.get("pci_model", "pci-assign")
    pci_addr = params.get("pci_addr")
    modprobe_cmd = params.get("modprobe_cmd")

    if modprobe_cmd:
        # negative test, both guest and host should still work well.
        msg = "Try to remove sr-iov module in host."
        error.context(msg, logging.info)
        utils.system(modprobe_cmd)
    if vm.pci_assignable is not None:
        pa_pci_ids = vm.pci_assignable.request_devs(1)
    # Probe qemu to verify what is the supported syntax for PCI hotplug
    if vm.monitor.protocol == 'qmp':
        cmd_output = vm.monitor.info("commands")
    else:
        cmd_output = vm.monitor.send_args_cmd("help")

    if not cmd_output:
        raise error.TestError("Unknow version of qemu")

    cmd_type = utils_test.find_substring(str(cmd_output), "pci_add",
                                                          "device_add")
    for j in range(rp_times):
        if cmd_type == "pci_add":
            pci_add_cmd = make_pci_add_cmd(pa_pci_ids[0], pci_addr)
        elif cmd_type == "device_add":
            pci_add_cmd = make_device_add_cmd(pa_pci_ids[0], pci_addr)
        try:
            msg = "Adding pci device with command '%s'" % pci_add_cmd
            error.context(msg, logging.info)
            case_fail = False
            add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
            case_fail = True
        except Exception, e:
            if neg_msg:
                msg = "Check negative hotplug error message"
                error.context(msg, logging.info)
                if neg_msg not in str(e):
                    msg = "Could not find '%s' in error msg '%s'" % (
                        neg_msg, e)
                    raise error.TestFail(msg)
            logging.debug("Could not boot up vm, %s" % e)
        if case_fail:
            raise error.TestFail("Did not raise exception during hotpluging")
