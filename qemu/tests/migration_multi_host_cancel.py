import logging
import socket
import time
import errno
import os
import fcntl
from virttest import utils_test, utils_misc, remote, virt_vm
from autotest.client.shared import error
from autotest.client.shared.syncdata import SyncData


@error.context_aware
def run_migration_multi_host_cancel(test, params, env):
    """
    KVM multi-host migration over fd test:

    Migrate machine over socket's fd. Migration execution progress is
    described in documentation for migrate method in class MultihostMigration.
    This test allows migrate only one machine at once.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    mig_protocol = params.get("mig_protocol", "tcp")
    base_class = utils_test.MultihostMigration
    if mig_protocol == "fd":
        base_class = utils_test.MultihostMigrationFd
    if mig_protocol == "exec":
        base_class = utils_test.MultihostMigrationExec

    class TestMultihostMigrationCancel(base_class):

        def __init__(self, test, params, env):
            super(TestMultihostMigrationCancel, self).__init__(test, params,
                                                               env)
            self.install_path = params.get("cpuflags_install_path", "/tmp")
            self.vm_mem = int(params.get("mem", "512"))
            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            self.vms = params["vms"].split()
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
            srchost = self.params.get("hosts")[0]
            dsthost = self.params.get("hosts")[1]

            def worker(mig_data):
                vm = mig_data.vms[0]
                session = vm.wait_for_login(timeout=self.login_timeout)

                utils_misc.install_cpuflags_util_on_vm(test, vm,
                                                       self.install_path,
                                                       extra_flags="-msse3 -msse2")

                cmd = ("%s/cpuflags-test --stressmem %d,%d %%" %
                      (os.path.join(self.install_path, "test_cpu_flags"),
                       self.vm_mem * 10, self.vm_mem / 2))
                logging.debug("Sending command: %s" % (cmd))
                session.sendline(cmd)

            error.context("Migration from %s to %s over protocol %s with high"
                          " cpu and memory load." %
                          (self.srchost, self.dsthost, mig_protocol),
                          logging.info)
            self.migrate_wait(["vm1"], srchost, dsthost, worker)
            if params.get("hostid") == self.master_id():
                self.check_guest()

            self._hosts_barrier(self.hosts, self.id,
                                'wait_for_cancel', self.login_timeout)

            params["cancel_delay"] = None
            error.context("Finish migration from %s to %s over protocol %s." %
                          (self.srchost, self.dsthost, mig_protocol),
                          logging.info)
            self.migrate_wait(["vm1"], srchost, dsthost)

    mig = TestMultihostMigrationCancel(test, params, env)
    mig.run()
