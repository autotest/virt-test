import logging
import os
from autotest.client.shared import error
from autotest.client import utils
from virttest import env_process, utils_test, remote, virt_vm, utils_misc
from autotest.client.shared.syncdata import SyncData
from provider_lib import cpuflags


@error.context_aware
def run(test, params, env):
    """
    KVM multi-host migration ping pong test:

    Migration execution progress is described in documentation
    for migrate method in class MultihostMigration.

    The test procedure:
    1) starts vm on master host.
    2) install on vm cpuflags-test and disktest utils.
    3) start ping pong migration master->slave->master variable migrate_count.
        - check if cpuflags-test and disktest works properly
          after every migration.

    On fail raise error with output of cpuflags-test and disktest utils.

    There are some variants of test no stress, cpu_memory, disk, all.

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

    class TestMultihostMigration(base_class):

        def __init__(self, test, params, env):
            super(TestMultihostMigration, self).__init__(test, params, env)
            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            self.vms = params["vms"].split()
            self.vm = params["vms"].split()[0]

            self.install_path = params.get("cpuflags_install_path", "/tmp")
            self.stress_memory = int(params.get("stress_memory", "128"))
            self.stress_type = params.get("stress_type", "none")
            self.migrate_count = int(params.get("migrate_count", "3")) - 1
            self.migration_timeout = int(params.get("migration_timeout",
                                                    "240"))
            self.disk_usage = int(params.get("disk_usage", "512"))
            self.id = {'src': self.srchost,
                       'dst': self.dsthost,
                       "type": "file_transfer"}
            self.vmaddr = None
            self.cpuflags_test_out = os.path.join("/tmp", "cpuflags_test.out")
            self.disktest_out = os.path.join("/tmp", "disktest.out")

        def check_vms(self, mig_data):
            """
            Check vms after migrate.

            :param mig_data: object with migration data.
            """
            for vm in mig_data.vms:
                vm.resume()
                if not utils_test.qemu.guest_active(vm):
                    raise error.TestFail("Guest not active after migration")

            logging.info("Migrated guest appears to be running")

            logging.info("Logging into migrated guest after migration...")
            for vm in mig_data.vms:
                session = vm.wait_for_login(timeout=self.login_timeout)

                run_error = []
                if self.stress_type in ["cpu_memory", "all"]:
                    if session.cmd_status("killall -s 0 cpuflags-test") != 0:
                        run_error.append("cpuflags-test")

                if self.stress_type in ["disk", "all"]:
                    if session.cmd_status("killall -s 0 disktest") != 0:
                        run_error.append("disktest")

                if run_error:
                    cpu_flags_out = ""
                    disk_out = ""
                    if "cpuflags-test" in run_error:
                        cpu_flags_out = ("\ncpuflags_test_output: \n" +
                                         session.cmd_output("cat %s" %
                                                            (self.cpuflags_test_out)))
                    if "disktest" in run_error:
                        disk_out = ("\ndisk_test_output: \n" +
                                    session.cmd_output("cat %s" %
                                                       (self.disktest_out)))
                    raise error.TestFail("Something wrong happened"
                                         " during migration %s"
                                         " should be running all time"
                                         " during this test."
                                         " outputs%s%s" %
                                         (run_error, cpu_flags_out,
                                          disk_out))

        def _prepare_vm(self, vm_name):
            """
            Prepare, start vm and return vm.

            :param vm_name: Class with data necessary for migration.

            :return: Started VM.
            """
            new_params = self.params.copy()

            new_params['migration_mode'] = None
            new_params['start_vm'] = 'yes'
            self.vm_lock.acquire()
            env_process.process(self.test, new_params, self.env,
                                env_process.preprocess_image,
                                env_process.preprocess_vm)
            self.vm_lock.release()
            vm = self.env.get_vm(vm_name)
            vm.wait_for_login(timeout=self.login_timeout)
            return vm

        def ping_pong_migrate(self, sync, worker):
            for _ in range(self.migrate_count):
                logging.info("File transfer not ended, starting"
                             " a round of migration...")
                sync.sync(True, timeout=self.migration_timeout)
                self.migrate_wait([self.vm],
                                  self.srchost,
                                  self.dsthost)
                tmp = self.dsthost
                self.dsthost = self.srchost
                self.srchost = tmp

        def install_disktest(self):
            test.job.setup_dep(['disktest'])
            self.disk_srcdir = os.path.join(test.autodir, "deps",
                                            "disktest", "src")

        def migration_scenario(self):
            error.context("Migration from %s to %s over protocol %s." %
                          (self.srchost, self.dsthost, mig_protocol),
                          logging.info)
            sync = SyncData(self.master_id(), self.hostid, self.hosts,
                            self.id, self.sync_server)
            address_cache = env.get("address_cache")

            def worker_cpu_mem(mig_data):
                vm = mig_data.vms[0]
                session = vm.wait_for_login(timeout=self.login_timeout)

                cpuflags.install_cpuflags_util_on_vm(test, vm,
                                                     self.install_path,
                                                     extra_flags="-msse3 -msse2")

                cmd = ("nohup %s/cpuflags-test --stressmem %d,32"
                       " > %s &" %
                      (os.path.join(self.install_path, "cpu_flags"),
                       self.stress_memory,
                       self.cpuflags_test_out))
                logging.debug("Sending command: %s" % (cmd))
                session.sendline(cmd)
                if session.cmd_status("killall -s 0 cpuflags-test") != 0:
                    cpu_flags_out = ("\n cpuflags_test_output: \n" +
                                     session.cmd_output("cat %s" %
                                                        (self.cpuflags_test_out)))
                    raise error.TestFail("Something wrong happened"
                                         " during migration cpuflags-test"
                                         " should be running all time"
                                         " during this test.\n%s" %
                                         (cpu_flags_out))

            def worker_disk(mig_data):
                vm = mig_data.vms[0]
                session = vm.wait_for_login(timeout=self.login_timeout)

                utils_misc.install_disktest_on_vm(test, vm, self.disk_srcdir,
                                                  self.install_path)

                cmd = ("nohup %s/disktest -m %s -L -S > %s &" %
                      (os.path.join(self.install_path, "disktest", "src"),
                       self.disk_usage,
                       self.disktest_out))
                logging.debug("Sending command: %s" % (cmd))
                session.sendline(cmd)
                if session.cmd_status("killall -s 0 disktest") != 0:
                    disk_out = ("\n cpuflags_test_output: \n" +
                                session.cmd_output("cat %s" %
                                                   (self.disktest_out)))
                    raise error.TestFail("Something wrong happened"
                                         " during migration disktest"
                                         " should be running all time"
                                         " during this test.\n%s" %
                                         (disk_out))

            def worker_all(mig_data):
                worker_cpu_mem(mig_data)
                worker_disk(mig_data)

            self.worker = None
            if self.stress_type == "cpu_memory":
                self.worker = worker_cpu_mem

            elif self.stress_type == "disk":
                if (self.hostid == self.master_id()):
                    self.install_disktest()
                self.worker = worker_disk

            elif self.stress_type == "all":
                if (self.hostid == self.master_id()):
                    self.install_disktest()
                self.worker = worker_all

            if (self.hostid == self.master_id()):
                self.vm_addr = self._prepare_vm(self.vm).get_address()
                self._hosts_barrier(self.hosts, self.id, "befor_mig", 120)
                sync.sync(address_cache, timeout=120)
            else:
                self._hosts_barrier(self.hosts, self.id, "befor_mig", 260)
                address_cache.update(sync.sync(timeout=120)[self.master_id()])

            self.migrate_wait([self.vm], self.srchost, self.dsthost,
                              start_work=self.worker)
            sync.sync(True, timeout=self.migration_timeout)
            tmp = self.dsthost
            self.dsthost = self.srchost
            self.srchost = tmp

            self.ping_pong_migrate(sync, self.worker)

    mig = TestMultihostMigration(test, params, env)
    mig.run()
