import logging
from autotest.client.shared import error
from virttest import env_process, utils_misc, utils_test

try:
    from autotest.client.shared import utils_memory
except ImportError:
    from virttest.staging import utils_memory


@error.context_aware
def run_numa_basic(test, params, env):
    """
    Qemu numa basic test:
    1) Get host numa topological structure
    2) Start a guest and bind it on the cpus of one node
    3) Check the memory status of qemu process. It should mainly use the
       memory in the same node.
    4) Destroy the guest
    5) Repeat step 2 ~ 4 on every node in host

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error.context("Get host numa topological structure", logging.info)
    timeout = float(params.get("login_timeout", 240))
    host_numa_node = utils_misc.NumaInfo()
    node_list = host_numa_node.online_nodes
    for node_id in node_list:
        error.base_context("Bind qemu process to numa node %s" % node_id,
                           logging.info)
        vm = "vm_bind_to_%s" % node_id
        params['qemu_command_prefix'] = "numactl --cpunodebind=%s" % node_id
        utils_memory.drop_caches()
        env_process.preprocess_vm(test, params, env, vm)
        vm = env.get_vm(vm)
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)
        session.close()

        error.context("Check the memory use status of qemu process",
                      logging.info)
        memory_status, _ = utils_test.get_qemu_numa_status(host_numa_node,
                                                           vm.get_pid())
        node_used_most = 0
        memory_sz_used_most = 0
        for index in range(len(node_list)):
            if memory_sz_used_most < memory_status[index]:
                memory_sz_used_most = memory_status[index]
                node_used_most = node_list[index]
            logging.debug("Qemu used %s pages in node"
                          " %s" % (memory_status[index], node_list[index]))
        if node_used_most != node_id:
            raise error.TestFail("Qemu still use memory from other node."
                                 " Expect: %s, used: %s" % (node_id,
                                                            node_used_most))

        error.context("Destroy guest.", logging.info)
        vm.destroy()
