import logging, os
from autotest.client.shared import utils, error
from autotest.client import utils as client_utils
from virttest import aexpect


@error.context_aware
def run_migration_with_dst_problem(test, params, env):
    """
    KVM migration with destination problems.
    Contains group of test for testing qemu behavior if some
    problems happens on destination side.

    Tests are described right in test classes comments down in code.

    Test needs params: nettype = bridge.

    @param test: kvm test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    login_timeout = int(params.get("login_timeout", 360))
    mig_timeout = float(params.get("mig_timeout", "3600"))
    mig_protocol = params.get("migration_protocol", "tcp")

    mount_path = None
    while mount_path is None or os.path.exists(mount_path):
        mount_path = ("%s/ni_mount_%s" %
                        (test.tmpdir, utils.generate_random_string(3)))

    mig_dst = os.path.join(mount_path, "mig_dst")

    migration_exec_cmd_src = params.get("migration_exec_cmd_src",
                                        "gzip -c > %s")
    migration_exec_cmd_src = (migration_exec_cmd_src % (mig_dst))


    class MiniSubtest(object):
        def __new__(cls, *args, **kargs):
            self = super(MiniSubtest, cls).__new__(cls)
            ret = None
            if args is None:
                args = []
            try:
                ret = self.test(*args, **kargs)
            finally:
                if hasattr(self, "clean"):
                    self.clean()
            return ret


    def set_nfs_server(vm):
        """
        Start nfs server on guest.

        @param vm: Virtual machine for vm.
        """
        session = vm.wait_for_login(timeout=login_timeout)
        session.cmd("echo '/mnt *(ro,async,no_root_squash)' > /etc/exports")
        try:
            session.cmd("systemctl --version")
            session.cmd("systemctl restart nfs-server.service")
        except:
            try:
                session.cmd("service nfs restart")
            except:
                raise error.TestNAError("NFS server service is probably not"
                                        " installed.")
        session.close()


    def mount_nfs(vm_ds, mount_path):
        """
        Mount nfs server to mount_path

        @param vm_ds: Virtual machine where nfs is placed.
        @param mount_path: path where nfs dir will be placed.
        """

        utils.run("mkdir -p %s" % (mount_path))
        ip_dst = vm_ds.get_address()
        utils.run("mount %s:/mnt %s" % (ip_dst, mount_path))


    def umount(mount_path):
        """
        Umount nfs server mount_path

        @param mount_path: path where nfs dir will be placed.
        """
        utils.run("umount -f %s" % (mount_path))


    def create_file_disk(dst_path, size):
        """
        Create file with size and create there ext3 filesystem.

        @param dst_path: Path to file.
        @param size: Size of file in MB
        """
        utils.run("dd if=/dev/zero of=%s bs=1M count=%s" % (dst_path, size))
        utils.run("mkfs.ext3 -F %s" % (dst_path))


    def mount_file_disk(disk_path, mount_path):
        """
        Mount Disk to path

        @param disk_path: Path to disk
        @param mount_path: Path where disk will be mounted.
        """
        utils.run("mkdir -p %s" % (mount_path))
        utils.run("mount -o loop %s %s" % (disk_path, mount_path))


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


            vm_ds.verify_alive()
            vm_guest.create()
            vm_guest.verify_alive()

            set_nfs_server(vm_ds)
            mount_nfs(vm_ds, mount_path)
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

            vm_guest.verify_alive()
            vm_guest.wait_for_login(timeout=login_timeout)

            create_file_disk(self.disk_path, disk_size)
            mount_file_disk(self.disk_path, mount_path)

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


    test_type = params.get("test_type")
    if (test_type in locals()):
        tests_group = locals()[test_type]
        tests_group()
    else:
        raise error.TestFail("Test group '%s' is not defined in"
                             " migration_with_dst_problem test" % test_type)
