import os
import re
import logging
import time
import socket
from autotest.client.shared import error, utils
from autotest.client.shared.barrier import listen_server
from autotest.client.shared.syncdata import SyncData
from virttest import utils_test, utils_misc


def run_migration_multi_host_with_speed_measurement(test, params, env):
    """
    KVM migration test:
    1) Get a live VM and clone it.
    2) Verify that the source VM supports migration.  If it does, proceed with
            the test.
    3) Start memory load in vm.
    4) Set defined migration speed.
    5) Send a migration command to the source VM and collecting statistic
            of migration speed.
    !) Checks that migration utilisation didn't slow down in guest stresser
       which would lead to less page-changes than required for this test.
       (migration speed is set too high for current CPU)
    6) Kill both VMs.
    7) Print statistic of migration.

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

    install_path = params.get("cpuflags_install_path", "/tmp")

    vm_mem = int(params.get("mem", "512"))

    get_mig_speed = re.compile("^transferred ram: (\d+) kbytes$",
                               re.MULTILINE)

    mig_speed = params.get("mig_speed", "1G")
    mig_speed_accuracy = float(params.get("mig_speed_accuracy", "0.2"))

    def get_migration_statistic(vm):
        last_transfer_mem = 0
        transfered_mem = 0
        mig_stat = utils.Statistic()
        for _ in range(30):
            o = vm.monitor.info("migrate")
            warning_msg = ("Migration already ended. Migration speed is"
                           " probably too high and will block vm while"
                           " filling its memory.")
            fail_msg = ("Could not determine the transferred memory from"
                        " monitor data: %s" % o)
            if isinstance(o, str):
                if not "status: active" in o:
                    raise error.TestWarn(warning_msg)
                try:
                    transfered_mem = int(get_mig_speed.search(o).groups()[0])
                except (IndexError, ValueError):
                    raise error.TestFail(fail_msg)
            else:
                if o.get("status") != "active":
                    raise error.TestWarn(warning_msg)
                try:
                    transfered_mem = o.get("ram").get("transferred") / (1024)
                except (IndexError, ValueError):
                    raise error.TestFail(fail_msg)

            real_mig_speed = (transfered_mem - last_transfer_mem) / 1024

            last_transfer_mem = transfered_mem

            logging.debug("Migration speed: %s MB/s" % (real_mig_speed))
            mig_stat.record(real_mig_speed)
            time.sleep(1)

        return mig_stat

    class TestMultihostMigration(base_class):

        def __init__(self, test, params, env):
            super(TestMultihostMigration, self).__init__(test, params, env)
            self.mig_stat = None
            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            self.id = {'src': self.srchost,
                       'dst': self.dsthost,
                       "type": "speed_measurement"}
            self.link_speed = 0

        def check_vms(self, mig_data):
            """
            Check vms after migrate.

            :param mig_data: object with migration data.
            """
            pass

        def migrate_vms_src(self, mig_data):
            """
            Migrate vms source.

            :param mig_Data: Data for migration.

            For change way how machine migrates is necessary
            re implement this method.
            """
            super_cls = super(TestMultihostMigration, self)
            super_cls.migrate_vms_src(mig_data)
            vm = mig_data.vms[0]
            self.mig_stat = get_migration_statistic(vm)

        def migration_scenario(self):
            sync = SyncData(self.master_id(), self.hostid, self.hosts,
                            self.id, self.sync_server)
            srchost = self.params.get("hosts")[0]
            dsthost = self.params.get("hosts")[1]
            vms = [params.get("vms").split()[0]]

            def worker(mig_data):
                vm = mig_data.vms[0]
                session = vm.wait_for_login(timeout=self.login_timeout)

                utils_misc.install_cpuflags_util_on_vm(test, vm, install_path,
                                                       extra_flags="-msse3 -msse2")

                cmd = ("%s/cpuflags-test --stressmem %d,%d" %
                      (os.path.join(install_path, "test_cpu_flags"),
                       vm_mem * 4, vm_mem / 2))
                logging.debug("Sending command: %s" % (cmd))
                session.sendline(cmd)

            if self.master_id() == self.hostid:
                server_port = utils_misc.find_free_port(5200, 6000)
                server = listen_server(port=server_port)
                data_len = 0
                sync.sync(server_port, timeout=120)
                client = server.socket.accept()[0]
                endtime = time.time() + 30
                while endtime > time.time():
                    data_len += len(client.recv(2048))
                client.close()
                server.close()
                self.link_speed = data_len / (30 * 1024 * 1024)
                logging.info("Link speed %d MB/s" % (self.link_speed))
                ms = utils.convert_data_size(mig_speed, 'M')
                if (ms > data_len / 30):
                    logging.warn("Migration speed %s MB/s is set faster than "
                                 "real link speed %d MB/s" % (mig_speed,
                                                              self.link_speed))
                else:
                    self.link_speed = ms / (1024 * 1024)
            else:
                data = ""
                for _ in range(10000):
                    data += "i"
                server_port = sync.sync(timeout=120)[self.master_id()]
                sock = socket.socket(socket.AF_INET,
                                     socket.SOCK_STREAM)
                sock.connect((self.master_id(), server_port))
                try:
                    endtime = time.time() + 10
                    while endtime > time.time():
                        sock.sendall(data)
                    sock.close()
                except:
                    pass
            self.migrate_wait(vms, srchost, dsthost, worker)

    mig = TestMultihostMigration(test, params, env)
    # Start migration
    mig.run()

    # If machine is migration master check migration statistic.
    if mig.master_id() == mig.hostid:
        mig_speed = utils.convert_data_size(mig_speed, "M")

        mig_stat = mig.mig_stat

        mig_speed = mig_speed / (1024 * 1024)
        real_speed = mig_stat.get_average()
        ack_speed = mig.link_speed * mig_speed_accuracy

        logging.info("Target migration speed: %d MB/s", mig_speed)
        logging.info("Real Link speed: %d MB/s", mig.link_speed)
        logging.info(
            "Average migration speed: %d MB/s", mig_stat.get_average())
        logging.info("Minimum migration speed: %d MB/s", mig_stat.get_min())
        logging.info("Maximum migration speed: %d MB/s", mig_stat.get_max())

        logging.info("Maximum tolerable divergence: %3.1f%%",
                     mig_speed_accuracy * 100)

        if real_speed < mig_speed - ack_speed:
            divergence = (1 - float(real_speed) / float(mig_speed)) * 100
            raise error.TestWarn("Average migration speed (%s MB/s) "
                                 "is %3.1f%% lower than target (%s MB/s)" %
                                 (real_speed, divergence, mig_speed))

        if real_speed > mig_speed + ack_speed:
            divergence = (1 - float(mig_speed) / float(real_speed)) * 100
            raise error.TestWarn("Average migration speed (%s MB/s) "
                                 "is %3.1f %% higher than target (%s MB/s)" %
                                 (real_speed, divergence, mig_speed))
