import logging, os
from autotest.client.shared import error
from virttest import utils_test, remote, virt_vm, utils_misc


def run_migration_multi_host(test, params, env):
    """
    KVM multi-host migration test:

    Migration execution progress is described in documentation
    for migrate method in class MultihostMigration.

    @param test: kvm test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    class TestMultihostMigration(utils_test.MultihostMigration):
        def __init__(self, test, params, env):
            super(TestMultihostMigration, self).__init__(test, params, env)
            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            self.vms = params.get("vms").split()


        def migration_scenario(self, worker=None):
            self.migrate_wait(self.vms, self.srchost, self.dsthost,
                              start_work=worker)


    class TestMultihostMigrationCancel(TestMultihostMigration):
        def __init__(self, test, params, env):
            super(TestMultihostMigrationCancel, self).__init__(test, params,
                                                               env)
            self.install_path = params.get("cpuflags_install_path", "/tmp")
            self.vm_mem = int(params.get("mem", "512"))
            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            self.vms = params.get("vms").split()
            self.id = {'src': self.srchost,
                       'dst': self.dsthost,
                       "type": "cancel_migration"}

        def check_guest(self):
            broken_vms = []
            for vm in self.vms:
                try:
                    vm = env.get_vm(vm)
                    session = vm.wait_for_login(timeout=self.login_timeout)
                    session.sendline("killall -9 cpuflags-test")
                except (remote.LoginError, virt_vm.VMError):
                    broken_vms.append(vm)
            if broken_vms:
                raise error.TestError("VMs %s should work on src"
                                      " host after canceling of"
                                      " migration." % (broken_vms))
            # Try migration again without cancel.

        def migration_scenario(self):
            def worker(mig_data):
                vm = mig_data.vms[0]
                session = vm.wait_for_login(timeout=self.login_timeout)

                utils_misc.install_cpuflags_util_on_vm(test, vm,
                                                       self.install_path,
                                                   extra_flags="-msse3 -msse2")

                cmd = ("%s/cpuflags-test --stressmem %d %%" %
                           (os.path.join(self.install_path, "test_cpu_flags"),
                            self.vm_mem / 2))
                logging.debug("Sending command: %s" % (cmd))
                session.sendline(cmd)

            super_cls = super(TestMultihostMigrationCancel, self)
            super_cls.migration_scenario(worker)

            if params.get("hostid") == self.master_id():
                self.check_guest()

            self._hosts_barrier(self.hosts, self.id,
                                'wait_for_cancel', self.login_timeout)

            params["cancel_delay"] = None
            super(TestMultihostMigrationCancel, self).migration_scenario()


    mig = None
    cancel_delay = params.get("cancel_delay", None)
    if cancel_delay is None:
        mig = TestMultihostMigration(test, params, env)
    else:
        mig = TestMultihostMigrationCancel(test, params, env)

    mig.run()
