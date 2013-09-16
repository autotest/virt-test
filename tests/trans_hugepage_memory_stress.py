import logging
import os
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_test

try:
    from autotest.client.shared import utils_memory
except ImportError:
    from virttest.staging import utils_memory


@error.context_aware
def run_trans_hugepage_memory_stress(test, params, env):
    """
    Run stress as a memory stress in guest for THP testing

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    nr_ah = []

    debugfs_flag = 1
    debugfs_path = os.path.join(test.tmpdir, 'debugfs')
    mem = int(params.get("mem"))
    qemu_mem = int(params.get("qemu_mem", "64"))
    hugetlbfs_path = params.get("hugetlbfs_path", "/proc/sys/vm/nr_hugepages")

    error.context("smoke test setup")
    if not os.path.ismount(debugfs_path):
        if not os.path.isdir(debugfs_path):
            os.makedirs(debugfs_path)
        try:
            utils.system("mount -t debugfs none %s" % debugfs_path)
        except Exception:
            debugfs_flag = 0

    try:
        # Allocated free memory to hugetlbfs
        mem_free = int(utils_memory.read_from_meminfo('MemFree')) / 1024
        mem_swap = int(utils_memory.read_from_meminfo('SwapFree')) / 1024
        hugepage_size = (int(utils_memory.read_from_meminfo('Hugepagesize'))
                         / 1024)
        nr_hugetlbfs = (mem_free + mem_swap - mem - qemu_mem) / hugepage_size
        fd = open(hugetlbfs_path, "w")
        fd.write(str(nr_hugetlbfs))
        fd.close()

        error.context("Memory stress test")

        nr_ah.append(int(utils_memory.read_from_meminfo('AnonHugePages')))
        if nr_ah[0] <= 0:
            raise error.TestFail("VM is not using transparent hugepage")

        # Run stress memory heavy in guest
        memory_stress_test = params['thp_memory_stress']
        utils_test.run_virt_sub_test(test, params, env,
                                     sub_type=memory_stress_test)

        nr_ah.append(int(utils_memory.read_from_meminfo('AnonHugePages')))
        logging.debug("The huge page using for guest is: %s" % nr_ah)

        if nr_ah[1] <= nr_ah[0]:
            logging.warn(
                "VM don't use transparent hugepage while memory stress")

        if debugfs_flag == 1:
            if int(open(hugetlbfs_path, 'r').read()) <= 0:
                raise error.TestFail("KVM doesn't use transparenthugepage")

        logging.info("memory stress test finished")
    finally:
        error.context("all tests cleanup")
        fd = open(hugetlbfs_path, "w")
        fd.write("0")
        fd.close()
        if os.path.ismount(debugfs_path):
            utils.run("umount %s" % debugfs_path)
        if os.path.isdir(debugfs_path):
            os.removedirs(debugfs_path)
