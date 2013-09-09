import logging
import os
import time
from autotest.client.shared import error
from virttest import utils_test, remote, virt_vm, utils_misc
from autotest.client.shared import utils


def run_migration_multi_host_downtime_and_speed(test, params, env):
    """
    KVM multi-host migration test:

    Migration execution progress is described in documentation
    for migrate method in class MultihostMigration.

    @param test: kvm test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    mig_protocol = params.get("mig_protocol", "tcp")
    base_class = utils_test.MultihostMigration
    if mig_protocol == "fd":
        base_class = utils_test.MultihostMigrationFd
    if mig_protocol == "exec":
        base_class = utils_test.MultihostMigrationExec

    class TestMultihostMigration(base_class):

        def __init__(self, test, params, env):
            super(TestMultihostMigration, self).__init__(test, params, env)
            self.install_path = params.get("cpuflags_install_path", "/tmp")
            self.vm_mem = int(params.get("mem", "512"))
            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            self.vms = params["vms"].split()

            self.sub_type = self.params.get("sub_type", None)
            self.max_downtime = int(self.params.get("max_mig_downtime", "10"))
            self.min_speed = self.params.get("min_migration_speed", "10")
            self.max_speed = self.params.get("max_migration_speed", "1000")
            self.ch_speed = int(self.params.get("change_speed_interval", 1))
            speed_count = float(self.params.get("count_of_change", 5))

            self.min_speed = utils.convert_data_size(self.min_speed, "M")
            self.max_speed = utils.convert_data_size(self.max_speed, "M")
            self.speed_step = int((self.max_speed - self.min_speed) /
                                  speed_count)

            if self.sub_type == "downtime":
                self.post_migration = self.post_migration_downtime
            elif self.sub_type == "speed":
                self.post_migration = self.post_migration_speed
            elif self.sub_type == "stop_during":
                self.post_migration = self.post_migration_stop
            else:
                error.TestFail("Wrong subtest type selected %s" %
                               (self.sub_type))

        def mig_finished(self, vm):
            ret = True
            if (vm.params["display"] == "spice" and
                    vm.get_spice_var("spice_seamless_migration") == "on"):
                s = vm.monitor.info("spice")
                if isinstance(s, str):
                    ret = "migrated: true" in s
                else:
                    ret = s.get("migrated") == "true"
            o = vm.monitor.info("migrate")
            if isinstance(o, str):
                return ret and (not "status: active" in o)
            else:
                return ret and (o.get("status") != "active")

        def wait_for_migration(self, vm, timeout):
            if not utils_misc.wait_for(lambda: self.mig_finished(vm),
                                       timeout,
                                       2, 2,
                                       "Waiting for migration to complete"):
                raise virt_vm.VMMigrateTimeoutError("Timeout expired while"
                                                    " waiting for migration"
                                                    " to finish")

        def post_migration_downtime(self, vm, cancel_delay, mig_offline,
                                    dsthost, vm_ports, not_wait_for_migration,
                                    fd, mig_data):

            super(TestMultihostMigration, self).post_migration(vm,
                                                               cancel_delay, mig_offline, dsthost,
                                                               vm_ports, not_wait_for_migration,
                                                               fd, mig_data)

            downtime = 0
            for downtime in range(1, self.max_downtime):
                try:
                    self.wait_for_migration(vm, 10)
                    break
                except virt_vm.VMMigrateTimeoutError:
                    vm.monitor.migrate_set_downtime(downtime)
            logging.debug("Migration pass with downtime %s", downtime)

        def post_migration_speed(self, vm, cancel_delay, mig_offline, dsthost,
                                 vm_ports, not_wait_for_migration,
                                 fd, mig_data):

            super(TestMultihostMigration, self).post_migration(vm,
                                                               cancel_delay, mig_offline, dsthost,
                                                               vm_ports, not_wait_for_migration,
                                                               fd, mig_data)

            self.min_speed
            self.max_speed
            self.ch_speed
            mig_speed = None

            for mig_speed in range(self.min_speed,
                                   self.max_speed,
                                   self.speed_step):
                try:
                    self.wait_for_migration(vm, 5)
                    break
                except virt_vm.VMMigrateTimeoutError:
                    vm.monitor.migrate_set_speed("%sB" % (mig_speed))

            # Test migration status. If migration is not completed then
            # it kill program which creates guest load.
            try:
                self.wait_for_migration(vm, 5)
            except virt_vm.VMMigrateTimeoutError:
                try:
                    session = vm.wait_for_login(timeout=15)
                    session.sendline("killall -9 cpuflags-test")
                except remote.LoginTimeoutError:
                    try:
                        self.wait_for_migration(vm, 5)
                    except virt_vm.VMMigrateTimeoutError:
                        raise error.TestFail("Migration wan't successful"
                                             " and VM is not accessible.")
                self.wait_for_migration(vm, self.mig_timeout)
            logging.debug("Migration pass with mig_speed %sB", mig_speed)

        def post_migration_stop(self, vm, cancel_delay, mig_offline, dsthost,
                                vm_ports, not_wait_for_migration,
                                fd, mig_data):

            super(TestMultihostMigration, self).post_migration(vm,
                                                               cancel_delay, mig_offline, dsthost,
                                                               vm_ports, not_wait_for_migration,
                                                               fd, mig_data)

            wait_before_mig = int(vm.params.get("wait_before_stop", "5"))

            try:
                self.wait_for_migration(vm, wait_before_mig)
            except virt_vm.VMMigrateTimeoutError:
                vm.pause()

        def migrate_vms_src(self, mig_data):
            super_cls = super(TestMultihostMigration, self)
            super_cls.migrate_vms_src(mig_data)

        def migration_scenario(self, worker=None):
            def worker_func(mig_data):
                vm = mig_data.vms[0]
                session = vm.wait_for_login(timeout=self.login_timeout)

                utils_misc.install_cpuflags_util_on_vm(test, vm,
                                                       self.install_path,
                                                       extra_flags="-msse3 -msse2")

                cmd = ("nohup %s/cpuflags-test --stressmem %d,%d &" %
                      (os.path.join(self.install_path, "test_cpu_flags"),
                       self.vm_mem * 100, self.vm_mem / 2))
                logging.debug("Sending command: %s" % (cmd))
                session.sendline(cmd)
                time.sleep(3)

            if worker is None:
                worker = worker_func

            self.migrate_wait(self.vms, self.srchost, self.dsthost,
                              start_work=worker)

    mig = TestMultihostMigration(test, params, env)

    mig.run()
