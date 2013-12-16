import re
import logging
import random
from autotest.client.shared import error
from virttest import qemu_monitor, utils_test, utils_misc


class BallooningTest(object):

    """
    Provide basic functions for memory ballooning test cases
    """

    def __init__(self, test, params, env):
        self.test = test
        self.params = params
        self.env = env
        self.free_mem_cmd = params["free_mem_cmd"]
        self.ratio = float(params.get("ratio", 0.5))

        self.vm = env.get_vm(params["main_vm"])
        self.vm.verify_alive()
        timeout = int(params.get("login_timeout", 360))
        self.session = self.vm.wait_for_login(timeout=timeout)

        self.ori_mem = int(params['mem'])
        self.current_mmem = self.get_ballooned_memory()
        if self.current_mmem != self.ori_mem:
            self.balloon_memory(self.ori_mem)
        self.ori_gmem = self.get_memory_status()
        self.current_gmem = self.ori_gmem
        self.current_mmem = self.ori_mem

        self.test_round = 0

    def get_ballooned_memory(self):
        """
        Get the size of memory from monitor

        :return: the size of memory
        :rtype: int
        """
        try:
            output = self.vm.monitor.info("balloon")
            ballooned_mem = int(re.findall(r"\d+", str(output))[0])
            if self.vm.monitor.protocol == "qmp":
                ballooned_mem *= 1024 ** -2
        except qemu_monitor.MonitorError, emsg:
            logging.error(emsg)
            return 0
        return ballooned_mem

    @error.context_aware
    def memory_check(self, step, ballooned_mem):
        """
        Check memory status according expect values

        :param step: the check point string
        :type step: string
        :param ballooned_mem: ballooned memory in current step
        :type ballooned_mem: int
        :return: memory size get from monitor and guest
        :rtype: tuple
        """
        error.context("Check memory status %s" % step, logging.info)
        mmem = self.get_ballooned_memory()
        gmem = self.get_memory_status()
        if (abs(mmem - self.ori_mem) != ballooned_mem
                or (abs(gmem - self.ori_gmem) < self.ratio * ballooned_mem)):
            self.error_report(step, self.ori_mem - ballooned_mem, mmem, gmem)
            raise error.TestFail("Balloon test failed %s" % step)
        return (mmem, gmem)

    @error.context_aware
    def balloon_memory(self, new_mem):
        """
        Baloon memory to new_mem and verifies on both qemu monitor and
        guest OS if change worked.

        :param new_mem: New desired memory.
        :type new_mem: int
        """
        error.context("Change VM memory to %s" % new_mem, logging.info)
        compare_mem = new_mem
        if self.params["monitor_type"] == "qmp":
            new_mem = new_mem * 1024 * 1024
        # This should be replaced by proper monitor method call
        self.vm.monitor.send_args_cmd("balloon value=%s" % new_mem)
        balloon_timeout = float(self.params.get("balloon_timeout", 100))
        status = utils_misc.wait_for((lambda: compare_mem
                                      == self.get_ballooned_memory()),
                                     balloon_timeout)
        if status is None:
            raise error.TestFail("Failed to balloon memory to expect"
                                 " value during %ss" % balloon_timeout)

    def run_balloon_sub_test(self, test, params, env, test_tag):
        """
        Run subtest after ballooned memory. Set up the related parameters
        according to the subtest.

        :param test: QEMU test object
        :type test: object
        :param params: Dictionary with the test parameters
        :type param: dict
        :param env: Dictionary with test environment.
        :type env: dict
        :return: if qemu-kvm process quit after test. There are three status
                 for this variable. -1 means the process will not quit. 0
                 means the process will quit but already restart in sub test.
                 1 means the process quit after sub test.
        :rtype: int
        """
        utils_test.run_virt_sub_test(test, params, env,
                                     sub_type=test_tag)
        qemu_quit_after_test = -1
        if "shutdown" in test_tag:
            logging.info("Guest shutdown normally after balloon")
            qemu_quit_after_test = 1
        if params.get("session_need_update", "no") == "yes":
            timeout = int(self.params.get("login_timeout", 360))
            self.session = self.vm.wait_for_login(timeout=timeout)
        if params.get("qemu_quit_after_sub_case", "no") == "yes":
            self.current_mmem = self.ori_mem
            self.current_gmem = self.ori_gmem
            qemu_quit_after_test = 0
        return qemu_quit_after_test

    def get_memory_boundary(self, balloon_type='evict'):
        """
        Get the legal memory boundary for balloon operation.

        :param balloon_type: evict or enlarge
        :type balloon_type: string
        :return: min and max size of the memory
        :rtype: tuple
        """
        max_size = self.ori_mem
        if balloon_type == 'enlarge':
            min_size = self.current_mmem
        else:
            vm_total = self.get_memory_status()
            status, output = self.session.cmd_status_output(self.free_mem_cmd)
            if status != 0:
                raise error.TestError("Can not get guest memory information")

            vm_mem_free = int(re.findall(r'\d+', output)[0]) / 1024
            min_size = vm_total - vm_mem_free
        return min_size, max_size

    @error.context_aware
    def run_ballooning_test(self, expect_mem, tag):
        """
        Run a loop of ballooning test

        :param expect_mem: memory will be setted in test
        :type expect_mem: int
        :param tag: test tag to get related params
        :type tag: string
        :return: If test should quit after test
        :rtype: bool
        """
        if self.test_round < 1:
            self.memory_check("before ballooning test", 0)

        params_tag = self.params.object_params(tag)
        balloon_type = params_tag.get("balloon_type")
        min_size, max_size = self.get_memory_boundary(balloon_type)

        if expect_mem < min_size or expect_mem > max_size:
            raise error.TestError("Memory is set to an illegal size %s. It "
                                  "should between %s and %s" % (expect_mem,
                                                                min_size,
                                                                max_size))

        self.balloon_memory(expect_mem)
        self.test_round += 1
        if expect_mem > self.current_mmem:
            balloon_type = "enlarge"
        elif expect_mem < self.current_mmem:
            balloon_type = "evict"
        else:
            balloon_type = "command test"

        mmem, gmem = self.memory_check("after %s memory" % balloon_type,
                                       self.ori_mem - expect_mem)
        self.current_mmem = mmem
        self.current_gmem = gmem
        if (params_tag.get("run_sub_test_after_balloon", "no") == "yes"
                and params_tag.get('sub_test_after_balloon')):
            should_quit = self.run_balloon_sub_test(self.test, params_tag,
                                                    self.env,
                                                    params_tag['sub_test_after_balloon'])
            if should_quit == 1:
                return True
            elif should_quit == 0:
                expect_mem = self.ori_mem

            mmem, gmem = self.memory_check("after subtest",
                                           self.ori_mem - expect_mem)
            self.current_mmem = mmem
            self.current_gmem = gmem
        return False

    def reset_memory(self):
        """
        Reset memory to original value
        """
        if self.vm.is_alive():
            self.balloon_memory(self.ori_mem)

    def error_report(self, step, expect_value, monitor_value, guest_value):
        """
        Generate the error report

        :param step: the step of the error happen
        :param expect_value: memory size assign to the vm
        :param monitor_value: memory size report from monitor, this value can
                              be None
        :param guest_value: memory size report from guest, this value can be
                            None
        """
        pass

    def get_memory_status(self):
        """
        Get Memory status inside guest.
        """
        pass


