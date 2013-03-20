import re, logging, random, time
from autotest.client.shared import error
from autotest.client.virt import kvm_monitor, utils_test


@error.context_aware
def run_balloon_check(test, params, env):
    """
    Check Memory ballooning:
    1) Boot a guest with balloon enabled/disabled.
    2) Check whether monitor command 'info balloon' works
    3) Reduce memory to random size between Free memory to max memory size
    4) Run optional test after evicting memory (Optional)
    5) Reset memory value to original memory assigned on qemu (Optional)
    6) Run optional test after enlarging memory (Optional)
    7) Check memory after sub test
    8) Check whether the memory is set up correctly

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    def check_ballooned_memory():
        """
        Verify the actual memory reported by monitor command info balloon. If
        the operation failed, increase the failure counter.

        @return: Number of failures occurred during operation.
        """
        fail = 0
        try:
            output = vm.monitor.info("balloon")
        except kvm_monitor.MonitorError, e:
            logging.error(e)
            fail += 1
            return 0, fail
        return int(re.findall("\d+", str(output))[0]), fail

    def balloon_memory(new_mem, offset):
        """
        Baloon memory to new_mem and verifies on both qemu monitor and
        guest OS if change worked.

        @param new_mem: New desired memory.
        @return: Number of failures occurred during operation.
        """
        if params.get("os_type") == "windows":
           free_mem = session.cmd_output(free_mem_cmd)
           free_mem = re.findall("\d+", free_mem)[0]
           if params.get("monitor_type") == "qmp":
               free_mem = int(free_mem) * 1024
           else:
               free_mem = int(free_mem) / 1024

        fail = 0
        error.context("Check ballooned memory in monitor before balloon")
        old_mem, cfail = check_ballooned_memory()
        fail += cfail
        if params.get("monitor_type") == "qmp":
            new_mem = new_mem * 1024 * 1024
        error.context("Change VM memory to %s" % new_mem, logging.info)
        # This should be replaced by proper monitor method call
        vm.monitor.send_args_cmd("balloon value=%s" % new_mem)
        time.sleep(20)

        error.context("Check ballooned memory in monitor after balloon")
        ballooned_mem, cfail = check_ballooned_memory()
        fail += cfail
        # Verify whether the VM machine reports the correct new memory
        if ballooned_mem != new_mem:
            logging.error("Memory ballooning failed while changing memory "
                          "to %s", new_mem)
            fail += 1

        # Verify whether the guest OS reports the correct new memory
        ratio = float(params.get("ratio", "0.5"))
        guest_check_fail = False
        error.context("Check ballooned memory in guest")
        if params.get("os_type") == "windows":
            cur_free_mem = session.cmd_output(free_mem_cmd)
            cur_free_mem = re.findall("\d+", cur_free_mem)[0]
            if params.get("monitor_type") == "qmp":
                cur_free_mem = int(cur_free_mem) * 1024
            else:
                cur_free_mem = int(cur_free_mem) / 1024
            ballooned_mem_guest = abs(free_mem - cur_free_mem)
            ballooned_mem = abs(old_mem - new_mem)
            if (abs(ballooned_mem_guest - ballooned_mem) >
                ratio * ballooned_mem):
                fail += 1
                guest_check_fail = True
                error_msg = "Try to balloon %s RAM, " % ballooned_mem
                error_msg += "but guest OS reports RAM "
                error_msg += "changed %s" % ballooned_mem_guest
        else:
            current_mem_guest = vm.get_current_memory_size()
            current_mem_guest = current_mem_guest + offset
            if params.get("monitor_type") == "qmp":
                current_mem_guest = current_mem_guest * 1024 * 1024
            if current_mem_guest != new_mem:
                error_msg = "Guest OS reports %s of RAM, " % current_mem_guest
                error_msg += "but new ballooned RAM is %s" % new_mem
                fail += 1
                guest_check_fail = True
        if guest_check_fail:
            logging.error(error_msg)

        return fail

    fail = 0
    free_mem_cmd = params.get("free_mem_cmd")
    vm = env.get_vm(params["main_vm"])
    error.context("Boot a guest", logging.info)
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    # Upper limit that we can raise the memory
    vm_assigned_mem = int(params.get("mem"))

    error.context("Check the memory in guest", logging.info)
    boot_mem = vm.get_memory_size()
    if boot_mem != vm_assigned_mem:
        logging.error("Memory size mismatch:")
        logging.error("    Assigned to VM: %s", vm_assigned_mem)
        logging.error("    Reported by guest OS at boot: %s", boot_mem)
        fail += 1

    error.context("Check whether monitor command 'info balloon' works")
    current_vm_mem, cfail = check_ballooned_memory()
    if cfail:
        fail += cfail
    if current_vm_mem:
        logging.info("Current VM memory according to ballooner: %s",
                     current_vm_mem)

    error.context("Get the offset of memory reported by guest system")
    guest_memory = vm.get_current_memory_size()
    offset = vm_assigned_mem - guest_memory

    error.context("Reduce memory to random size between Free memory"
                  "to max memory size", logging.info)
    s, o = session.cmd_status_output(free_mem_cmd)
    if s != 0:
        raise error.TestError("Can not get guest memory information")

    vm_mem_free = int(re.findall('\d+', o)[0]) / 1024

    new_mem = int(random.uniform(vm_assigned_mem - vm_mem_free,
                                 vm_assigned_mem))
    fail += balloon_memory(new_mem, offset)

    error.context("Run optional test after evicting memory", logging.info)
    if params.has_key('sub_balloon_test_evict'):
        balloon_test = params['sub_balloon_test_evict']
        utils_test.run_virt_sub_test(test, params, env, sub_type=balloon_test)
        if balloon_test == "shutdown" :
            logging.info("Guest shutdown normally after balloon")
            return

    error.context("Reset memory value to original memory assigned on qemu")
    # This will ensure we won't trigger guest OOM killer while running
    # multiple iterations.
    fail += balloon_memory(vm_assigned_mem, offset)

    error.context("Run optional test after enlarging memory", logging.info)
    if params.has_key('sub_balloon_test_enlarge'):
        balloon_test = params['sub_balloon_test_enlarge']
        utils_test.run_virt_sub_test(test, params, env, sub_type=balloon_test)
        if balloon_test == "shutdown" :
            logging.info("Guest shutdown normally after balloon")
            return

    error.context("Check memory after sub test", logging.info)
    boot_mem = vm.get_memory_size()
    if boot_mem != vm_assigned_mem:
        fail += 1

    error.context("Check whether the memory is set up correctly")
    current_vm_mem, cfail = check_ballooned_memory()
    if params.get("monitor_type") == "qmp":
        current_vm_mem = current_vm_mem / 1024 / 1024
    if current_vm_mem != vm_assigned_mem:
        fail += 1
    logging.error("Memory size after tests:")
    logging.error("    Assigned to VM: %s", vm_assigned_mem)
    logging.error("    Reported by guest OS: %s", boot_mem)
    logging.error("    Reported by monitor: %s", current_vm_mem)

    # Close stablished session
    session.close()
    error.context("Check whether any failures happen during the whole test")
    if fail != 0:
        raise error.TestFail("Memory ballooning test failed,"
                             " totally %d steps failed." % fail)
