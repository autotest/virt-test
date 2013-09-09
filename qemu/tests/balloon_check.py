import re
import logging
import random
import time
from autotest.client.shared import error
from virttest import qemu_monitor, utils_test, utils_misc


@error.context_aware
def run_balloon_check(test, params, env):
    """
    Check Memory ballooning, use M when compare memory in this script:
    1) Boot a guest with balloon enabled/disabled.
    2) Check whether monitor command 'info balloon' works
    3) Reduce memory to random size between Free memory to max memory size
    4) Run optional test after evicting memory (Optional)
    5) Reset memory value to original memory assigned on qemu (Optional)
    6) Run optional test after enlarging memory (Optional)
    7) Check memory after sub test
    8) Check whether the memory is set up correctly

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def error_report(step, expect_value, monitor_value, guest_value,
                     guest_changed=None, ori_value=None):
        """
        Generate the error report

        :param step: the step of the error happen
        :param expect_value: memory size assign to the vm
        :param monitor_value: memory size report from monitor, this value can
                              be None
        :param guest_value: memory size report from guest, this value can be
                            None
        :param ori_value: memory size in qemu command line
        """
        logging.error("Memory size mismatch %s:\n" % step)
        if guest_changed is not None:
            error_msg = "Wanted to be changed: %s\n" % (ori_value
                                                        - expect_value)
            if monitor_value:
                error_msg += "Changed in monitor: %s\n" % (ori_value
                                                           - monitor_value)
            error_msg += "Changed in guest: %s\n" % guest_changed
        else:
            error_msg = "Assigner to VM: %s\n" % expect_value
            if monitor_value:
                error_msg += "Reported by monitor: %s\n" % monitor_value
            if guest_value:
                error_msg += "Reported by guest OS: %s\n" % guest_value
        logging.error(error_msg)

    def check_ballooned_memory():
        """
        Verify the actual memory reported by monitor command info balloon. If
        the operation failed, increase the failure counter.

        :return: Number of failures occurred during operation.
        """
        try:
            output = vm.monitor.info("balloon")
            ballooned_mem = int(re.findall("\d+", str(output))[0])
            if vm.monitor.protocol == "qmp":
                ballooned_mem *= 1024 ** -2
        except qemu_monitor.MonitorError, e:
            logging.error(e)
            return 0
        return ballooned_mem

    def get_memory_status():
        """
        Get Memory status inside guest. As memory balloon shows different
        results in Windows and Linux guests. So use different method for
        them.

        :return: Number of failures occurred during operation and the memory
                 size.
        """
        try:
            if params["os_type"] == "windows":
            # In Windows guest we get the free memory for memory compare
                memory = session.cmd_output(free_mem_cmd)
                memory = int(re.findall("\d+", memory)[0])
                memory *= 1024 ** -1
            else:
                memory = vm.get_current_memory_size()
        except Exception, e:
            logging.error(e)
            return 0
        return memory

    def memory_check(step, ballooned_mem, ori_mmem, ori_gmem, ratio):
        """
        Check memory status according expect values

        :param step: the check point string
        :param ballooned_mem: ballooned memory in current step
        :param ori_mmem: original memory size get from monitor
        :param ori_gmem: original memory size get from guest
        :param ratio: the ratio that can accept when check results
        """
        error.context("Check memory status %s" % step, logging.info)
        mmem = check_ballooned_memory()
        gmem = get_memory_status()
        if (abs(mmem - ori_mmem) != ballooned_mem
           or (abs(gmem - ori_gmem) < ratio * ballooned_mem)):
            if params["os_type"] == "windows":
                error_report(step, ori_mmem - ballooned_mem, mmem, None,
                             abs(gmem - ori_gmem), ori_mmem)
            else:
                error_report(step, ori_mmem - ballooned_mem, mmem, gmem)
            raise error.TestFail("Balloon test failed %s" % step)

    def balloon_memory(new_mem):
        """
        Baloon memory to new_mem and verifies on both qemu monitor and
        guest OS if change worked.

        :param new_mem: New desired memory.
        """
        error.context("Change VM memory to %s" % new_mem, logging.info)
        compare_mem = new_mem
        if params["monitor_type"] == "qmp":
            new_mem = new_mem * 1024 * 1024
        # This should be replaced by proper monitor method call
        vm.monitor.send_args_cmd("balloon value=%s" % new_mem)
        balloon_timeout = float(params.get("balloon_timeout", 100))
        s = utils_misc.wait_for((lambda: compare_mem
                                 == check_ballooned_memory()),
                                balloon_timeout)
        if s is None:
            raise error.TestFail("Failed to balloon memory to expect"
                                 " value during %ss" % balloon_timeout)

    free_mem_cmd = params["free_mem_cmd"]
    ratio = float(params.get("ratio", 0.5))
    vm = env.get_vm(params["main_vm"])
    error.context("Boot a guest", logging.info)
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    # Upper limit that we can raise the memory
    vm_assigned_mem = int(params["mem"])

    error.context("Check the memory in guest", logging.info)
    boot_mem = vm.get_memory_size()

    error.context("Check whether monitor command 'info balloon' works")
    monitor_boot_mem = check_ballooned_memory()
    if boot_mem != vm_assigned_mem or monitor_boot_mem != vm_assigned_mem:
        error_report("check memory before test", vm_assigned_mem,
                     monitor_boot_mem, boot_mem)
        raise error.TestError("Memory status is in currect after guest boot"
                              " up, abort the test")
    if monitor_boot_mem:
        logging.info("Current VM memory according to ballooner: %s",
                     monitor_boot_mem)

    guest_boot_mem = get_memory_status()

    error.context("Reduce memory to random size between Free memory"
                  "to max memory size", logging.info)
    s, o = session.cmd_status_output(free_mem_cmd)
    if s != 0:
        raise error.TestError("Can not get guest memory information")

    vm_mem_free = int(re.findall('\d+', o)[0]) / 1024

    new_mem = int(random.uniform(vm_assigned_mem - vm_mem_free,
                                 vm_assigned_mem))
    balloon_memory(new_mem)
    ballooned_mem = vm_assigned_mem - new_mem
    memory_check("after evict memory", ballooned_mem,
                 monitor_boot_mem, guest_boot_mem, ratio)

    if (params.get("run_evict_sub_test", "no") == "yes"
            and 'sub_balloon_test_evict' in params):
        error.context("Run optional test after evicting memory", logging.info)
        balloon_test = params['sub_balloon_test_evict']
        utils_test.run_virt_sub_test(test, params, env, sub_type=balloon_test)
        if balloon_test == "shutdown":
            logging.info("Guest shutdown normally after balloon")
            return
        if params.get("session_need_update", "no") == "yes":
            session = vm.wait_for_login(timeout=timeout)
        if params.get("qemu_quit_after_sub_case", "no") == "yes":
            ballooned_mem = 0
        memory_check("after subtest when evicting memory", ballooned_mem,
                     monitor_boot_mem, guest_boot_mem, ratio)

    error.context("Enlarge memory to random size between current memory to"
                  " max memory size", logging.info)
    # This will ensure we won't trigger guest OOM killer while running
    # multiple iterations.
    expect_mem = int(random.uniform(new_mem, vm_assigned_mem))

    balloon_memory(expect_mem)
    ballooned_mem = vm_assigned_mem - expect_mem
    memory_check("after enlarge memory", ballooned_mem,
                 monitor_boot_mem, guest_boot_mem, ratio)

    if (params.get("run_enlarge_sub_test", "no") == "yes"
            and 'sub_balloon_test_enlarge' in params):
        error.context("Run optional test after enlarging memory",
                      logging.info)
        balloon_test = params['sub_balloon_test_enlarge']
        utils_test.run_virt_sub_test(test, params, env, sub_type=balloon_test)
        if balloon_test == "shutdown":
            logging.info("Guest shutdown normally after balloon")
            return
        if params.get("session_need_update", "no") == "yes":
            session = vm.wait_for_login(timeout=timeout)
        if params.get("qemu_quit_after_sub_case", "no") == "yes":
            ballooned_mem = 0
        memory_check("after subtest when enlarging memory", ballooned_mem,
                     monitor_boot_mem, guest_boot_mem, ratio)

    # we should reset the memory to the origin value, so that next
    # iterations can pass when check memory before test
    error.context("Reset the memory to monitor boot memory", logging.info)

    balloon_memory(monitor_boot_mem)
    ballooned_mem = vm_assigned_mem - monitor_boot_mem
    memory_check("after reset memory", ballooned_mem,
                 monitor_boot_mem, guest_boot_mem, ratio)

    session.close()
