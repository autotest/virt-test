import logging
from autotest.client.shared import error
from virttest import virsh
from virttest.libvirt_xml import vm_xml


def check_domiftune(params):
    """
    Compare inbound and outbound value with guest XML configuration
    and virsh command output.
    :params: the parameter dictionary
    """
    vm_name = params.get("vms")
    vm = params.get("vm")
    interface = params.get("iface_dev")
    options = params.get("options")
    inbound = params.get("inbound", "")
    outbound = params.get("outbound", "")
    inbound_from_cmd_output = None
    outbound_from_cmd_output = None
    domiftune_params = {}
    if vm and vm.is_alive():
        result = virsh.domiftune(vm_name, interface, options=options)
        dicts = {}
        o = result.stdout.strip().split("\n")
        for l in o:
            if l and l.find(':'):
                k, v = l.split(':')
                dicts[k.strip()] = v.strip()

        logging.debug(dicts)
        inbound_from_cmd_output = dicts['inbound.average']
        outbound_from_cmd_output = dicts['outbound.average']

    virt_xml_obj = vm_xml.VMXML(virsh_instance=virsh)

    if options == "config" and vm and vm.is_alive():
        domiftune_params = virt_xml_obj.get_iftune_params(
            vm_name, "--inactive")
    elif vm and not vm.is_alive():
        logging.debug("The guest %s isn't running!", vm_name)
        return True
    else:
        domiftune_params = virt_xml_obj.get_iftune_params(vm_name)

    inbound_from_xml = domiftune_params.get("inbound")
    outbound_from_xml = domiftune_params.get("outbound")

    if vm and vm.is_alive() and options != "config":
        if inbound and inbound != inbound_from_cmd_output:
            logging.error("To expect inbound %s: %s", inbound,
                          inbound_from_cmd_output)
            return False
        if outbound and outbound != outbound_from_cmd_output:
            logging.error("To expect inbound %s: %s", outbound,
                          outbound_from_cmd_output)
            return False
        if inbound and inbound_from_xml and inbound != inbound_from_xml:
            logging.error("To expect outbound %s: %s", inbound,
                          inbound_from_xml)
            return False
        if outbound and outbound_from_xml and outbound != outbound_from_xml:
            logging.error("To expect outbound %s: %s", outbound,
                          outbound_from_xml)
            return False

    return True


def get_domiftune_parameter(params):
    """
    Get the domiftune parameters
    :params: the parameter dictionary
    """
    vm_name = params.get("vms")
    options = params.get("options")
    interface = params.get("iface_dev")

    result = virsh.domiftune(vm_name, interface, options=options)
    status = result.exit_status

    # Check status_error
    status_error = params.get("status_error", "no")

    if status_error == "yes":
        if status:
            logging.info("It's an expected error: %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value", status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            logging.info(result.stdout)


def set_domiftune_parameter(params):
    """
    Set the domiftune parameters
    :params: the parameter dictionary
    """
    vm_name = params.get("vms")
    inbound = params.get("inbound")
    outbound = params.get("outbound")
    options = params.get("options", None)
    interface = params.get("iface_dev")

    result = virsh.domiftune(vm_name, interface, options, inbound, outbound)
    status = result.exit_status

    # Check status_error
    status_error = params.get("status_error", "no")

    if status_error == "yes":
        if status:
            logging.info("It's an expected error: %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value", status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            if check_domiftune(params):
                logging.info(result.stdout)
            else:
                error.TestFail("The 'inbound' or/and 'outbound' are"
                               " inconsistent with domiftune XML"
                               " and/or virsh command output")


def run(test, params, env):
    """
    Test domiftune tuning

    1) Positive testing
       1.1) get the current domiftune parameters for a running guest
       1.2) set the current domiftune parameters for a running guest
    2) Negative testing
       2.1) get domiftune parameters
       2.2) set domiftune parameters
    """

    # Run test case
    vm_name = params.get("vms")
    vm = env.get_vm(vm_name)
    status_error = params.get("status_error", "no")
    start_vm = params.get("start_vm", "yes")
    change_parameters = params.get("change_parameters", "no")
    interface = []

    if vm and vm.is_alive():
        virt_xml_obj = vm_xml.VMXML(virsh_instance=virsh)
        interface = virt_xml_obj.get_iface_dev(vm_name)

    test_dict = dict(params)
    test_dict['vm'] = vm
    if interface:
        test_dict['iface_dev'] = interface[0]

    if start_vm == "no" and vm and vm.is_alive():
        vm.destroy()

    # positive and negative testing #########

    if status_error == "no":
        if change_parameters == "no":
            get_domiftune_parameter(test_dict)
        else:
            set_domiftune_parameter(test_dict)

    if status_error == "yes":
        if change_parameters == "no":
            get_domiftune_parameter(test_dict)
        else:
            set_domiftune_parameter(test_dict)
