import re
import logging
from autotest.client.shared import error
from virttest import virsh


def run(test, params, env):
    """
    Test command: virsh dumpxml.
    This version contains a common option(--inactive) only.
    TODO: to support some options like --security-info, --update-cpu

    1) Prepare parameters.
    2) Set options of virsh dumpxml.
    3) Prepare environment: vm_state, etc.
    4) Run dumpxml command.
    5) Recover environment.
    6) Check result.
    """
    def is_dumpxml_of_running_vm(dumpxml, domid):
        """
        To check whether the dumpxml is got during vm is running.
        (Verify the domid in dumpxml)

        :param dumpxml: the output of virsh dumpxml.
        :param domid: the id of vm
        """
        match_string = "<domain.*id='%s'/>" % domid
        if re.search(dumpxml, match_string):
            return True
        return False

    # Prepare parameters
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    vm_ref = params.get("dumpxml_vm_ref", "domname")
    options_ref = params.get("dumpxml_options_ref", "")
    options_suffix = params.get("dumpxml_options_suffix", "")
    vm_state = params.get("dumpxml_vm_state", "running")
    status_error = params.get("status_error", "no")
    domuuid = vm.get_uuid()
    domid = vm.get_id()

    # Prepare vm state for test
    if vm_state == "shutoff" and vm.is_alive():
        vm.destroy()  # Confirm vm is shutoff

    if vm_ref == "domname":
        vm_ref = vm_name
    elif vm_ref == "domid":
        vm_ref = domid
    elif vm_ref == "domuuid":
        vm_ref = domuuid
    elif vm_ref == "hex_id":
        if domid == "-":
            vm_ref = domid
        else:
            vm_ref = hex(int(domid))

    if options_suffix:
        options_ref = "%s %s" % (options_ref, options_suffix)

    # Run command
    logging.info("Command:virsh dumpxml %s", vm_ref)
    try:
        cmd_result = virsh.dumpxml(vm_ref, extra=options_ref)
        output = cmd_result.stdout.strip()
        if cmd_result.exit_status:
            raise error.TestFail("dumpxml %s failed.\n"
                                 "Detail: %s.\n" % (vm_ref, cmd_result))
        status = 0
    except error.TestFail, detail:
        status = 1
        output = detail
    logging.debug("virsh dumpxml result:\n%s", output)

    # Recover vm state
    if vm_state == "paused":
        vm.resume()

    # Check result
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command.")
    elif status_error == "no":
        if status:
            raise error.TestFail("Run failed with right command.")
        else:
            # validate dumpxml file
            # Since validate LibvirtXML functions are been working by cevich,
            # reserving it here. :)
            if options_ref == "--inactive":
                if is_dumpxml_of_running_vm(output, domid):
                    raise error.TestFail("Got dumpxml for active vm "
                                         "with --inactive option!")
            else:
                if (vm_state == "shutoff"
                        and is_dumpxml_of_running_vm(output, domid)):
                    raise error.TestFail("Got dumpxml for active vm "
                                         "when vm is shutoff.")
