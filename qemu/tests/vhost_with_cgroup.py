import logging
from autotest.client.shared import error
from autotest.client import utils
from virttest.env_process import preprocess

try:
    from virttest.staging.utils_cgroup import Cgroup, CgroupModules
except ImportError:
    # TODO: Obsoleted path used prior autotest-0.15.2/virttest-2013.06.24
    from autotest.client.shared.utils_cgroup import Cgroup, CgroupModules


@error.context_aware
def run(test, params, env):
    """
    Test Step:
        1. boot guest with vhost enabled
        2. add vhost-%pid_qemu process to a cgroup
        3. check the vhost process join to the cgroup successfully

        :param test: QEMU test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
    """
    def assign_vm_into_cgroup(vm, cgroup, pwd=None):
        """
        Assigns all threads of VM into cgroup
        :param vm: desired VM
        :param cgroup: cgroup handler
        :param pwd: desired cgroup's pwd, cgroup index or None for root cgroup
        """
        cgroup.set_cgroup(vm.get_shell_pid(), pwd)
        for pid in utils.get_children_pids(vm.get_shell_pid()):
            try:
                cgroup.set_cgroup(int(pid), pwd)
            except Exception:   # Process might not already exist
                raise error.TestFail("Failed to move all VM threads to cgroup")

    error.context("Test Setup: Cgroup initialize in host", logging.info)
    modules = CgroupModules()
    if (modules.init(['cpu']) != 1):
        raise error.TestFail("Can't mount cpu cgroup modules")

    cgroup = Cgroup('cpu', '')
    cgroup.initialize(modules)

    error.context("Boot guest and attach vhost to cgroup your setting(cpu)",
                  logging.info)
    params["start_vm"] = "yes"
    preprocess(test, params, env)
    vm = env.get_vm(params["main_vm"])
    timeout = int(params.get("login_timeout", 360))
    vm.wait_for_login(timeout=timeout)

    cgroup.mk_cgroup()
    cgroup.set_property("cpu.cfs_period_us", 100000, 0)
    assign_vm_into_cgroup(vm, cgroup, 0)

    vhost_pid = utils.system_output("pidof vhost-%s" % vm.get_pid())
    if not vhost_pid:
        raise error.TestError("Vhost process not exise")
    logging.info("Vhost have started with pid %s" % vhost_pid)
    cgroup.set_cgroup(int(vhost_pid))

    error.context("Check whether vhost attached to cgroup successfully",
                  logging.info)

    if vhost_pid not in cgroup.get_property("/tasks"):
        raise error.TestError("Oops, vhost process attach to cgroup FAILED!")
    logging.info("Vhost process attach to cgroup successfully")
