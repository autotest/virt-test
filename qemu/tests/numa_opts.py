from autotest.client.shared import error
from virttest import qemu_vm

import logging
logger = logging.getLogger(__name__)
dbg = logger.debug


def run_numa_opts(test, params, env):
    """
    Simple test to check if NUMA options are being parsed properly

    This _does not_ test if NUMA information is being properly exposed to the
    guest.
    """

    dbg("starting numa_opts test...")

    # work around a test runner bug that makes it override test-specific "mem"
    # and "smp" options unconditionally, so we override them manually if
    # necessary, using the mem_override/smp_override options:
    mem_override = params.get("mem_override")
    if mem_override:
        params["mem"] = mem_override
    smp_override = params.get("smp_override")
    if smp_override:
        params["smp"] = smp_override

    # we start the VM manually because of the mem/smp workaround above:
    vm = env.get_vm(params["main_vm"])
    vm.create(params=params)

    numa = vm.monitors[0].info_numa()
    dbg("info numa reply: %r", numa)

    numa_nodes = params.get("numa_nodes")
    if numa_nodes:
        numa_nodes = int(params.get("numa_nodes"))
        if len(numa) != numa_nodes:
            raise error.TestFail(
                "Wrong number of numa nodes: %d. Expected: %d" %
                (len(numa), numa_nodes))

    for nodenr, node in enumerate(numa):
        size = params.get("numa_node%d_size" % (nodenr))
        if size is not None:
            size = int(size)
            if size != numa[nodenr][0]:
                raise error.TestFail(
                    "Wrong size of numa node %d: %d. Expected: %d" %
                    (nodenr, numa[nodenr][0], size))

        cpus = params.get("numa_node%d_cpus" % (nodenr))
        if cpus is not None:
            cpus = set([int(v) for v in cpus.split()])
            if cpus != numa[nodenr][1]:
                raise error.TestFail(
                    "Wrong CPU set on numa node %d: %s. Expected: %s" %
                    (nodenr, numa[nodenr][1], cpus))