class BallooningTestWin(BallooningTest):

    """
    Windows memory ballooning test
    """

    def error_report(self, step, expect_value, monitor_value, guest_value):
        """
        Generate the error report

        :param step: the step of the error happen
        :param expect_value: memory size assign to the vm
        :param monitor_value: memory size report from monitor, this value can
                              be None
        :param guest_value: memory size report from guest, this value can be
                            None
        """
        logging.error("Memory size mismatch %s:\n" % step)
        error_msg = "Wanted to be changed: %s\n" % (self.ori_mem
                                                    - expect_value)
        if monitor_value:
            error_msg += "Changed in monitor: %s\n" % (self.ori_mem
                                                       - monitor_value)
        error_msg += "Changed in guest: %s\n" % (guest_value - self.ori_gmem)
        logging.error(error_msg)

    def get_memory_status(self):
        """
        Get Memory status inside guest.

        :return: the free memory size inside guest.
        :rtype: int
        """
        free_mem_cmd = self.params['free_mem_cmd']
        try:
            # In Windows guest we get the free memory for memory compare
            memory = self.session.cmd_output(free_mem_cmd)
            memory = int(re.findall(r"\d+", memory)[0])
            memory *= 1024 ** -1
        except Exception, emsg:
            logging.error(emsg)
            return 0
        return memory


class BallooningTestLinux(BallooningTest):

    """
    Linux memory ballooning test
    """

    def error_report(self, step, expect_value, monitor_value, guest_value):
        """
        Generate the error report

        @param step: the step of the error happen
        @param expect_value: memory size assign to the vm
        @param monitor_value: memory size report from monitor, this value can
                              be None
        @param guest_value: memory size report from guest, this value can be
                            None
        """
        logging.error("Memory size mismatch %s:\n" % step)
        error_msg = "Assigner to VM: %s\n" % expect_value
        if monitor_value:
            error_msg += "Reported by monitor: %s\n" % monitor_value
        if guest_value:
            error_msg += "Reported by guest OS: %s\n" % guest_value
        logging.error(error_msg)

    def get_memory_status(self):
        """
        Get Memory status inside guest.

        :return: the size of total memory in guest
        :rtype: int
        """
        try:
            memory = self.vm.get_current_memory_size()
        except Exception, emsg:
            logging.error(emsg)
            return 0
        return memory


@error.context_aware
def run_balloon_check(test, params, env):
    """
    Check Memory ballooning, use M when compare memory in this script:
    1) Boot a guest with balloon enabled.
    2) Balloon guest memory to given value and run sub test(Optional)
    3) Repeat step 2 following the cfg files.
    8) Reset memory back to the original value

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    if params['os_type'] == 'windows':
        balloon_test = BallooningTestWin(test, params, env)
    else:
        balloon_test = BallooningTestLinux(test, params, env)

    for tag in params.objects('test_tags'):
        error.context("Running %s test" % tag, logging.info)
        params_tag = params.object_params(tag)
        if params_tag.get('expect_memory'):
            expect_mem = int(params_tag.get('expect_memory'))
        elif params_tag.get('expect_memory_ratio'):
            expect_mem = int(balloon_test.ori_mem *
                             float(params_tag.get('expect_memory_ratio')))
        else:
            balloon_type = params_tag['balloon_type']
            min_sz, max_sz = balloon_test.get_memory_boundary(balloon_type)
            expect_mem = int(random.uniform(min_sz, max_sz))

        quit_after_test = balloon_test.run_ballooning_test(expect_mem, tag)
        if quit_after_test:
            return

    balloon_test.reset_memory()
