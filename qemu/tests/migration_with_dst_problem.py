import logging
import os
import time
import re
import sys
from autotest.client.shared import utils, error
from autotest.client import utils as client_utils
from virttest import aexpect, env_process, utils_misc, qemu_storage


@error.context_aware
def run_migration_with_dst_problem(test, params, env):
    """
    KVM migration with destination problems.
    Contains group of test for testing qemu behavior if some
    problems happens on destination side.

    Tests are described right in test classes comments down in code.

    Test needs params: nettype = bridge.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    login_timeout = int(params.get("login_timeout", 360))
    mig_timeout = float(params.get("mig_timeout", "3600"))
    mig_protocol = params.get("migration_protocol", "tcp")

    test_rand = None
    mount_path = None
    while mount_path is None or os.path.exists(mount_path):
        test_rand = utils.generate_random_string(3)
        mount_path = ("%s/ni_mount_%s" %
                     (test.tmpdir, test_rand))

    mig_dst = os.path.join(mount_path, "mig_dst")

    migration_exec_cmd_src = params.get("migration_exec_cmd_src",
                                        "gzip -c > %s")
    migration_exec_cmd_src = (migration_exec_cmd_src % (mig_dst))

    class MiniSubtest(object):

        def __new__(cls, *args, **kargs):
            self = super(MiniSubtest, cls).__new__(cls)
            ret = None
            exc_info = None
            if args is None:
                args = []
            try:
                try:
                    ret = self.test(*args, **kargs)
                except Exception:
                    exc_info = sys.exc_info()
            finally:
                if hasattr(self, "clean"):
                    try:
                        self.clean()
                    except Exception:
                        if exc_info is None:
                            raise
                    if exc_info:
                        raise exc_info[0], exc_info[1], exc_info[2]
            return ret

    def control_service(session, service, init_service, action, timeout=60):
        """
        Start service on guest.

        :param vm: Virtual machine for vm.
        :param service: service to stop.
        :param action: action with service (start|stop|restart)
        :param init_service: name of service for old service control.
        """
        try:
            session.cmd("systemctl --version", timeout=timeout)
            session.cmd("systemctl %s %s.service" % (action, service),
                        timeout=timeout)
        except:
            session.cmd("service %s %s" % (init_service, action),
                        timeout=timeout)

    def set_nfs_server(vm, share_cfg):
        """
        Start nfs server on guest.

        :param vm: Virtual machine for vm.
        """
        session = vm.wait_for_login(timeout=login_timeout)
        cmd = "echo '%s' > /etc/exports" % (share_cfg)
        control_service(session, "nfs-server", "nfs", "stop")
        session.cmd(cmd)
        control_service(session, "nfs-server", "nfs", "start")
        session.cmd("iptables -F")
        session.close()

    def umount(mount_path):
        """
        Umount nfs server mount_path

        :param mount_path: path where nfs dir will be placed.
        """
        utils.run("umount -f %s" % (mount_path))

    def create_file_disk(dst_path, size):
        """
        Create file with size and create there ext3 filesystem.

        :param dst_path: Path to file.
        :param size: Size of file in MB
        """
        utils.run("dd if=/dev/zero of=%s bs=1M count=%s" % (dst_path, size))
        utils.run("mkfs.ext3 -F %s" % (dst_path))

    def mount(disk_path, mount_path, options=None):
        """
        Mount Disk to path

        :param disk_path: Path to disk
        :param mount_path: Path where disk will be mounted.
        :param options: String with options for mount
        """
        if options is None:
            options = ""
        else:
            options = "%s" % options

        utils.run("mount %s %s %s" % (options, disk_path, mount_path))

    def find_disk_vm(vm, disk_serial):
        """
        Find disk on vm which ends with disk_serial

        :param vm: VM where to find a disk.
        :param disk_serial: sufix of disk id.

        :return: string Disk path
        """
        session = vm.wait_for_login(timeout=login_timeout)

        disk_path = os.path.join("/", "dev", "disk", "by-id")
        disks = session.cmd("ls %s" % disk_path).split("\n")
        session.close()
        disk = filter(lambda x: x.endswith(disk_serial), disks)
        if not disk:
            return None
        return os.path.join(disk_path, disk[0])

    def prepare_disk(vm, disk_path, mount_path):
        """
        Create Ext3 on disk a send there data from main disk.

        :param vm: VM where to find a disk.
        :param disk_path: Path to disk in guest system.
        """
        session = vm.wait_for_login(timeout=login_timeout)
        session.cmd("mkfs.ext3 -F %s" % (disk_path))
        session.cmd("mount %s %s" % (disk_path, mount_path))
        session.close()

    def disk_load(vm, src_path, dst_path, copy_timeout=None, dsize=None):
        """
        Start disk load. Cyclic copy from src_path to dst_path.

        :param vm: VM where to find a disk.
        :param src_path: Source of data
        :param dst_path: Path to destination
        :param copy_timeout: Timeout for copy
        :param dsize: Size of data block which is periodical copied.
        """
        if dsize is None:
            dsize = 100
        session = vm.wait_for_login(timeout=login_timeout)
        cmd = ("nohup /bin/bash -c 'while true; do dd if=%s of=%s bs=1M "
               "count=%s; done;' 2> /dev/null &" % (src_path, dst_path, dsize))
        pid = re.search(r"\[.+\] (.+)",
                        session.cmd_output(cmd, timeout=copy_timeout))
        return pid.group(1)

    class IscsiServer_tgt(object):

        """
        Class for set and start Iscsi server.
        """

        def __init__(self):
            self.server_name = "autotest_guest_" + test_rand
            self.user = "user1"
            self.passwd = "pass"
            self.config = """
