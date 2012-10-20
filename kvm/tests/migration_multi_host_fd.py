import logging, socket, time, errno, os, fcntl
from virttest import utils_test, utils_misc, remote, virt_vm
from autotest.client.shared import error
from autotest.client.shared.syncdata import SyncData


def run_migration_multi_host_fd(test, params, env):
    """
    KVM multi-host migration over fd test:

    Migrate machine over socket's fd. Migration execution progress is
    described in documentation for migrate method in class MultihostMigration.
    This test allows migrate only one machine at once.

    @param test: kvm test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    class TestMultihostMigrationFd(utils_test.MultihostMigration):
        def __init__(self, test, params, env):
            super(TestMultihostMigrationFd, self).__init__(test, params, env)

        def migrate_vms_src(self, mig_data):
            """
            Migrate vms source.

            @param mig_Data: Data for migration.

            For change way how machine migrates is necessary
            re implement this method.
            """
            logging.info("Start migrating now...")
            cancel_delay = mig_data.params.get("cancel_delay")
            if cancel_delay is not None:
                cancel_delay = int(cancel_delay)
            vm = mig_data.vms[0]
            vm.migrate(dest_host=mig_data.dst,
                       cancel_delay=cancel_delay,
                       protocol="fd",
                       fd_src=mig_data.params['migration_fd'])

        def _check_vms_source(self, mig_data):
            for vm in mig_data.vms:
                vm.wait_for_login(timeout=self.login_timeout)
            self._hosts_barrier(mig_data.hosts, mig_data.mig_id,
                                'prepare_VMS', 60)

        def _check_vms_dest(self, mig_data):
            self._hosts_barrier(mig_data.hosts, mig_data.mig_id,
                                 'prepare_VMS', 120)
            os.close(mig_data.params['migration_fd'])

        def _connect_to_server(self, host, port, timeout=60):
            """
            Connect to network server.
            """
            endtime = time.time() + timeout
            sock = None
            while endtime > time.time():
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    sock.connect((host, port))
                    break
                except socket.error, err:
                    (code, _) = err
                    if (code != errno.ECONNREFUSED):
                        raise
                    time.sleep(1)

            return sock

        def _create_server(self, port, timeout=60):
            """
            Create network server.
            """
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(timeout)
            sock.bind(('', port))
            sock.listen(1)
            return sock

        def migration_scenario(self, worker=None):
            srchost = self.params.get("hosts")[0]
            dsthost = self.params.get("hosts")[1]
            mig_port = None

            if params.get("hostid") == self.master_id():
                mig_port = utils_misc.find_free_port(5200, 6000)

            sync = SyncData(self.master_id(), self.hostid,
                             self.params.get("hosts"),
                             {'src': srchost, 'dst': dsthost,
                              'port': "ports"}, self.sync_server)
            mig_port = sync.sync(mig_port, timeout=120)
            mig_port = mig_port[srchost]
            logging.debug("Migration port %d" % (mig_port))

            if params.get("hostid") != self.master_id():
                s = self._connect_to_server(srchost, mig_port)
                try:
                    fd = s.fileno()
                    logging.debug("File descrtiptor %d used for"
                                  " migration." % (fd))

                    self.migrate_wait(["vm1"], srchost, dsthost, mig_mode="fd",
                                      params_append={"migration_fd": fd})
                finally:
                    s.close()
            else:
                s = self._create_server(mig_port)
                try:
                    conn, _ = s.accept()
                    fd = conn.fileno()
                    logging.debug("File descrtiptor %d used for"
                                  " migration." % (fd))

                    #Prohibits descriptor inheritance.
                    flags = fcntl.fcntl(fd, fcntl.F_GETFD)
                    flags |= fcntl.FD_CLOEXEC
                    fcntl.fcntl(fd, fcntl.F_SETFD, flags)

                    self.migrate_wait(["vm1"], srchost, dsthost, mig_mode="fd",
                                      params_append={"migration_fd": fd})
                    conn.close()
                finally:
                    s.close()


    class TestMultihostMigrationCancel(TestMultihostMigrationFd):
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
        mig = TestMultihostMigrationFd(test, params, env)
    else:
        mig = TestMultihostMigrationCancel(test, params, env)

    mig.run()
