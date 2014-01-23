import logging
import re
from autotest.client.shared import error
from virttest import libvirt_vm, virsh, utils_net
from virttest.libvirt_xml import vm_xml


def set_options(iface_type=None, iface_source=None,
                iface_mac=None, suffix="", operation_type="attach"):
    """
    Set attach-detach-interface options.
    """
    options = ""
    if iface_type is not None:
        options += " --type '%s'" % iface_type
    if iface_source is not None and operation_type == "attach":
        options += " --source '%s'" % iface_source
    if iface_mac is not None:
        options += " --mac '%s'" % iface_mac
    if suffix:
        options += " %s" % suffix
    return options


def check_dumpxml_iface(vm_name, checked_mac, checked_type=None,
                        checked_source=None):
    """
    Check interfaces in vm's XML file to get matched one.

    :return: a tuple with a status and an output
    """
    iface_features = vm_xml.VMXML.get_iface_by_mac(vm_name, checked_mac)
    if iface_features is not None:
        if checked_type is not None:
            iface_type = iface_features['type']
            if iface_type != checked_type:
                return (1, ("Interface type(%s) doesn't match %s."
                            % (checked_type, iface_type)))
        if checked_source is not None:
            iface_source = iface_features['source']
            if iface_source != checked_source:
                return (1, ("Interface source(%s) doesn't match %s."
                            % (checked_source, iface_source)))
    else:
        return (1, "Can not find interface with mac(%s) in xml." % checked_mac)
    return (0, "")


def login_to_check(vm, checked_mac):
    """
    Login to vm to get matched interface according its mac address.
    """
    try:
        session = vm.wait_for_login()
    except Exception, detail:  # Do not care Exception's type
        return (1, "Can not login to vm:%s" % detail)
    status, output = session.cmd_status_output("ip -4 -o link list")
    if status != 0:
        return (1, "Login to check failed.")
    else:
        if not re.search(checked_mac, output):
            return (1, ("Can not find interface with mac in vm:%s"
                        % output))
    return (0, "")


def run(test, params, env):
    """
    Test virsh {at|de}tach-interface command.

    1) Prepare test environment and its parameters
    2) Attach the required interface
    3) According test type(only attach or both attach and detach):
       a.Go on to test detach(if attaching is correct)
       b.Return GOOD or raise TestFail(if attaching is wrong)
    4) Check if attached interface is correct:
       a.Try to catch it in vm's XML file
       b.Try to catch it in vm
    5) Detach the attached interface
    6) Check result
    """

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    # Test parameters
    uri = libvirt_vm.normalize_connect_uri(params.get("connect_uri",
                                                      "default"))
    vm_ref = params.get("at_detach_iface_vm_ref", "domname")
    options_suffix = params.get("at_detach_iface_options_suffix", "")
    status_error = "yes" == params.get("status_error", "no")
    start_vm = params.get("start_vm")
    # Should attach must be pass for detach test.
    correct_attach = "yes" == params.get("correct_attach", "no")

    # Interface specific attributes.
    iface_type = params.get("at_detach_iface_type", "network")
    iface_source = params.get("at_detach_iface_source", "default")
    iface_mac = params.get("at_detach_iface_mac", "created")
    virsh_dargs = {'ignore_status': True, 'uri': uri}

    # Get a bridge name for test if iface_type is bridge.
    # If there is no bridge other than virbr0, raise TestNAError
    if iface_type == "bridge":
        host_bridge = utils_net.Bridge()
        bridge_list = host_bridge.list_br()
        try:
            bridge_list.remove("virbr0")
        except AttributeError:
            pass  # If no virbr0, just pass is ok
        logging.debug("Useful bridges:%s", bridge_list)
        # just choosing one bridge on host.
        if len(bridge_list):
            iface_source = bridge_list[0]
        else:
            raise error.TestNAError("No useful bridge on host "
                                    "other than 'virbr0'.")

    dom_uuid = vm.get_uuid()
    dom_id = vm.get_id()

    # To confirm vm's state
    if start_vm == "no" and vm.is_alive():
        vm.destroy()

    # Test both detach and attach, So collect info
    # both of them for result check.
    # When something wrong with interface, set it to 1
    fail_flag = 0
    result_info = []

    # Set attach-interface domain
    if vm_ref == "domname":
        vm_ref = vm_name
    elif vm_ref == "domid":
        vm_ref = dom_id
    elif vm_ref == "domuuid":
        vm_ref = dom_uuid
    elif vm_ref == "hexdomid" and dom_id is not None:
        vm_ref = hex(int(dom_id))

    # Get a mac address if iface_mac is 'created'.
    if iface_mac == "created" or correct_attach:
        iface_mac = utils_net.generate_mac_address_simple()

    # Set attach-interface options and Start attach-interface test
    if correct_attach:
        options = set_options("network", "default", iface_mac, "", "attach")
        attach_result = virsh.attach_interface(vm_name, options,
                                               **virsh_dargs)
    else:
        options = set_options(iface_type, iface_source, iface_mac,
                              options_suffix, "attach")
        attach_result = virsh.attach_interface(vm_ref, options, **virsh_dargs)
    attach_status = attach_result.exit_status
    logging.debug(attach_result)

    # If attach interface failed.
    if attach_status:
        if not status_error:
            fail_flag = 1
            result_info.append("Attach Failed: %s" % attach_result)
        elif status_error:
            # Here we just use it to exit, do not mean test failed
            fail_flag = 1
    # If attach interface succeeded.
    else:
        if status_error and not correct_attach:
            fail_flag = 1
            result_info.append("Attach Success with wrong command.")

    if fail_flag and start_vm == "yes":
        vm.destroy()
        if len(result_info):
            raise error.TestFail(result_info)
        else:
            # Exit because it is error_test for attach-interface.
            return

    # Check dumpxml file whether the interface is added successfully.
    status, ret = check_dumpxml_iface(
        vm_name, iface_mac, iface_type, iface_source)
    if status:
        fail_flag = 1
        result_info.append(ret)

    # Login to domain to check new interface.
    if not vm.is_alive():
        vm.start()
    elif vm.state() == "paused":
        vm.resume()

    status, ret = login_to_check(vm, iface_mac)
    if status:
        fail_flag = 1
        result_info.append(ret)

    # Set detach-interface options
    options = set_options(iface_type, None, iface_mac,
                          options_suffix, "detach")

    # Start detach-interface test
    detach_result = virsh.detach_interface(vm_ref, options, **virsh_dargs)
    detach_status = detach_result.exit_status

    logging.debug(detach_result)

    # Clean up.
    if check_dumpxml_iface(vm_name, iface_mac) is not None:
        cleanup_options = "--type %s --mac %s" % (iface_type, iface_mac)
        virsh.detach_interface(vm_ref, cleanup_options, **virsh_dargs)

    # Shutdown vm to be afraid of cleaning up failed
    if vm.is_alive():
        vm.destroy()

    # Check results.
    if status_error:
        if detach_status == 0:
            raise error.TestFail("Detach Success with wrong command.")
    else:
        if detach_status != 0:
            raise error.TestFail("Detach Failed.")
        else:
            if fail_flag:
                raise error.TestFail("Attach-Detach Success but "
                                     "something wrong with its "
                                     "functional use:%s" % result_info)
