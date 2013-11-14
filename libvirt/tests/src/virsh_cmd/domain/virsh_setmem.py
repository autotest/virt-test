import re
import logging
import time
from autotest.client.shared import error
from virttest import virsh, utils_libvirtd


def run(test, params, env):
    """
    Test command: virsh setmem.

    1) Prepare vm environment.
    2) Handle params
    3) Prepare libvirtd status.
    4) Run test command and wait for current memory's stable.
    5) Recover environment.
    4) Check result.
    TODO: support new libvirt with more options.
    """

    def vm_proc_meminfo(session):
        proc_meminfo = session.cmd_output("cat /proc/meminfo")
        # verify format and units are expected
        return int(re.search(r'MemTotal:\s+(\d+)\s+kB', proc_meminfo).group(1))

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
            size_darg_value = "%d" % int(original_mem * 1.5)  # no fraction
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

    def is_in_range(actual, expected, error_percent):
        deviation = 100 - (100 * (float(actual) / float(expected)))
        logging.debug("Deviation: %0.2f%%" % float(deviation))
        return float(deviation) <= float(error_percent)

    def is_old_libvirt():
        regex = r'\s+\[--size\]\s+'
        return bool(not virsh.has_command_help_match('setmem', regex))

    def print_debug_stats(original_inside_mem, original_outside_mem,
                          test_inside_mem, test_outside_mem,
                          expected_mem, delta_percentage):
        dbgmsg = ("Original inside mem  : %d KiB\n"
                  "Expected inside mem  : %d KiB\n"
                  "Actual inside mem    : %d KiB\n"
                  "Inside mem deviation : %0.2f%%\n"
                  "Original outside mem : %d KiB\n"
                  "Expected outside mem : %d KiB\n"
                  "Actual outside mem   : %d KiB\n"
                  "Outside mem deviation: %0.2f%%\n"
                  "Acceptable deviation %0.2f%%" % (
                      original_inside_mem,
                      expected_mem,
                      test_inside_mem,
                      100 -
                      (100 * (float(test_inside_mem) / float(expected_mem))),
                      original_outside_mem,
                      expected_mem,
                      test_outside_mem,
                      100 -
                      (100 * (float(test_outside_mem) / float(expected_mem))),
                      float(delta_percentage)))
        for dbgline in dbgmsg.splitlines():
            logging.debug(dbgline)

    # MAIN TEST CODE ###
    # Process cartesian parameters
    vm_ref = params.get("setmem_vm_ref", "")
    mem_ref = params.get("setmem_mem_ref", "")
    flags = params.get("setmem_flags", "")
    status_error = params.get("status_error", "no")
    old_libvirt_fail = params.get("setmem_old_libvirt_fail", "no")
    quiesce_delay = int(params.get("setmem_quiesce_delay", "1"))
    domarg = params.get("setmem_domarg", "no")
    sizearg = params.get("setmem_sizearg", "no")
    libvirt = params.get("libvirt", "on")
    delta_percentage = float(params.get("setmem_delta_per", "10"))
    start_vm = params.get("start_vm", "yes")
    vm_name = params.get("main_vm")
    paused_after_start_vm = "yes" == params.get("paused_after_start_vm", "no")

    # Gather environment parameters
    vm = env.get_vm(params["main_vm"])
    if start_vm == "yes":
        if paused_after_start_vm:
            vm.resume()
        session = vm.wait_for_login()
        original_inside_mem = vm_proc_meminfo(session)
        session.close()
        if paused_after_start_vm:
            vm.pause()
    else:
        session = None
        # Retrieve known mem value, convert into kilobytes
        original_inside_mem = int(params.get("mem", "1024")) * 1024
    original_outside_mem = vm.get_used_mem()
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

    # Argument pattern is complex, build with dargs
    dargs = {'flagstr': flags,
             'use_kilobytes': use_kilobytes,
             'uri': uri, 'ignore_status': True, "debug": True}
    dargs.update(make_domref(domarg, vm_ref, domid, vm_name, domuuid))
    dargs.update(make_sizeref(sizearg, mem_ref, original_outside_mem))

    # Prepare libvirtd status
    if libvirt == "off":
        utils_libvirtd.libvirtd_stop()
    else:
        if not utils_libvirtd.libvirtd_is_running() and \
           not utils_libvirtd.libvirtd_start():
            raise error.TestFail("Cannot start libvirtd")

    if status_error == "yes" or old_libvirt_fail == "yes":
        logging.info("Error Test: Expecting an error to occur!")

    result = virsh.setmem(**dargs)
    status = result.exit_status

    # Recover libvirtd status
    if libvirt == "off":
        utils_libvirtd.libvirtd_start()

    if status is 0:
        logging.info(
            "Waiting %d seconds for VM memory to settle", quiesce_delay)
        # It takes time for kernel to settle on new memory
        # and current clean pages is not predictable. Therefor,
        # extremely difficult to determine quiescence, so
        # sleep one second per error percent is reasonable option.
        time.sleep(quiesce_delay)

    # Gather stats if not running error test
    if status_error == "no" and old_libvirt_fail == "no":
        if vm.state() == "shut off":
            vm.start()
        # Make sure it's never paused
        vm.resume()
        session = vm.wait_for_login()

        # Actual results
        test_inside_mem = vm_proc_meminfo(session)
        session.close()
        test_outside_mem = vm.get_used_mem()

        # Expected results for both inside and outside
        if sizearg == "yes":
            expected_mem = int(dargs["sizearg"])
        else:
            expected_mem = int(dargs["size"])

        print_debug_stats(original_inside_mem, original_outside_mem,
                          test_inside_mem, test_outside_mem,
                          expected_mem, delta_percentage)

    if status is 0:  # Restore original memory
        restore_status = virsh.setmem(domainarg=vm_name,
                                      sizearg=original_outside_mem,
                                      ignore_status=True).exit_status
        if restore_status is not 0:
            logging.warning("Failed to restore VM's original memory to %s KiB"
                            % original_outside_mem)
    else:
        # virsh setmem failed, no need to restore
        pass

    # Don't care about memory comparison on error test
    if status_error == "no" and old_libvirt_fail == "no":
        outside_in_range = is_in_range(test_outside_mem, expected_mem,
                                       delta_percentage)
        inside_in_range = is_in_range(test_inside_mem, expected_mem,
                                      delta_percentage)
        if status is not 0 or not outside_in_range or not inside_in_range:
            msg = "test conditions not met: "
            if status is not 0:
                msg += "Non-zero virsh setmem exit code. "  # maybe multiple
            if not outside_in_range:                       # errors
                msg += "Outside memory deviated. "
            if not inside_in_range:
                msg += "Inside memory deviated. "
            raise error.TestFail(msg)

        return  # Normal test passed
    elif status_error == "no" and old_libvirt_fail == "yes":
        if status is 0:
            if old_libvirt:
                raise error.TestFail("Error test did not result in an error")
        else:
            if not old_libvirt:
                raise error.TestFail("Newer libvirt failed when it should not")
    else:  # Verify an error test resulted in error
        if status is 0:
            raise error.TestFail("Error test did not result in an error")
