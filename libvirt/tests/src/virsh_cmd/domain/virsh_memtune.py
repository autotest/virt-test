import logging
from autotest.client.shared import error
from virttest import virsh

try:
    from virttest.staging import utils_memory
    from virttest.staging import utils_cgroup
except ImportError:
    from autotest.client.shared import utils_memory
    from autotest.client.shared import utils_cgroup


def run(test, params, env):
    """
    Test the command virsh memtune

    (1) To get the current memtune parameters
    (2) Change the parameter values
    (3) Check the memtune query updated with the values
    (4) Check whether the mounted cgroup path gets the updated value
    (5) Login to guest and use the memory greater that the assigned value
        and check whether it kills the vm.
    (6) TODO:Check more values and robust scenarios.
    """

    def check_limit(path, expected_value, limit_name):
        """
        Matches the expected and actual output
        (1) Match the output of the virsh memtune
        (2) Match the output of the respective cgroup fs value

        :params: path: memory controller path for a domain
        :params: expected_value: the expected limit value
        :params: limit_name: the limit to be checked
                             hard_limit/soft_limit/swap_hard_limit
        :return: True or False based on the checks
        """
        status_value = True
        # Check 1
        actual_value = virsh.memtune_get(domname, limit_name)
        if actual_value == -1:
            raise error.TestFail("the key %s not found in the "
                                 "virsh memtune output" % limit_name)
        if actual_value != int(expected_value):
            status_value = False
            logging.error("%s virsh output:\n\tExpected value:%d"
                          "\n\tActual value: "
                          "%d", limit_name,
                          int(expected_value), int(actual_value))

        # Check 2
        if limit_name == 'hard_limit':
            cg_file_name = '%s/memory.limit_in_bytes' % path
        elif limit_name == 'soft_limit':
            cg_file_name = '%s/memory.soft_limit_in_bytes' % path
        elif limit_name == 'swap_hard_limit':
            cg_file_name = '%s/memory.memsw.limit_in_bytes' % path

        cg_file = None
        try:
            try:
                cg_file = open(cg_file_name)
                output = cg_file.read()
                value = int(output) / 1024
                if int(expected_value) != int(value):
                    status_value = False
                    logging.error("%s cgroup fs:\n\tExpected Value: %d"
                                  "\n\tActual Value: "
                                  "%d", limit_name,
                                  int(expected_value), int(value))
            except IOError:
                status_value = False
                logging.error("Error while reading:\n%s", cg_file_name)
        finally:
            if cg_file is not None:
                cg_file.close()

        return status_value

    # Get the vm name, pid of vm and check for alive
    domname = params.get("main_vm")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    pid = vm.get_pid()
    logging.info("Verify valid cgroup path for VM pid: %s", pid)

    # Resolve the memory cgroup path for a domain
    path = utils_cgroup.resolve_task_cgroup_path(int(pid), "memory")

    # Set the initial memory starting value for test case
    # By default set 1GB less than the total memory
    # In case of total memory is less than 1GB set to 256MB
    # visit subtests.cfg to change these default values
    Memtotal = utils_memory.read_from_meminfo('MemTotal')
    base_mem = params.get("memtune_base_mem")

    if int(Memtotal) < int(base_mem):
        Mem = int(params.get("memtune_min_mem"))
    else:
        Mem = int(Memtotal) - int(base_mem)

    # Initialize error counter
    error_counter = 0

    # Check for memtune command is available in the libvirt version under test
    if not virsh.has_help_command("memtune"):
        raise error.TestNAError(
            "Memtune not available in this libvirt version")

    # Run test case with 100kB increase in memory value for each iteration
    while (Mem < Memtotal):
        if virsh.has_command_help_match("memtune", "hard-limit"):
            hard_mem = Mem - int(params.get("memtune_hard_base_mem"))
            options = " --hard-limit %d --live" % hard_mem
            virsh.memtune_set(domname, options)
            if not check_limit(path, hard_mem, "hard_limit"):
                error_counter += 1
        else:
            raise error.TestNAError("harlimit option not available in memtune "
                                    "cmd in this libvirt version")

        if virsh.has_command_help_match("memtune", "soft-limit"):
            soft_mem = Mem - int(params.get("memtune_soft_base_mem"))
            options = " --soft-limit %d --live" % soft_mem
            virsh.memtune_set(domname, options)
            if not check_limit(path, soft_mem, "soft_limit"):
                error_counter += 1
        else:
            raise error.TestNAError("softlimit option not available in memtune "
                                    "cmd in this libvirt version")

        if virsh.has_command_help_match("memtune", "swap-hard-limit"):
            swaphard = Mem
            options = " --swap-hard-limit %d --live" % swaphard
            virsh.memtune_set(domname, options)
            if not check_limit(path, swaphard, "swap_hard_limit"):
                error_counter += 1
        else:
            raise error.TestNAError("swaplimit option not available in memtune "
                                    "cmd in this libvirt version")
        Mem += int(params.get("memtune_hard_base_mem"))

    # Raise error based on error_counter
    if error_counter > 0:
        raise error.TestFail(
            "Test failed, consult the previous error messages")
