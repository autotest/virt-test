import logging
from autotest.client.shared import utils, error
from virttest import virsh, virt_vm
from virttest.libvirt_xml import vm_xml


def run(test, params, env):
    """
    Test command: virsh setmaxmem.

    1) Prepare vm environment.
    2) Handle params
    3) Run test command and get vm started then get maxmem.
    4) Recover environment.
    5) Check result.
    TODO: support more options:--live,--config,--current.
    """

    def vmxml_max_mem(vm_name):
        vmxml = vm_xml.VMXML.new_from_dumpxml(vm_name)
        return int(vmxml.max_mem)

    def make_domref(domarg, vm_ref, domid, vm_name, domuuid):
        # Specify domain as argument or parameter
        if domarg == "yes":
            dom_darg_key = "domainarg"
        else:
            dom_darg_key = "domain"

        # How to reference domain
        if vm_ref == "domid":
            dom_darg_value = domid
        elif vm_ref == "domname":
            dom_darg_value = vm_name
        elif vm_ref == "domuuid":
            dom_darg_value = domuuid
        elif vm_ref == "none":
            dom_darg_value = None
        elif vm_ref == "emptystring":
            dom_darg_value = '""'
        else:  # stick in value directly
            dom_darg_value = vm_ref

        return {dom_darg_key: dom_darg_value}

    def make_sizeref(sizearg, mem_ref, original_mem):
        if sizearg == "yes":
            size_darg_key = "sizearg"
        else:
            size_darg_key = "size"

        if mem_ref == "halfless":
            size_darg_value = "%d" % (original_mem / 2)
        elif mem_ref == "halfmore":
            size_darg_value = "%d" % int(original_mem * 1.5)
        elif mem_ref == "same":
            size_darg_value = "%d" % original_mem
        elif mem_ref == "emptystring":
            size_darg_value = '""'
        elif mem_ref == "zero":
            size_darg_value = "0"
        elif mem_ref == "toosmall":
            size_darg_value = "1024"
        elif mem_ref == "toobig":
            size_darg_value = "1099511627776"  # (KiB) One Petabyte
        elif mem_ref == "none":
            size_darg_value = None
        else:  # stick in value directly
            size_darg_value = mem_ref

        return {size_darg_key: size_darg_value}

    def is_old_libvirt():
        regex = r'\s+\[--size\]\s+'
        return bool(not virsh.has_command_help_match('setmaxmem', regex))

    def is_xen_host():
        check_cmd = "ls /dev/kvm"
        return utils.run(check_cmd, ignore_status=True).exit_status

    def is_in_range(actual, expected, error_percent):
        deviation = 100 - (100 * (float(actual) / float(expected)))
        logging.debug("Deviation: %0.2f%%", float(deviation))
        return float(deviation) <= float(error_percent)

    def print_debug_stats(original_vmxml_mem, original_dominfo_mem,
                          expected_mem, test_vmxml_mem, test_dominfo_mem):
        dbgmsg = ("Original vmxml mem : %d KiB\n"
                  "Original dominfo mem : %d KiB\n"
                  "Expected max mem : %d KiB\n"
                  "Actual vmxml mem   : %d KiB\n"
                  "Actual dominfo mem   : %d KiB\n" % (
                      original_vmxml_mem,
                      original_dominfo_mem,
                      expected_mem,
                      test_vmxml_mem,
                      test_dominfo_mem))
        for dbgline in dbgmsg.splitlines():
            logging.debug(dbgline)

    # MAIN TEST CODE ###
    # Process cartesian parameters
    vm_ref = params.get("setmaxmem_vm_ref", "")
    mem_ref = params.get("setmaxmem_mem_ref", "")
    status_error = "yes" == params.get("status_error", "no")
    flags = params.get("setmaxmem_flags", "")
    domarg = params.get("setmaxmem_domarg", "no")
    sizearg = params.get("setmaxmem_sizearg", "no")
    delta_per = params.get("setmaxmem_delta_per", "10")
    vm_name = params.get("main_vm")

    # Gather environment parameters
    vm = env.get_vm(vm_name)

    # Backup original XML
    original_vmxml = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)

    original_vmxml_mem = vmxml_max_mem(vm_name)

    original_dominfo_mem = vm.get_max_mem()
    domid = vm.get_id()
    domuuid = vm.get_uuid()
    uri = vm.connect_uri

    old_libvirt = is_old_libvirt()
    if old_libvirt:
        logging.info("Running test on older libvirt")
        use_kilobytes = True
    else:
        logging.info("Running test on newer libvirt")
        use_kilobytes = False

    xen_host = is_xen_host()
    if xen_host:
        logging.info("Running on xen host, %s offset is allowed.", delta_per)

    # Argument pattern is complex, build with dargs
    dargs = {'flagstr': flags,
             'use_kilobytes': use_kilobytes,
             'uri': uri, 'ignore_status': True, "debug": True}
    dargs.update(make_domref(domarg, vm_ref, domid, vm_name, domuuid))
    dargs.update(make_sizeref(sizearg, mem_ref, original_dominfo_mem))

    if status_error:
        logging.info("Error Test: Expecting an error to occur!")

    try:
        result = virsh.setmaxmem(**dargs)
        status = result.exit_status

        # Gather status if not running error test
        start_status = 0    # Check can guest be started after maxmem-modified.
        if not status_error:
            if vm.state() == "shut off":
                try:
                    vm.start()
                except virt_vm.VMStartError, detail:
                    start_status = 1
                    logging.error("Start after VM's maxmem modified failed:%s",
                                  detail)

            # Actual results
            test_vmxml_mem = vmxml_max_mem(vm_name)
            test_dominfo_mem = vm.get_max_mem()

            # Expected results for both vmxml and dominfo
            if sizearg == "yes":
                expected_mem = int(dargs["sizearg"])
            else:
                expected_mem = int(dargs["size"])

            print_debug_stats(original_vmxml_mem, original_dominfo_mem,
                              expected_mem, test_vmxml_mem, test_dominfo_mem)

        else:
            if vm.state() == "paused":
                vm.resume()
    finally:
        original_vmxml.sync()

    # Don't care about memory comparison on error test
    if status_error:
        if status is 0:
            raise error.TestFail("Error test did not result in an error.")
    else:
        vmxml_match = (test_vmxml_mem == expected_mem)
        if xen_host:
            dominfo_match = is_in_range(test_dominfo_mem, expected_mem,
                                        delta_per)
        else:
            dominfo_match = (test_dominfo_mem == expected_mem)
        if (status or start_status or not vmxml_match or not dominfo_match):
            msg = "test conditions not met: "
            if status:
                msg += "Non-zero virsh setmaxmem exit code. "
            if not vmxml_match:
                msg += "Max memory in VM's xml is not matched. "
            if not dominfo_match:
                msg += "Max memory in dominfo's output is not matched. "
            if start_status:
                msg += "Start after VM's max mem is modified failed."
            raise error.TestFail(msg)

    logging.info("Test end normally.")
