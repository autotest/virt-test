import logging
import os
import time
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_test, remote, virt_vm, utils_misc, qemu_monitor


@error.context_aware
def run(test, params, env):
    """
    KVM multi-host migration test:

    Tests multi-host migration with network problem on destination side.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    mig_protocol = params.get("mig_protocol", "tcp")
    base_class = utils_test.qemu.MultihostMigration
    if mig_protocol == "fd":
        base_class = utils_test.qemu.MultihostMigrationFd
    if mig_protocol == "exec":
        base_class = utils_test.qemu.MultihostMigrationExec

    sub_type = params["sub_type"]

    def wait_for_migration(vm, timeout):
        def mig_finished():
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

        if not utils_misc.wait_for(mig_finished, timeout, 2, 2,
                                   "Waiting for migration to complete"):
            raise virt_vm.VMMigrateTimeoutError("Timeout expired while waiting "
                                                "for migration to finish")

    class TestMultihostMigrationLongWait(base_class):

        def __init__(self, test, params, env):
            super(TestMultihostMigrationLongWait, self).__init__(
                test, params, env)
            self.install_path = params.get("cpuflags_install_path", "/tmp")
            self.vm_mem = int(params.get("mem", "512"))

            self.mig_timeout = int(params.get("mig_timeout", "550"))
            self.mig_fir_timeout = self.mig_timeout - 5

            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            self.vms = params.get("vms").split()

        def firewall_block_port(self, port):
            utils.run("iptables -A INPUT -p tcp --dport %s"
                      " -j REJECT" % (port), ignore_status=True)

        def clean_firewall(self):
            utils.run("iptables -F", ignore_status=True)

        def migrate_vms_src(self, mig_data):
            super(TestMultihostMigrationLongWait,
                  self).migrate_vms_src(mig_data)
            self._hosts_barrier(self.hosts, mig_data.mig_id, 'mig_started',
                                self.mig_timeout)
            vm = mig_data.vms[0]
            self._hosts_barrier(self.hosts, mig_data.mig_id, 'mig_interrupted',
                                self.mig_timeout)

            session = vm.wait_for_login(timeout=self.login_timeout)
            session.cmd("killall cpuflags-test")
            if params.get("mig_cancel", "no") == "yes":
                vm.monitor.cmd("migrate_cancel")
                vm.monitor.info("migrate")
            else:
                for _ in range(self.mig_fir_timeout):
                    state = vm.monitor.info("migrate")
                    if type(state) is str:
                        if "failed" in state:
                            break
                    else:
                        if state["status"] == "failed":
                            break
                    time.sleep(1)
                else:
                    raise error.TestWarn("Firewall block migraiton timeout"
                                         " is too short: %s. For completing"
                                         " the test increase mig_timeout in"
                                         " variant dest-problem-test." %
                                         (self.mig_fir_timeout))

            self._hosts_barrier(self.hosts, mig_data.mig_id, 'mig_interfynish',
                                self.mig_timeout)

        def migrate_vms_dest(self, mig_data):
            """
            Migrate vms destination. This function is started on dest host during
            migration.

            :param mig_Data: Data for migration.
            """
            self._hosts_barrier(self.hosts, mig_data.mig_id, 'mig_started',
                                self.mig_timeout)

            time.sleep(3)
            for vm in mig_data.vms:
                self.firewall_block_port(mig_data.vm_ports[vm.name])
            self._hosts_barrier(self.hosts, mig_data.mig_id, 'mig_interrupted',
                                self.mig_timeout)
            self._hosts_barrier(self.hosts, mig_data.mig_id, 'mig_interfynish',
                                self.mig_fir_timeout + 10)
            try:
                stat = []
                for vm in mig_data.vms:
                    stat.append(vm.monitor.get_status())
            except qemu_monitor.MonitorProtocolError, qemu_monitor.QMPCmdError:
                logging.debug("Guest %s not working" % (vm))

        def check_vms_src(self, mig_data):
            """
            Check vms after migrate.

            :param mig_data: object with migration data.
            """
            for vm in mig_data.vms:
                vm.resume()
                if not utils_test.qemu.guest_active(vm):
                    raise error.TestFail("Guest not active after migration")

            logging.info("Migrated guest appears to be running")

            logging.info("Logging into guest after interrupted migration...")
            for vm in mig_data.vms:
                vm.wait_for_serial_login(timeout=self.login_timeout)
                # There is sometime happen that system sends some message on
                # serial console and IP renew command block test. Because
                # there must be added "sleep" in IP renew command.
                vm.wait_for_login(timeout=self.login_timeout)

        def check_vms_dst(self, mig_data):
            """
            Check vms after migrate.

            :param mig_data: object with migration data.
            """
            for vm in mig_data.vms:
                try:
                    vm.resume()
                    if utils_test.qemu.guest_active(vm):
                        raise error.TestFail("Guest can't be active after"
                                             " interrupted migration.")
                except (qemu_monitor.MonitorProtocolError,
                        qemu_monitor.MonitorLockError,
                        qemu_monitor.QMPCmdError):
                    pass

        def migration_scenario(self, worker=None):
            error.context("Migration from %s to %s over protocol %s." %
                          (self.srchost, self.dsthost, mig_protocol),
                          logging.info)

            def worker_func(mig_data):
                vm = mig_data.vms[0]
                session = vm.wait_for_login(timeout=self.login_timeout)

                utils_misc.install_cpuflags_util_on_vm(test, vm,
                                                       self.install_path,
                                                       extra_flags="-msse3 -msse2")

                cmd = ("nohup %s/cpuflags-test --stressmem %d,%d &" %
                      (os.path.join(self.install_path, "cpu_flags"),
                       self.vm_mem * 100, self.vm_mem / 2))
                logging.debug("Sending command: %s" % (cmd))
                session.sendline(cmd)
                time.sleep(3)

            if worker is None:
                worker = worker_func

            try:
                self.migrate_wait(self.vms, self.srchost, self.dsthost,
                                  start_work=worker)
            finally:
                self.clean_firewall()

    class TestMultihostMigrationShortInterrupt(TestMultihostMigrationLongWait):

        def __init__(self, test, params, env):
            super(TestMultihostMigrationShortInterrupt, self).__init__(
                test, params, env)

        def migrate_vms_src(self, mig_data):
            super(TestMultihostMigrationLongWait,
                  self).migrate_vms_src(mig_data)
            self._hosts_barrier(self.hosts, mig_data.mig_id, 'mig_started',
                                self.mig_timeout)
            vm = mig_data.vms[0]
            self._hosts_barrier(self.hosts, mig_data.mig_id, 'mig_interrupted',
                                self.mig_timeout)

            session = vm.wait_for_login(timeout=self.login_timeout)
            session.cmd("killall cpuflags-test")

            wait_for_migration(vm, self.mig_timeout)

            self._hosts_barrier(self.hosts, mig_data.mig_id, 'mig_done',
                                self.mig_timeout)

        def migrate_vms_dest(self, mig_data):
            """
            Migrate vms destination. This function is started on dest host during
            migration.

            :param mig_Data: Data for migration.
            """
            self._hosts_barrier(self.hosts, mig_data.mig_id, 'mig_started',
                                self.mig_timeout)

            time.sleep(3)
            for vm in mig_data.vms:
                self.firewall_block_port(mig_data.vm_ports[vm.name])
            self._hosts_barrier(self.hosts, mig_data.mig_id, 'mig_interrupted',
                                self.mig_timeout)
            self.clean_firewall()
            self._hosts_barrier(self.hosts, mig_data.mig_id, 'mig_done',
                                self.mig_fir_timeout)
            try:
                for vm in mig_data.vms:
                    vm.monitor.get_status()
            except qemu_monitor.MonitorProtocolError, qemu_monitor.QMPCmdError:
                logging.debug("Guest %s not working" % (vm))

        def check_vms_dst(self, mig_data):
            """
            Check vms after migrate.

            :param mig_data: object with migration data.
            """
            super(TestMultihostMigrationLongWait, self).check_vms_dst(mig_data)

        def check_vms_src(self, mig_data):
            """
            Check vms after migrate.

            :param mig_data: object with migration data.
            """
            super(TestMultihostMigrationLongWait, self).check_vms_src(mig_data)

    mig = None
    if sub_type == "long_wait":
        mig = TestMultihostMigrationLongWait(test, params, env)
    elif sub_type == "short_interrupt":
        mig = TestMultihostMigrationShortInterrupt(test, params, env)
    else:
        raise error.TestNAError("Unsupported sub_type = '%s'." % sub_type)
    mig.run()
