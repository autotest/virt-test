import logging
from autotest.client.shared import error, modprobe, utils
from virttest import utils_test, env_process, utils_misc

class MMU(modprobe.Module):

    mmu_dict = {"ept": "kvm_intel", "npt": "kvm_amd"}

    def __init__(self):
        """
        Init MMU support module info;
        """
        self.mmu = self.__get_mmu()
        name = self.mmu_dict.get(self.mmu, "")
        super(MMU, self).__init__(name)

    def is_support(self):
        """
        Check ept/npt is support by module;
        """
        return self.has_param(self.mmu)

    def __get_mmu(self):
        """
        Get HW support MMU name;
        """
        cpu_flags = utils_misc.get_cpu_flags()
        mmu = filter(lambda x:x in cpu_flags, self.mmu_dict.keys())
        # check cpu support ept/npt flag
        if mmu:
            return mmu[0]
        return ""

    def is_enabled(self):
        """
        Check is mmu(ept/npt) enabled in module;
        """
        if not self.is_support():
            return False
        return self.get_value(self.mmu) in ["Y", "1"]

    def enable(self):
        """
        enable ept/npt in kvm_intel/kvm_amd module, AKA set ept/npt=1;
        """
        if self.is_enabled():
            return True
        params = "%s=1" % self.mmu
        return self.set_value(params)

    def disable(self):
        """
        Disable ept/npt in kvm_intel/kvm_amd module, AKA set ept/npt=0;
        """
        if not self.is_enabled():
            return True
        params = "%s=0" % self.mmu
        return self.set_value(params)

@error.context_aware
def run_query_cpus_when_pxeboot(test, params, env):
    """
    KVM guest pxe boot test:
    1). check npt/ept function enable, then boot vm
    2). execute query/info cpus in loop
    3). verify vm not paused during pxe booting

    params:
    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    error.context("check ept/npt feature enabled", logging.info)
    npt = MMU()
    if not npt.mmu:
        raise error.TestWarn("Hardware not support error, "
                             "EPT/NPT is not support by your CPU")
    else:
        enabled = npt.is_enabled()
        if not enabled:
            logging.info("%s not enable in %s, enable it now" % (npt.mmu,
                                                                 npt.name))
            npt.enable()

    error.context("Bootup vm from network", logging.info)
    params["start_vm"] = "yes"
    vm = env.get_vm(params["main_vm"])
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm.verify_alive()
    bg = utils.InterruptedThread(utils_test.run_virt_sub_test,
                                 args=(test, params, env,),
                                 kwargs={"sub_type":"pxe"})
    bg.start()
    vm = env.get_vm(params["main_vm"])
    try:
        error.context("Query cpus in loop", logging.info)
        count = 0
        while True:
            vm.monitor.info("cpus")
            count += 1
            vm.verify_status("running")
            if not bg.isAlive():
                break
        logging.info("Execute info/query cpus %d times", count)
    finally:
        bg.join()
