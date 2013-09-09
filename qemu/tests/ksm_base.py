import logging
import time
import random
import os
import commands
import re
from autotest.client.shared import error
from virttest import aexpect, utils_test, data_dir


@error.context_aware
def run_ksm_base(test, params, env):
    """
    Test how KSM (Kernel Shared Memory) act when more than physical memory is
    used. In second part we also test how KVM handles a situation when the host
    runs out of memory (it is expected to pause the guest system, wait until
    some process returns memory and bring the guest back to life)

    @param test: QEMU test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    def _start_allocator(vm, session, timeout):
        """
        Execute guest script and wait until it is initialized.

        @param vm: VM object.
        @param session: Remote session to a VM object.
        @param timeout: Timeout that will be used to verify if guest script
                started properly.
        """
        logging.debug("Starting guest script on guest %s", vm.name)
        session.sendline("python /tmp/ksm_overcommit_guest.py")
        try:
            _ = session.read_until_last_line_matches(["PASS:", "FAIL:"],
                                                     timeout)
        except aexpect.ExpectProcessTerminatedError, exc:
            raise error.TestFail("Command guest script on vm '%s' failed: %s" %
                                 (vm.name, str(exc)))

    def _execute_allocator(command, vm, session, timeout):
        """
        Execute a given command on guest script main loop, indicating the vm
        the command was executed on.

        @param command: Command that will be executed.
        @param vm: VM object.
        @param session: Remote session to VM object.
        @param timeout: Timeout used to verify expected output.

        @return: Tuple (match index, data)
        """
        logging.debug("Executing '%s' on guest script loop, vm: %s, timeout: "
                      "%s", command, vm.name, timeout)
        session.sendline(command)
        try:
            (match, data) = session.read_until_last_line_matches(
                ["PASS:", "FAIL:"],
                timeout)
        except aexpect.ExpectProcessTerminatedError, exc:
            e_str = ("Failed to execute command '%s' on guest script, "
                     "vm '%s': %s" % (command, vm.name, str(exc)))
            raise error.TestFail(e_str)
        return (match, data)

    timeout = float(params.get("login_timeout", 240))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    # Prepare work in guest
    error.context("Turn off swap in guest", logging.info)
    session.cmd_status_output("swapoff -a")
    script_file_path = os.path.join(data_dir.get_root_dir(),
                                    "shared/scripts/ksm_overcommit_guest.py")
    vm.copy_files_to(script_file_path, "/tmp")
    test_type = params.get("test_type")
    shared_mem = params.get("shared_mem")
    get_free_mem_cmd = params.get("get_free_mem_cmd",
                                  "grep MemFree /proc/meminfo")
    free_mem = vm.get_memory_size(get_free_mem_cmd)
    # Keep test from OOM killer
    if free_mem < shared_mem:
        shared_mem = free_mem
    fill_timeout = int(shared_mem) / 10
    query_cmd = params.get("query_cmd")
    query_regex = params.get("query_regex")
    random_bits = params.get("random_bits")
    seed = random.randint(0, 255)

    query_cmd = re.sub("QEMU_PID", str(vm.process.get_pid()), query_cmd)

    _, sharing_page_0 = commands.getstatusoutput(query_cmd)
    if query_regex:
        sharing_page_0 = re.findall(query_regex, sharing_page_0)[0]

    error.context("Start to allocate pages inside guest", logging.info)
    _start_allocator(vm, session, 60)
    error.context("Turn off swap in guest", logging.info)
    mem_fill = "mem = MemFill(%s, 0, %s)" % (shared_mem, seed)
    _execute_allocator(mem_fill, vm, session, fill_timeout)
    cmd = "mem.value_fill()"
    _execute_allocator(cmd, vm, session, fill_timeout)
    time.sleep(120)

    _, sharing_page_1 = commands.getstatusoutput(query_cmd)
    if query_regex:
        sharing_page_1 = re.findall(query_regex, sharing_page_1)[0]

    error.context("Start to fill memory with random value in guest",
                  logging.info)
    split = params.get("split")
    if split == "yes":
        if test_type == "negative":
            cmd = "mem.static_random_fill(%s)" % random_bits
        else:
            cmd = "mem.static_random_fill()"
    _execute_allocator(cmd, vm, session, fill_timeout)
    time.sleep(120)

    _, sharing_page_2 = commands.getstatusoutput(query_cmd)
    if query_regex:
        sharing_page_2 = re.findall(query_regex, sharing_page_2)[0]

    sharing_page = [sharing_page_0, sharing_page_1, sharing_page_2]
    for i in sharing_page:
        if re.findall("[A-Za-z]", i):
            data = i[0:-1]
            unit = i[-1]
            index = sharing_page.index(i)
            if unit == "g":
                sharing_page[index] = utils_test.aton(data) * 1024
            else:
                sharing_page[index] = utils_test.aton(data)

    fail_type = 0
    if test_type == "disable":
        if int(sharing_page[0]) != 0 and int(sharing_page[1]) != 0:
            fail_type += 1
    else:
        if int(sharing_page[0]) >= int(sharing_page[1]):
            fail_type += 2
        if int(sharing_page[1]) <= int(sharing_page[2]):
            fail_type += 4

    fail = ["Sharing page increased abnormally",
            "Sharing page didn't increase", "Sharing page didn't split"]

    if fail_type != 0:
        turns = 0
        while (fail_type > 0):
            if fail_type % 2 == 1:
                logging.error(fail[turns])
            fail_type = fail_type / 2
            turns += 1
        raise error.TestFail("KSM test failed: %s %s %s" %
                             (sharing_page_0, sharing_page_1,
                              sharing_page_2))
    session.close()
