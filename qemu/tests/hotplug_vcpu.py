import logging
from autotest.client.shared import error
from virttest import utils_misc

@error.context_aware
def run_hotplug_vcpu(test, params, env):
    """
    NOTE: hotplug_vcpu is added since RHEL.6.3,
          so not boot with hmp is consider here.
    Test steps:
        1) boot the vm with -smp X,maxcpus=Y
        2) after logged into the vm, check vcpus number
        3) verify hot-plug sucessfully
        4) check guest get hot-pluged vcpu
        5) reboot the vm
        6) recheck guest get hot-pluged vcpu
    params:
        @param test: QEMU test object
        @param params: Dictionary with the test parameters
        @param env: Dictionary with test environment.
    """


    hotplug_cmd = "cpu_set %s online"

    error.context("boot the vm, with '-smp X,maxcpus=Y' option,"
                  "thus allow hotplug vcpu", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error.context("check if CPUs in guest matches qemu cmd "
                  "before hot-plug", logging.info)
    smp_by_cmd = int(params.get("smp"))
    if not utils_misc.check_if_vm_vcpu_match(smp_by_cmd, vm):
        raise error.TestError("CPU quantity mismatch cmd before hotplug !")
    # Start vCPU hotplug
    error.context("hotplugging vCPU...", logging.info)
    vcpu_maxcpus = int(params.get("vcpu_maxcpus"))
    # cpu starts from 0(and its not removable).
    # the hotplug-able cpus are X ~ Y.
    # X = smp - 1   ; Y = maxcpus
    vcpus_need_hotplug = range(smp_by_cmd, vcpu_maxcpus, 1)
    for vcpu in vcpus_need_hotplug:
        try:
            error.context("hot-pluging vCPU %s" % vcpu, logging.info)
            output = vm.monitor.send_args_cmd(hotplug_cmd % vcpu)
        except Exception:
            raise error.TestError("the last output from monitor is : %"
                                  % output)
    # Windows is a little bit lazy that needs more secs to recognize.
    error.context("hotplugging finished, let's wait a few sec and"
                  " check cpus quantity in guest.", logging.info)
    if not utils_misc.wait_for(lambda: utils_misc.check_if_vm_vcpu_match(vcpu_maxcpus, vm),
                       60, first=10, step=5.0, text="retry later"):
        raise error.TestFail("CPU quantity mismatch cmd after hotplug !")
    error.context("rebooting the vm and check CPU quantity !", logging.info)
    vm.reboot()
    if not utils_misc.check_if_vm_vcpu_match(vcpu_maxcpus, vm):
        raise error.TestFail("CPU quantity mismatch cmd after hotplug "
                             "and reboot !")
