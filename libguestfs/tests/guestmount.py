import logging
import re
import os
from autotest.client.shared import error, utils
from virttest import utils_libguestfs as lgf
from virttest import data_dir


def umount_fs(mountpoint):
    if os.path.ismount(mountpoint):
        result = utils.run("umount -l %s" % mountpoint, ignore_status=True)
        if result.exit_status:
            logging.debug("Umount %s failed", mountpoint)
            return False
    logging.debug("Umount %s successfully", mountpoint)
    return True


class GuestfishTools(lgf.GuestfishPersistent):

    """Useful Tools for Guestfish class."""

    __slots__ = lgf.GuestfishPersistent.__slots__ + ('params', )

    def __init__(self, params):
        """
        Init a persistent guestfish shellsession.
        """
        self.params = params
        disk_img = params.get("disk_img")
        ro_mode = bool(params.get("ro_mode", False))
        libvirt_domain = params.get("libvirt_domain")
        inspector = bool(params.get("inspector", False))
        mount_options = params.get("mount_options")
        super(GuestfishTools, self).__init__(disk_img, ro_mode,
                                             libvirt_domain, inspector,
                                             mount_options=mount_options)

    def get_root(self):
        """
        Get root filesystem w/ guestfish
        """
        getroot_result = self.inspect_os()
        roots_list = getroot_result.stdout.splitlines()
        if getroot_result.exit_status or not len(roots_list):
            logging.error("Get root failed:%s", getroot_result)
            return (False, getroot_result)
        return (True, roots_list[0].strip())


class VirtTools(object):
    """
    Useful functions for virt-commands.
    """

    def __init__(self, vm, params):
        self.params = params
        self.vm = vm

    def guestmount(self, mountpoint, disk_or_domain=None):
        """
        Mount filesystems in a disk or domain to host mountpoint.

        @param disk_or_domain: if it is None, use default vm in params
        """
        logging.info("Mounting filesystems...")
        if disk_or_domain is None:
            disk_or_domain = self.vm.name
        if not os.path.isdir(mountpoint):
            os.mkdir(mountpoint)
        if os.path.ismount(mountpoint):
            utils.run("umount -l %s" % mountpoint, ignore_status=True)
        inspector = "yes" == self.params.get("gm_inspector", "yes")
        readonly = "yes" == self.params.get("gm_readonly", "no")
        special_mountpoints = self.params.get("special_mountpoints", [])
        options = {}
        options['ignore_status'] = True
        options['debug'] = True
        options['timeout'] = int(self.params.get("timeout", 240))
        options['special_mountpoints'] = special_mountpoints
        result = lgf.guestmount(disk_or_domain, mountpoint,
                                inspector, readonly, **options)
        if result.exit_status:
            error_info = "Mount %s to %s failed." % (disk_or_domain,
                                                     mountpoint)
            logging.error(result)
            return (False, str(result))
        return (True, mountpoint)

    def write_file_with_guestmount(self, mountpoint, path,
                                   content=None, vm_ref=None):
        """
        Write content to file with guestmount
        """
        logging.info("Creating file...")
        gms, gmo = self.guestmount(mountpoint, vm_ref)
        if gms is True:
            mountpoint = gmo
        else:
            logging.error("Create file %s failed.", path)
            return (False, gmo)

        # file's path on host's mountpoint
        file_path = "%s/%s" % (mountpoint, path)
        if content is None:
            content = "This is a temp file with guestmount."
        try:
            fd = open(file_path, "w")
            fd.write(content)
            fd.close()
        except IOError, detail:
            logging.error(detail)
            return (False, detail)
        logging.info("Create file %s successfully", path)
        # Cleanup created file
        utils.run("rm -f %s" % file_path, ignore_status=True)
        return (True, file_path)


def run_guestmount(test, params, env):
    """
    Test libguestfs tool guestmount.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    if vm.is_alive():
        vm.destroy()

    # Create a file to vm with guestmount
    content = "This is file for guestmount test."
    path = params.get("gm_tempfile", "/home/gm_tmp")
    mountpoint = os.path.join(data_dir.get_tmp_dir(), "mountpoint")
    status_error = "yes" == params.get("status_error", "yes")
    readonly = "no" == params.get("gm_readonly", "no")
    special_mount = "yes" == params.get("gm_mount", "no")
    vt = VirtTools(vm, params)

    if special_mount:
        # Get root filesystem before test
        params['libvirt_domain'] = params.get("main_vm")
        params['inspector'] = True
        gf = GuestfishTools(params)
        roots, rootfs = gf.get_root()
        gf.close_session()
        if roots is False:
            raise error.TestError("Can not get root filesystem "
                                  "in guestfish before test")
        logging.info("Root filesystem is:%s", rootfs)
        params['special_mountpoints'] = [rootfs]

    writes, writeo = vt.write_file_with_guestmount(mountpoint, path, content)
    if umount_fs(mountpoint) is False:
        logging.error("Umount vm's filesytem failed.")

    if status_error:
        if writes:
            if readonly:
                raise error.TestFail("Write file to readonly mounted "
                                     "filesystem successfully.Not expected.")
            else:
                raise error.TestFail("Write file with guestmount "
                                     "successfully.Not expected.")
    else:
        if not writes:
            raise error.TestFail("Write file to mounted filesystem failed.")
