import re
import logging
from autotest.client.shared import error
from virttest import virsh, utils_libvirtd


def run_virsh_list(test, params, env):
    """
    Test command: virsh list.

    1) Filt parameters according libvirtd's version
    2) Prepare domain's exist state:transient,managed-save.
    3) Prepare libvirt's status.
    4) Execute list command.
    5) Result check.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    options_ref = params.get("list_options_ref", "")
    list_ref = params.get("list_type_ref", "")
    vm_ref = params.get("vm_ref", "")

    # Some parameters are not supported on old libvirt, skip them.
    help_info = virsh.command("help list").stdout.strip()
    if vm_ref and not re.search(vm_ref, help_info):
        raise error.TestNAError("This version do not support vm type:%s"
                                % vm_ref)
    if list_ref and not re.search(list_ref, help_info):
        raise error.TestNAError("This version do not support list type:%s"
                                % list_ref)

    status_error = params.get("status_error", "no")
    addition_status_error = params.get("addition_status_error", "no")
    domuuid = vm.get_uuid().strip()
    # If a transient domain is destroyed, it will disappear.
    if vm_ref == "transient" and options_ref == "inactive":
        logging.info("Set addition_status_error to yes")
        logging.info(
            "because transient domain will disappear after destroyed.")
        addition_status_error = "yes"

    if vm_ref == "transient":
        tmp_xml = vm.backup_xml()
        vm.undefine()
    elif vm_ref == "managed-save":
        virsh.managedsave(vm_name, ignore_status=True, print_info=True)

    # Prepare libvirtd status
    libvirtd = params.get("libvirtd", "on")
    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    # run test case
    if list_ref == "--uuid":
        result_expected = domuuid
        logging.info("%s's uuid is: %s", vm_name, domuuid)
    else:
        result_expected = vm_name
        logging.info("domain's name is: %s", vm_name)

    if options_ref == "vm_id":
        domid = vm.get_id().strip()
        logging.info("%s's running-id is: %s", vm_name, domid)
        options_ref = "%s %s" % (domid, list_ref)
    elif options_ref == "vm_uuid":
        logging.info("%s's uuid is: %s", vm_name, domuuid)
        options_ref = "%s %s" % (domuuid, list_ref)
    elif options_ref == "inactive":
        vm.destroy()
        options_ref = "--inactive %s" % list_ref
    elif options_ref == "vm_name":
        options_ref = "%s %s" % (vm_name, list_ref)
    elif options_ref == "all":
        options_ref = "--all %s" % list_ref
    elif options_ref == "":
        options_ref = "%s" % list_ref

    if vm_ref:
        options_ref = "%s --%s" % (options_ref, vm_ref)
    result = virsh.dom_list(
        options_ref, ignore_status=True, print_info=True)
    status = result.exit_status
    output = result.stdout.strip()

    # Recover libvirtd service status
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # Recover of domain
    if vm_ref == "transient":
        vm.define(tmp_xml)
    elif vm_ref == "managed-save":
        # Recover saved guest.
        virsh.managedsave_remove(vm_name, ignore_status=True, print_info=True)

    # Check result
    status_error = (status_error == "no") and (addition_status_error == "no")
    if vm_ref == "managed-save":
        saved_output = re.search(vm_name + "\s+saved", output)
        if saved_output:
            output = saved_output.group(0)
        else:
            output = ""

    if not status_error:
        if status == 0 and re.search(result_expected, output):
            raise error.TestFail("Run successful with wrong command!")
    else:
        if status != 0:
            raise error.TestFail("Run failed with right command.")
        if not re.search(result_expected, output):
            raise error.TestFail("Run successful but result is not expected.")