<target %s:dev01>
    backing-store %s
    incominguser %s %s
</target>
"""

        def set_iscsi_server(self, vm_ds, disk_path, disk_size):
            """
            Set iscsi server with some variant.

            @oaram vm_ds: VM where should be iscsi server started.
            :param disk_path: path where should be disk placed.
            :param disk_size: size of new disk.
            """
            session = vm_ds.wait_for_login(timeout=login_timeout)

            session.cmd("dd if=/dev/zero of=%s bs=1M count=%s" % (disk_path,
                                                                  disk_size))
            status, output = session.cmd_status_output("setenforce 0")
            if not status in [0, 127]:
                logging.warn("Function setenforce fails.\n %s" % (output))

            config = self.config % (self.server_name, disk_path,
                                    self.user, self.passwd)
            cmd = "cat > /etc/tgt/conf.d/virt.conf << EOF" + config + "EOF"
            control_service(session, "tgtd", "tgtd", "stop")
            session.sendline(cmd)
            control_service(session, "tgtd", "tgtd", "start")
            session.cmd("iptables -F")
            session.close()

        def find_disk(self):
            disk_path = os.path.join("/", "dev", "disk", "by-path")
            disks = utils.run("ls %s" % disk_path).stdout.split("\n")
            disk = filter(lambda x: self.server_name in x, disks)
            if disk is []:
                return None
            return os.path.join(disk_path, disk[0].strip())

        def connect(self, vm_ds):
            """
            Connect to iscsi server on guest.

            :param vm_ds: Guest where is iscsi server running.

            :return: path where disk is connected.
            """
            ip_dst = vm_ds.get_address()
            utils.run("iscsiadm -m discovery -t st -p %s" % (ip_dst))

            server_ident = ('iscsiadm -m node --targetname "%s:dev01"'
                            ' --portal %s' % (self.server_name, ip_dst))
            utils.run("%s --op update --name node.session.auth.authmethod"
                      " --value CHAP" % (server_ident))
            utils.run("%s --op update --name node.session.auth.username"
                      " --value %s" % (server_ident, self.user))
            utils.run("%s --op update --name node.session.auth.password"
                      " --value %s" % (server_ident, self.passwd))
            utils.run("%s --login" % (server_ident))
            time.sleep(1.0)
            return self.find_disk()

        def disconnect(self):
            server_ident = ('iscsiadm -m node --targetname "%s:dev01"' %
                            (self.server_name))
            utils.run("%s --logout" % (server_ident))

    class IscsiServer(object):

        """
        Iscsi server implementation interface.
        """

        def __init__(self, iscsi_type, *args, **kargs):
            if iscsi_type == "tgt":
                self.ic = IscsiServer_tgt(*args, **kargs)
            else:
                raise NotImplementedError()

        def __getattr__(self, name):
            if self.ic:
                return self.ic.__getattribute__(name)
            raise AttributeError("Cannot find attribute %s in class" % name)

    class test_read_only_dest(MiniSubtest):

        """
        Migration to read-only destination by using a migration to file.

        1) Start guest with NFS server.
        2) Config NFS server share for read-only.
        3) Mount the read-only share to host.
        4) Start second guest and try to migrate to read-only dest.

        result) Migration should fail with error message about read-only dst.
        """

        def test(self):
            if params.get("nettype") != "bridge":
                raise error.TestNAError("Unable start test without params"
                                        " nettype=bridge.")

            vm_ds = env.get_vm("virt_test_vm2_data_server")
            vm_guest = env.get_vm("virt_test_vm1_guest")
            ro_timeout = int(params.get("read_only_timeout", "480"))
            exp_str = r".*Read-only file system.*"
            utils.run("mkdir -p %s" % (mount_path))

            vm_ds.verify_alive()
            vm_guest.create()
            vm_guest.verify_alive()

            set_nfs_server(vm_ds, "/mnt *(ro,async,no_root_squash)")

            mount_src = "%s:/mnt" % (vm_ds.get_address())
            mount(mount_src, mount_path,
                  "-o hard,timeo=14,rsize=8192,wsize=8192")
            vm_guest.migrate(mig_timeout, mig_protocol,
                             not_wait_for_migration=True,
                             migration_exec_cmd_src=migration_exec_cmd_src)
            try:
                vm_guest.process.read_until_last_line_matches(exp_str,
                                                              timeout=ro_timeout)
            except aexpect.ExpectTimeoutError:
                raise error.TestFail("The Read-only file system warning not"
                                     " come in time limit.")

        def clean(self):
            if os.path.exists(mig_dst):
                os.remove(mig_dst)
            if os.path.exists(mount_path):
                umount(mount_path)
                os.rmdir(mount_path)

    class test_low_space_dest(MiniSubtest):

        """
        Migrate to destination with low space.

        1) Start guest.
        2) Create disk with low space.
        3) Try to migratie to the disk.

        result) Migration should fail with warning about No left space on dev.
        """

        def test(self):
            self.disk_path = None
            while self.disk_path is None or os.path.exists(self.disk_path):
                self.disk_path = ("%s/disk_%s" %
                                 (test.tmpdir, utils.generate_random_string(3)))

            disk_size = utils.convert_data_size(params.get("disk_size", "10M"),
                                                default_sufix='M')
            disk_size /= 1024 * 1024    # To MB.

            exp_str = r".*gzip: stdout: No space left on device.*"
            vm_guest = env.get_vm("virt_test_vm1_guest")
            utils.run("mkdir -p %s" % (mount_path))

            vm_guest.verify_alive()
            vm_guest.wait_for_login(timeout=login_timeout)

            create_file_disk(self.disk_path, disk_size)
            mount(self.disk_path, mount_path, "-o loop")

            vm_guest.migrate(mig_timeout, mig_protocol,
                             not_wait_for_migration=True,
                             migration_exec_cmd_src=migration_exec_cmd_src)
            try:
                vm_guest.process.read_until_last_line_matches(exp_str)
            except aexpect.ExpectTimeoutError:
                raise error.TestFail("The migration to destination with low "
                                     "storage space didn't fail as it should.")

        def clean(self):
            if os.path.exists(mount_path):
                umount(mount_path)
                os.rmdir(mount_path)
            if os.path.exists(self.disk_path):
                os.remove(self.disk_path)

    class test_extensive_io(MiniSubtest):

        """
        Migrate after extensive_io abstract class. This class only define
        basic funtionaly and define interface. For other tests.

        1) Start ds_guest which starts data server.
        2) Create disk for data stress in ds_guest.
        3) Share and prepare disk from ds_guest
        6) Mount the disk to mount_path
        7) Create disk for second guest in the mounted path.
        8) Start second guest with prepared disk.
        9) Start stress on the prepared disk on second guest.
        10) Wait few seconds.
        11) Restart iscsi server.
        12) Migrate second guest.

        result) Migration should be successful.
        """

        def test(self):
            self.copier_pid = None
            if params.get("nettype") != "bridge":
                raise error.TestNAError("Unable start test without params"
                                        " nettype=bridge.")

            self.disk_serial = params.get("drive_serial_image2_vm1",
                                          "nfs-disk-image2-vm1")
            self.disk_serial_src = params.get("drive_serial_image1_vm1",
                                              "root-image1-vm1")
            self.guest_mount_path = params.get("guest_disk_mount_path", "/mnt")
            self.copy_timeout = int(params.get("copy_timeout", "1024"))

            self.copy_block_size = params.get("copy_block_size", "100M")
            self.copy_block_size = utils.convert_data_size(
                self.copy_block_size,
                "M")
            self.disk_size = "%s" % (self.copy_block_size * 1.4)
            self.copy_block_size /= 1024 * 1024

            self.server_recover_timeout = (
                int(params.get("server_recover_timeout", "240")))

            utils.run("mkdir -p %s" % (mount_path))

            self.test_params()
            self.config()

            self.vm_guest_params = params.copy()
            self.vm_guest_params["images_base_dir_image2_vm1"] = mount_path
            self.vm_guest_params["image_size_image2_vm1"] = self.disk_size
            self.vm_guest_params = self.vm_guest_params.object_params("vm1")
            self.image2_vm_guest_params = (self.vm_guest_params.
                                           object_params("image2"))

            env_process.preprocess_image(test,
                                         self.image2_vm_guest_params,
                                         env)
            self.vm_guest.create(params=self.vm_guest_params)

            self.vm_guest.verify_alive()
            self.vm_guest.wait_for_login(timeout=login_timeout)
            self.workload()

            self.restart_server()

            self.vm_guest.migrate(mig_timeout, mig_protocol)

            try:
                self.vm_guest.verify_alive()
                self.vm_guest.wait_for_login(timeout=login_timeout)
            except aexpect.ExpectTimeoutError:
                raise error.TestFail("Migration should be successful.")

        def test_params(self):
            """
            Test specific params. Could be implemented in inherited class.
            """
            pass

        def config(self):
            """
            Test specific config.
            """
            raise NotImplementedError()

        def workload(self):
            disk_path = find_disk_vm(self.vm_guest, self.disk_serial)
            if disk_path is None:
                raise error.TestFail("It was impossible to find disk on VM")

            prepare_disk(self.vm_guest, disk_path, self.guest_mount_path)

            disk_path_src = find_disk_vm(self.vm_guest, self.disk_serial_src)
            dst_path = os.path.join(self.guest_mount_path, "test.data")
            self.copier_pid = disk_load(self.vm_guest, disk_path_src, dst_path,
                                        self.copy_timeout, self.copy_block_size)

        def restart_server(self):
            raise NotImplementedError()

        def clean_test(self):
            """
            Test specific cleanup.
            """
            pass

        def clean(self):
            if self.copier_pid:
                try:
                    if self.vm_guest.is_alive():
                        session = self.vm_guest.wait_for_login(timeout=
                                                               login_timeout)
                        session.cmd("kill -9 %s" % (self.copier_pid))
                except:
                    logging.warn("It was impossible to stop copier. Something "
                                 "probably happened with GUEST or NFS server.")

            if params.get("kill_vm") == "yes":
                if self.vm_guest.is_alive():
                    self.vm_guest.destroy()
                    finished = lambda: self.vm_guest.is_dead()
                    utils_misc.wait_for(finished, 30, 2, 2,
                                        "Waiting for dying of guest.")
                qemu_img = qemu_storage.QemuImg(self.image2_vm_guest_params,
                                                mount_path,
                                                None)
                qemu_img.check_image(self.image2_vm_guest_params,
                                     mount_path)

            self.clean_test()

    class test_extensive_io_nfs(test_extensive_io):

        """
        Migrate after extensive io.

        1) Start ds_guest which starts NFS server.
        2) Create disk for data stress in ds_guest.
        3) Share disk over NFS.
        4) Mount the disk to mount_path
        5) Create disk for second guest in the mounted path.
        6) Start second guest with prepared disk.
        7) Start stress on the prepared disk on second guest.
        8) Wait few seconds.
        9) Restart iscsi server.
        10) Migrate second guest.

        result) Migration should be successful.
        """

        def config(self):
            vm_ds = env.get_vm("virt_test_vm2_data_server")
            self.vm_guest = env.get_vm("vm1")
            self.image2_vm_guest_params = None
            self.copier_pid = None
            self.qemu_img = None

            vm_ds.verify_alive()
            self.control_session_ds = vm_ds.wait_for_login(timeout=
                                                           login_timeout)

            set_nfs_server(vm_ds, "/mnt *(rw,async,no_root_squash)")

            mount_src = "%s:/mnt" % (vm_ds.get_address())
            mount(mount_src, mount_path,
                  "-o hard,timeo=14,rsize=8192,wsize=8192")

        def restart_server(self):
            time.sleep(10)  # Wait for wail until copy start working.
            control_service(self.control_session_ds, "nfs-server",
                            "nfs", "stop")  # Stop NFS server
            time.sleep(5)
            control_service(self.control_session_ds, "nfs-server",
                            "nfs", "start")  # Start NFS server

            """
            Touch waits until all previous requests are invalidated
            (NFS grace period). Without grace period qemu start takes
            to long and timers for machine creation dies.
            """
            qemu_img = qemu_storage.QemuImg(self.image2_vm_guest_params,
                                            mount_path,
                                            None)
            utils.run("touch %s" % (qemu_img.image_filename),
                      self.server_recover_timeout)

        def clean_test(self):
            if os.path.exists(mount_path):
                umount(mount_path)
                os.rmdir(mount_path)

    class test_extensive_io_iscsi(test_extensive_io):

        """
        Migrate after extensive io.

        1) Start ds_guest which starts iscsi server.
        2) Create disk for data stress in ds_guest.
        3) Share disk over iscsi.
        4) Join to disk on host.
        5) Prepare partition on the disk.
        6) Mount the disk to mount_path
        7) Create disk for second guest in the mounted path.
        8) Start second guest with prepared disk.
        9) Start stress on the prepared disk on second guest.
        10) Wait few seconds.
        11) Restart iscsi server.
        12) Migrate second guest.

        result) Migration should be successful.
        """

        def test_params(self):
            self.iscsi_variant = params.get("iscsi_variant", "tgt")
            self.ds_disk_path = os.path.join(self.guest_mount_path, "test.img")

        def config(self):
            vm_ds = env.get_vm("virt_test_vm2_data_server")
            self.vm_guest = env.get_vm("vm1")
            self.image2_vm_guest_params = None
            self.copier_pid = None
            self.qemu_img = None

            vm_ds.verify_alive()
            self.control_session_ds = vm_ds.wait_for_login(timeout=
                                                           login_timeout)

            self.isci_server = IscsiServer("tgt")
            disk_path = os.path.join(self.guest_mount_path, "disk1")
            self.isci_server.set_iscsi_server(vm_ds, disk_path,
                                             (int(float(self.disk_size) * 1.1) / (1024 * 1024)))
            self.host_disk_path = self.isci_server.connect(vm_ds)

            utils.run("mkfs.ext3 -F %s" % (self.host_disk_path))
            mount(self.host_disk_path, mount_path)

        def restart_server(self):
            time.sleep(10)  # Wait for wail until copy start working.
            control_service(self.control_session_ds, "tgtd",
                            "tgtd", "stop", 240)  # Stop Iscsi server
            time.sleep(5)
            control_service(self.control_session_ds, "tgtd",
                            "tgtd", "start", 240)  # Start Iscsi server

            """
            Wait for iscsi server after restart and will be again
            accessible.
            """
            qemu_img = qemu_storage.QemuImg(self.image2_vm_guest_params,
                                            mount_path,
                                            None)
            utils.run("touch %s" % (qemu_img.image_filename),
                      self.server_recover_timeout)

        def clean_test(self):
            if os.path.exists(mount_path):
                umount(mount_path)
                os.rmdir(mount_path)
            if os.path.exists(self.host_disk_path):
                self.isci_server.disconnect()

    test_type = params.get("test_type")
    if (test_type in locals()):
        tests_group = locals()[test_type]
        tests_group()
    else:
        raise error.TestFail("Test group '%s' is not defined in"
                             " migration_with_dst_problem test" % test_type)
