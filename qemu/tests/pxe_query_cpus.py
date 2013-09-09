import time
import logging
from autotest.client.shared import error, utils
from virttest import utils_test, env_process, utils_misc


class Modprobe(object):

    prog = "/sbin/modprobe"

    def __init__(self, name):
        self.name = name

    def get_parm(self, parm):
        """
        Read parm value from sys file system
        """
        path = "/sys/module/%s/parameters/%s" % (self.name, parm)
        try:
            parm_fd = open(path, "r")
            val = parm_fd.readline()
            val = str(val).strip("\n")
            parm_fd.close()
            return val
        except IOError:
            return None

    def set_parm(self, parm, val):
        """
        Reload module with param to changes module params
        """
        val = str(val)
        _val = self.get_parm(parm)
        if val != _val:
            self.unload()
            self.load("%s=%s" % (parm, val))
            val = self.get_parm(parm)
            return (val == _val)
        return True

    def unload(self):
        cmd = "%s -r %s" % (self.prog, self.name)
        return utils.run(cmd)

    def load(self, s_parm=""):
        self.unload()
        cmd = "%s %s %s" % (self.prog, self.name, s_parm)
        return utils.run(cmd)

    def restore(self):
        """
        restore default module params
        """
        self.unload()
        time.sleep(0.5)
        return self.load()


class PxeTest(Modprobe):

    def __init__(self, test, params, env):
        """
        According cpu flag init module name and mmu
        """
        self.test = test
        self.params = params
        self.env = env
        c_flags = utils_misc.get_cpu_flags()
        if 'vmx' in c_flags:
            name = 'kvm_intel'
            if 'ept' in c_flags:
                mmu = "ept"
        elif 'svm' in c_flags:
            name = "kvm_amd"
            if 'npt' in c_flags:
                mmu = "npt"
        self.mmu = mmu
        super(PxeTest, self).__init__(name)

    def get_vm(self):
        params = self.params
        vm_name = params["main_vm"]
        params["start_vm"] = "yes"
        vm = self.env.get_vm(vm_name)
        env_process.preprocess_vm(self.test, params, self.env, vm_name)
        vm.verify_alive()
        return vm

    def stop_vms(self):
        qemu_bin = self.params["qemu_binary"]
        for vm in self.env.get_all_vms():
            if vm.is_alive():
                vm.destroy()
        utils.run("fuser -k %s" % qemu_bin, ignore_status=True)

    def enable_mmu(self):
        if not self.mmu:
            logging.warning("%s not support on host" % self.mmu)
            return
        self.stop_vms()
        enabled = self.set_parm(self.mmu, '1')
        if not enabled:
            raise error.TestFail("Fail to enable %s" % self.mmu)

    def cleanup(self):
        self.stop_vms()
        self.restore()


@error.context_aware
def run_pxe_query_cpus(test, params, env):
    """
    Qemu guest pxe boot test:
    1). check npt/ept function enable, then boot vm
    2). execute query/info cpus in loop
    3). verify vm not paused during pxe booting

    params:
    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    pxe_test = PxeTest(test, params, env)
    error.context("Enable %s on host" % pxe_test.mmu, logging.info)
    pxe_test.enable_mmu()

    error.context("Bootup vm from network", logging.info)
    vm = pxe_test.get_vm()
    params["start_vm"] = "yes"
    params["restart_vm"] = "no"
    bg = utils.InterruptedThread(utils_test.run_virt_sub_test,
                                 args=(test, params, env,),
                                 kwargs={"sub_type": "pxe"})
    bg.start()
    count = 0
    try:
        error.context("Query cpus in loop", logging.info)
        while True:
            vm.monitor.info("cpus")
            count += 1
            vm.verify_status("running")
            if not bg.isAlive():
                break
        logging.info("Execute info/query cpus %d times", count)
    finally:
        pxe_test.cleanup()
