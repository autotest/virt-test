import logging
from autotest.client.shared import error

from virttest import env_process, utils_misc, utils_test

try:
    from autotest.client.shared import utils_memory
except ImportError:
    from virttest.staging import utils_memory

@error.context_aware
def run_numa_consistency(test, params, env):
    """
    Qemu numa consistency test:
    1) Get host numa topological structure
    2) Start a guest with the same node as the host, each node has one cpu
    3) Get the vcpu thread used cpu id in host and the cpu belongs which node
    4) Allocate memory inside guest and bind the allocate process to one of
       its vcpu.
    5) The memory used in host should increase in the same node if the vcpu
       thread is not switch to other node.
    6) Repeat step 3~5 for each vcpu thread of the guest.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    def get_vcpu_used_node(numa_node_info, vcpu_thread):
        cpu_used_host = utils_misc.get_thread_cpu(vcpu_thread)[0]
        node_used_host = ([_ for _ in node_list if cpu_used_host
                           in numa_node_info.nodes[_].cpus][0])
        return node_used_host

    error.context("Get host numa topological structure", logging.info)
    timeout = float(params.get("login_timeout", 240))
    host_numa_node = utils_misc.NumaInfo()
    node_list = host_numa_node.online_nodes
    if len(node_list) < 2:
        raise error.TestNAError("This host only has one NUMA node, "
                                "skipping test...")
    node_list.sort()
    params['smp'] = len(node_list)
    params['vcpu_cores'] = 1
    params['vcpu_threads'] = 1
    params['vcpu_sockets'] = params['smp']
    params['guest_numa_nodes'] = ""
    for node_id in range(len(node_list)):
        params['guest_numa_nodes'] += " node%d" % node_id
    params['start_vm'] = 'yes'

    utils_memory.drop_caches()
    vm = params['main_vm']
    env_process.preprocess_vm(test, params, env, vm)
    vm = env.get_vm(vm)
    vm.verify_alive()
    vcpu_threads = vm.vcpu_threads
    session = vm.wait_for_login(timeout=timeout)

    dd_size = 256
    if dd_size * len(vcpu_threads) > int(params['mem']):
        dd_size = int(int(params['mem']) / 2 / len(vcpu_threads))

    mount_size = dd_size * len(vcpu_threads)

    mount_cmd = "mount -o size=%dM -t tmpfs none /tmp" % mount_size

    qemu_pid = vm.get_pid()
    drop = 0
    for cpuid in range(len(vcpu_threads)):
        error.context("Get vcpu %s used numa node." % cpuid, logging.info)
        memory_status, _ = utils_test.get_qemu_numa_status(host_numa_node,
                                                           qemu_pid)
        node_used_host = get_vcpu_used_node(host_numa_node,
                                            vcpu_threads[cpuid])
        memory_used_before = memory_status[node_used_host]
        error.context("Allocate memory in guest", logging.info)
        session.cmd(mount_cmd)
        binded_dd_cmd = "taskset %s" % str(2 ** int(cpuid))
        binded_dd_cmd += " dd if=/dev/urandom of=/tmp/%s" % cpuid
        binded_dd_cmd += " bs=1M count=%s" % dd_size
        session.cmd(binded_dd_cmd)
        error.context("Check qemu process memory use status", logging.info)
        node_after = get_vcpu_used_node(host_numa_node, vcpu_threads[cpuid])
        if node_after != node_used_host:
            logging.warn("Node used by vcpu thread changed. So drop the"
                         " results in this round.")
            drop += 1
            continue
        memory_status, _ = utils_test.get_qemu_numa_status(host_numa_node,
                                                           qemu_pid)
        memory_used_after = memory_status[node_used_host]

        memory_allocated = (memory_used_after - memory_used_before) * 4 / 1024

        if 1 - float(memory_allocated) / float(dd_size) > 0.05:
            raise error.TestFail("Expect malloc %sM memory in node %s, but "
                                 "only malloc %sM" % (dd_size, node_used_host,
                                                      memory_allocated))
    session.close()

    if drop == len(vcpu_threads):
        raise error.TestError("All test rounds are dropped."
                              " Please test it again.")
