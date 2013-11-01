import logging
import os
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_misc, funcatexit, utils_test, data_dir
from tests import autotest_control

try:
    from virttest.staging import utils_memory
except ImportError:
    from autotest.client.shared import utils_memory


def max_mem_map_node(host_numa_node, qemu_pid):
    """
    Find the numa node which qemu process memory maps to it the most.

    :param numa_node_info: Host numa node information
    :type numa_node_info: NumaInfo object
    :param qemu_pid: process id of qemu
    :type numa_node_info: string
    :return: The node id and how many pages are mapped to it
    :rtype: tuple
    """
    node_list = host_numa_node.online_nodes
    memory_status, _ = utils_test.qemu.get_numa_status(host_numa_node, qemu_pid)
    node_map_most = 0
    memory_sz_map_most = 0
    for index in range(len(node_list)):
        if memory_sz_map_most < memory_status[index]:
            memory_sz_map_most = memory_status[index]
            node_map_most = node_list[index]
    return (node_map_most, memory_sz_map_most)


@error.context_aware
def run_numa_stress(test, params, env):
    """
    Qemu numa stress test:
    1) Boot up a guest and find the node it used
    2) Try to allocate memory in that node
    3) Run memory heavy stress inside guest
    4) Check the memory use status of qemu process
    5) Repeat step 2 ~ 4 several times


    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    host_numa_node = utils_misc.NumaInfo()
    if len(host_numa_node.online_nodes) < 2:
        raise error.TestNAError("Host only has one NUMA node, "
                                "skipping test...")

    timeout = float(params.get("login_timeout", 240))
    test_count = int(params.get("test_count", 4))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    qemu_pid = vm.get_pid()

    if test_count < len(host_numa_node.online_nodes):
        test_count = len(host_numa_node.online_nodes)

    tmpfs_size = 0
    for node in host_numa_node.nodes:
        node_mem = int(host_numa_node.read_from_node_meminfo(node, "MemTotal"))
        if tmpfs_size < node_mem:
            tmpfs_size = node_mem
    tmpfs_path = params.get("tmpfs_path", "tmpfs_numa_test")
    tmpfs_path = utils_misc.get_path(data_dir.get_tmp_dir(), tmpfs_path)
    tmpfs_write_speed = int(params.get("tmpfs_write_speed", 10240))
    dd_timeout = tmpfs_size / tmpfs_write_speed * 1.5
    mount_fs_size = "size=%dK" % tmpfs_size
    memory_file = utils_misc.get_path(tmpfs_path, "test")
    dd_cmd = "dd if=/dev/urandom of=%s bs=1k count=%s" % (memory_file,
                                                          tmpfs_size)

    if not os.path.isdir(tmpfs_path):
        os.mkdir(tmpfs_path)

    numa_node_malloc = -1
    most_used_node, memory_used = utils_test.max_mem_map_node(host_numa_node,
                                                              qemu_pid)

    for test_round in range(test_count):
        if utils_memory.freememtotal() < tmpfs_size:
            raise error.TestError("Don't have enough memory to execute this "
                                  "test after %s round" % test_round)
        error.context("Executing stress test round: %s" % test_round,
                      logging.info)
        numa_node_malloc = most_used_node
        numa_dd_cmd = "numactl -m %s %s" % (numa_node_malloc, dd_cmd)
        error.context("Try to allocate memory in node %s" % numa_node_malloc,
                      logging.info)
        try:
            utils_misc.mount("none", tmpfs_path, "tmpfs", perm=mount_fs_size)
            funcatexit.register(env, params.get("type"), utils_misc.umount,
                                "none", tmpfs_path, "tmpfs")
            utils.system(numa_dd_cmd, timeout=dd_timeout)
        except Exception, error_msg:
            if "No space" in str(error_msg):
                pass
            else:
                raise error.TestFail("Can not allocate memory in node %s."
                                     " Error message:%s" % (numa_node_malloc,
                                                            str(error_msg)))
        error.context("Run memory heavy stress in guest", logging.info)
        autotest_control.run_autotest_control(test, params, env)
        error.context("Get the qemu process memory use status", logging.info)
        node_after, memory_after = utils_test.max_mem_map_node(host_numa_node,
                                                               qemu_pid)
        if node_after == most_used_node and memory_after >= memory_used:
            raise error.TestFail("Memory still stick in "
                                 "node %s" % numa_node_malloc)
        else:
            most_used_node = node_after
            memory_used = memory_after
        utils_misc.umount("none", tmpfs_path, "tmpfs")
        funcatexit.unregister(env, params.get("type"), utils_misc.umount,
                              "none", tmpfs_path, "tmpfs")
        session.cmd("sync; echo 3 > /proc/sys/vm/drop_caches")
        utils_memory.drop_caches()

    session.close()
