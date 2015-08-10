"""
Classes and functions to handle storage devices.

This exports:
  - two functions for get image/blkdebug filename
  - class for image operates and basic parameters
"""
import logging
import os
import shutil
import re
import tempfile
from autotest.client import utils
from autotest.client.shared import error
try:
    from virttest import iscsi
except ImportError:
    from autotest.client.shared import iscsi

import utils_misc
import virt_vm
import gluster
import lvm
import ceph
import data_dir
import asset


def preprocess_images(bindir, params, env):
    # Clone master image form vms.
    for vm_name in params.get("vms").split():
        vm = env.get_vm(vm_name)
        if vm:
            vm.destroy(free_mac_addresses=False)
        vm_params = params.object_params(vm_name)
        for image in vm_params.get("master_images_clone").split():
            image_obj = QemuImg(params, bindir, image)
            image_obj.clone_image(params, vm_name, image, bindir)


def preprocess_image_backend(bindir, params, env):
    enable_gluster = params.get("enable_gluster")
    gluster_image = params.get("gluster_brick")
    if enable_gluster and gluster_image:
        return gluster.create_gluster_vol(params)

    return True


def postprocess_images(bindir, params):
    for vm in params.get("vms").split():
        vm_params = params.object_params(vm)
        for image in vm_params.get("master_images_clone").split():
            image_obj = QemuImg(params, bindir, image)
            image_obj.rm_cloned_image(params, vm, image, bindir)


def file_exists(params, filename_path):
    """
    Check if image_filename exists.

    :param params: Dictionary containing the test parameters.
    :param filename_path: path to file
    :type filename_path: str
    :param root_dir: Base directory for relative filenames.
    :type root_dir: str

    :return: True if image file exists else False
    """
    gluster_image = params.get("gluster_brick")
    if gluster_image:
        return gluster.file_exists(params, filename_path)

    if params.get("enable_ceph") == "yes":
        image_name = params.get("image_name")
        image_format = params.get("image_format", "qcow2")
        ceph_monitor = params["ceph_monitor"]
        rbd_pool_name = params["rbd_pool_name"]
        rbd_image_name = "%s.%s" % (image_name.split("/")[-1], image_format)
        return ceph.rbd_image_exist(ceph_monitor, rbd_pool_name,
                                    rbd_image_name)

    return os.path.exists(filename_path)


def file_remove(params, filename_path):
    """
    Remove the image
    :param params: Dictionary containing the test parameters.
    :param filename_path: path to file
    """
    if params.get("enable_ceph") == "yes":
        image_name = params.get("image_name")
        image_format = params.get("image_format", "qcow2")
        ceph_monitor = params["ceph_monitor"]
        rbd_pool_name = params["rbd_pool_name"]
        rbd_image_name = "%s.%s" % (image_name.split("/")[-1], image_format)
        return ceph.rbd_image_rm(ceph_monitor, rbd_pool_name, rbd_image_name)


def get_image_blkdebug_filename(params, root_dir):
    """
    Generate an blkdebug file path from params and root_dir.

    blkdebug files allow error injection in the block subsystem.

    :param params: Dictionary containing the test parameters.
    :param root_dir: Base directory for relative filenames.

    :note: params should contain:
           blkdebug -- the name of the debug file.
    """
    blkdebug_name = params.get("drive_blkdebug", None)
    if blkdebug_name is not None:
        blkdebug_filename = utils_misc.get_path(root_dir, blkdebug_name)
    else:
        blkdebug_filename = None
    return blkdebug_filename


def get_image_filename(params, root_dir):
    """
    Generate an image path from params and root_dir.

    :param params: Dictionary containing the test parameters.
    :param root_dir: Base directory for relative filenames.
    :param image_name: Force name of image.
    :param image_format: Format for image.

    :note: params should contain:
           image_name -- the name of the image file, without extension
           image_format -- the format of the image (qcow2, raw etc)
    :raise VMDeviceError: When no matching disk found (in indirect method).
    """
    enable_gluster = params.get("enable_gluster", "no") == "yes"
    enable_ceph = params.get("enable_ceph", "no") == "yes"
    image_name = params.get("image_name")
    if image_name:
        if enable_gluster:
            image_name = params.get("image_name", "image")
            image_format = params.get("image_format", "qcow2")
            return gluster.get_image_filename(params, image_name, image_format)
        if enable_ceph:
            image_format = params.get("image_format", "qcow2")
            ceph_monitor = params["ceph_monitor"]
            rbd_pool_name = params["rbd_pool_name"]
            rbd_image_name = "%s.%s" % (image_name.split("/")[-1],
                                        image_format)
            return ceph.get_image_filename(ceph_monitor, rbd_pool_name,
                                           rbd_image_name)
        return get_image_filename_filesytem(params, root_dir)
    else:
        logging.warn("image_name parameter not set.")


def get_image_filename_filesytem(params, root_dir):
    """
    Generate an image path from params and root_dir.

    :param params: Dictionary containing the test parameters.
    :param root_dir: Base directory for relative filenames.

    :note: params should contain:
           image_name -- the name of the image file, without extension
           image_format -- the format of the image (qcow2, raw etc)
    :raise VMDeviceError: When no matching disk found (in indirect method).
    """
    def sort_cmp(first, second):
        """
        This function used for sort to suit for this test, first sort by len
        then by value.
        """
        first_contains_digit = re.findall(r'[vhs]d[a-z]*[\d]+', first)
        second_contains_digit = re.findall(r'[vhs]d[a-z]*[\d]+', second)

        if not first_contains_digit and not second_contains_digit:
            if len(first) > len(second):
                return 1
            elif len(first) < len(second):
                return -1
        if len(first) == len(second):
            if first_contains_digit and second_contains_digit:
                return cmp(first, second)
            elif first_contains_digit:
                return -1
            elif second_contains_digit:
                return 1
        return cmp(first, second)

    image_name = params.get("image_name", "image")
    indirect_image_select = params.get("indirect_image_select")
    if indirect_image_select:
        re_name = image_name
        indirect_image_select = int(indirect_image_select)
        matching_images = utils.system_output("ls -1d %s" % re_name)
        matching_images = sorted(matching_images.split('\n'), cmp=sort_cmp)
        if matching_images[-1] == '':
            matching_images = matching_images[:-1]
        try:
            image_name = matching_images[indirect_image_select]
        except IndexError:
            raise virt_vm.VMDeviceError("No matching disk found for "
                                        "name = '%s', matching = '%s' and "
                                        "selector = '%s'" %
                                        (re_name, matching_images,
                                         indirect_image_select))
        for protected in params.get('indirect_image_blacklist', '').split(' '):
            match_image = re.match(protected, image_name)
            if match_image and match_image.group(0) == image_name:
                # We just need raise an error if it is totally match, such as
                # sda sda1 and so on, but sdaa should not raise an error.
                raise virt_vm.VMDeviceError("Matching disk is in blacklist. "
                                            "name = '%s', matching = '%s' and "
                                            "selector = '%s'" %
                                            (re_name, matching_images,
                                             indirect_image_select))

    image_format = params.get("image_format", "qcow2")
    if params.get("image_raw_device") == "yes":
        return image_name
    if image_format:
        image_filename = "%s.%s" % (image_name, image_format)
    else:
        image_filename = image_name

    image_filename = utils_misc.get_path(root_dir, image_filename)
    return image_filename


class OptionMissing(Exception):

    """
    Option not found in the odbject
    """

    def __init__(self, option):
        self.option = option

    def __str__(self):
        return "%s is missing. Please check your parameters" % self.option


class QemuImg(object):

    """
    A basic class for handling operations of disk/block images.
    """

    def __init__(self, params, root_dir, tag):
        """
        Init the default value for image object.

        :param params: Dictionary containing the test parameters.
        :param root_dir: Base directory for relative filenames.
        :param tag: Image tag defined in parameter images.
        """
        self.image_filename = get_image_filename(params, root_dir)
        self.image_format = params.get("image_format", "qcow2")
        self.size = params.get("image_size", "10G")
        self.storage_type = params.get("storage_type", "local fs")
        self.check_output = params.get("check_output") == "yes"
        self.image_blkdebug_filename = get_image_blkdebug_filename(params,
                                                                   root_dir)
        self.remote_keywords = params.get("remote_image",
                                          "gluster iscsi ceph").split()
        image_chain = params.get("image_chain")
        self.root_dir = root_dir
        self.base_tag = None
        self.snapshot_tag = None
        if image_chain:
            image_chain = re.split(r"\s+", image_chain)
            if tag in image_chain:
                index = image_chain.index(tag)
                if index < len(image_chain) - 1:
                    self.snapshot_tag = image_chain[index + 1]
                if index > 0:
                    self.base_tag = image_chain[index - 1]
        if self.base_tag:
            base_params = params.object_params(self.base_tag)
            self.base_image_filename = get_image_filename(base_params,
                                                          root_dir)
            self.base_format = base_params.get("image_format")
        if self.snapshot_tag:
            ss_params = params.object_params(self.snapshot_tag)
            self.snapshot_image_filename = get_image_filename(ss_params,
                                                              root_dir)
            self.snapshot_format = ss_params.get("image_format")

    def check_option(self, option):
        """
        Check if object has the option required.

        :param option: option should be checked
        """
        if option not in self.__dict__:
            raise OptionMissing(option)

    def is_remote_image(self):
        """
        Check if image is from a remote server or not
        """

        for keyword in self.remote_keywords:
            if keyword in self.image_filename:
                return True

        return False

    def backup_image(self, params, root_dir, action, good=True,
                     skip_existing=False):
        """
        Backup or restore a disk image, depending on the action chosen.

        :param params: Dictionary containing the test parameters.
        :param root_dir: Base directory for relative filenames.
        :param action: Whether we want to backup or restore the image.
        :param good: If we are backing up a good image(we want to restore it)
            or a bad image (we are saving a bad image for posterior analysis).

        :note: params should contain:
               image_name -- the name of the image file, without extension
               image_format -- the format of the image (qcow2, raw etc)
        """
        def backup_raw_device(src, dst):
            if os.path.exists(src):
                utils.system("dd if=%s of=%s bs=4k conv=sync" % (src, dst))
            else:
                logging.info("No source %s, skipping dd...", src)

        def backup_image_file(src, dst):
            logging.debug("Copying %s -> %s", src, dst)
            if os.path.isfile(dst) and os.path.isfile(src):
                os.unlink(dst)
            if os.path.isfile(src):
                shutil.copy(src, dst)
            else:
                logging.info("No source file %s, skipping copy...", src)

        def get_backup_set(filename, backup_dir, action, good):
            """
            Get all sources and destinations required for each backup.
            """
            if not os.path.isdir(backup_dir):
                os.makedirs(backup_dir)
            basename = os.path.basename(filename)
            bkp_set = []
            if good:
                src = filename
                dst = os.path.join(backup_dir, "%s.backup" % basename)
                if action == 'backup':
                    bkp_set = [[src, dst]]
                elif action == 'restore':
                    bkp_set = [[dst, src]]
            else:
                # We have to make 2 backups, one of the bad image, another one
                # of the good image
                src_bad = filename
                src_good = os.path.join(backup_dir, "%s.backup" % basename)
                hsh = utils_misc.generate_random_string(4)
                dst_bad = (os.path.join(backup_dir, "%s.bad.%s" %
                                        (basename, hsh)))
                dst_good = (os.path.join(backup_dir, "%s.good.%s" %
                                         (basename, hsh)))
                if action == 'backup':
                    bkp_set = [[src_bad, dst_bad], [src_good, dst_good]]
                elif action == 'restore':
                    bkp_set = [[src_good, src_bad]]

            if not bkp_set:
                logging.error("No backup sets for action: %s, state: %s",
                              action, good)

            return bkp_set

        image_filename = self.image_filename
        backup_dir = params.get("backup_dir", "")
        if not os.path.isabs(backup_dir):
            backup_dir = os.path.join(root_dir, backup_dir)
        if params.get('image_raw_device') == 'yes':
            iname = "raw_device"
            iformat = params.get("image_format", "qcow2")
            ifilename = "%s.%s" % (iname, iformat)
            ifilename = utils_misc.get_path(root_dir, ifilename)
            backup_set = get_backup_set(ifilename, backup_dir, action, good)
            backup_func = backup_raw_device
        else:
            backup_set = get_backup_set(image_filename, backup_dir, action,
                                        good)
            backup_func = backup_image_file

        if action == 'backup':
            image_dir = os.path.dirname(image_filename)
            image_dir_disk_free = utils.freespace(image_dir)

            backup_size = 0
            for src, dst in backup_set:
                if os.path.isfile(src):
                    backup_size += os.path.getsize(src)

            minimum_disk_free = 1.2 * backup_size
            if image_dir_disk_free < minimum_disk_free:
                image_dir_disk_free_gb = float(image_dir_disk_free) / 10 ** 9
                backup_size_gb = float(backup_size) / 10 ** 9
                minimum_disk_free_gb = float(minimum_disk_free) / 10 ** 9
                logging.error("Free space on %s: %.1f GB", image_dir,
                              image_dir_disk_free_gb)
                logging.error("Backup size: %.1f GB", backup_size_gb)
                logging.error("Minimum free space acceptable: %.1f GB",
                              minimum_disk_free_gb)
                logging.error("Available disk space is not sufficient for a"
                              "full backup. Skipping backup...")
                return

        for src, dst in backup_set:
            if action == 'backup' and skip_existing and os.path.exists(dst):
                continue
            backup_func(src, dst)

    @staticmethod
    def clone_image(params, vm_name, image_name, root_dir):
        """
        Clone master image to vm specific file.

        :param params: Dictionary containing the test parameters.
        :param vm_name: Vm name.
        :param image_name: Master image name.
        :param root_dir: Base directory for relative filenames.
        """
        if not params.get("image_name_%s_%s" % (image_name, vm_name)):
            m_image_name = params.get("image_name", "image")
            vm_image_name = "%s_%s" % (m_image_name, vm_name)
            if params.get("clone_master", "yes") == "yes":
                image_params = params.object_params(image_name)
                image_params["image_name"] = vm_image_name

                m_image_fn = get_image_filename(params, root_dir)
                image_fn = get_image_filename(image_params, root_dir)

                force_clone = params.get("force_image_clone", "no")
                if not os.path.exists(image_fn) or force_clone == "yes":
                    logging.info("Clone master image for vms.")
                    utils.run(params.get("image_clone_command") % (m_image_fn,
                                                                   image_fn))

            params["image_name_%s_%s" % (image_name, vm_name)] = vm_image_name

    @staticmethod
    def rm_cloned_image(params, vm_name, image_name, root_dir):
        """
        Remove vm specific file.

        :param params: Dictionary containing the test parameters.
        :param vm_name: Vm name.
        :param image_name: Master image name.
        :param root_dir: Base directory for relative filenames.
        """
        if params.get("image_name_%s_%s" % (image_name, vm_name)):
            m_image_name = params.get("image_name", "image")
            vm_image_name = "%s_%s" % (m_image_name, vm_name)
            if params.get("clone_master", "yes") == "yes":
                image_params = params.object_params(image_name)
                image_params["image_name"] = vm_image_name

                image_fn = get_image_filename(image_params, root_dir)

                logging.debug("Removing vm specific image file %s", image_fn)
                if os.path.exists(image_fn):
                    utils.run(params.get("image_remove_command") % (image_fn))
                else:
                    logging.debug("Image file %s not found", image_fn)

    @error.context_aware
    def copy_image(self, test, params, env):
        """
        Copy guest images from nfs server after installation failure.
        1) Mount the NFS share directory
        2) Check the existence of source image
        3) If it exists, copy the image from NFS

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        vm = env.get_vm(params["main_vm"])
        if vm is not None:
            vm.destroy()

        src = params.get('images_good')
        asset_name = '%s' % (os.path.split(params['image_name'])[1])
        dst_path = get_image_filename(params, data_dir.get_data_dir())
        image = os.path.basename(dst_path)
        image_dir = os.path.dirname(dst_path)

        # Copy the image from nfs to glusterfs server when use it
        gluster_mount_dir = ""

        if params.get("enable_gluster_install", "no") == "yes":
            gluster_uri = gluster.create_gluster_uri(params, stripped=True)
            try:
                gluster_mount_dir = tempfile.mkdtemp("-gluster")
                gluster.glusterfs_mount(gluster_uri, gluster_mount_dir)
            except Exception, err:
                shutil.rmtree(gluster_mount_dir)
                raise error.TestError("Failed to mount gluster volume %s to "
                                      "mount dir %s: %s" % (gluster_uri,
                                                            gluster_mount_dir,
                                                            err))

            params['gluster_mount_dir'] = gluster_mount_dir
            dst_path = os.path.join(gluster_mount_dir, asset_name)
            dst_path += ".%s" % params['image_format']

        if params.get("rename_error_image", "no") == "yes":
            if gluster_mount_dir:
                error_image = os.path.join(gluster_mount_dir, asset_name)
                error_image += "-error"
                error_image += '.' + params['image_format']
                error_dst_path = error_image
            else:
                error_image = os.path.basename(params['image_name']) + "-error"
                error_image += '.' + params['image_format']
                error_dst_path = os.path.join(image_dir, error_image)

            shutil.copyfile(dst_path, error_dst_path)

        if src:
            mount_dest_dir = params.get('dst_dir', '/mnt/images')
            if not os.path.exists(mount_dest_dir):
                try:
                    os.makedirs(mount_dest_dir)
                except OSError, err:
                    logging.warning('mkdir %s error:\n%s', mount_dest_dir, err)

            if not os.path.exists(mount_dest_dir):
                raise error.TestError('Failed to create NFS share dir %s' %
                                      mount_dest_dir)

            error.context("Mount the NFS share directory")
            if not utils_misc.mount(src, mount_dest_dir, 'nfs', 'ro'):
                raise error.TestError('Could not mount NFS share %s to %s' %
                                      (src, mount_dest_dir))

            error.context("Check the existence of source image")
            src_path = '%s/%s.%s' % (mount_dest_dir, asset_name,
                                     params['image_format'])
            asset_info = asset.get_file_asset(asset_name, src_path, dst_path)
            if asset_info is None:
                raise error.TestError('Could not find %s' % image)
        else:
            asset_info = asset.get_asset_info(asset_name)

        # Do not force extraction if integrity information is available
        if asset_info['sha1_url']:
            force = params.get("force_copy", "no") == "yes"
        else:
            force = params.get("force_copy", "yes") == "yes"

        error.context("Copy image '%s'" % image, logging.info)
        if utils.is_url(asset_info['url']):
            asset.download_file(asset_info, interactive=False, force=force)
        else:
            utils.get_file(asset_info['url'], asset_info['destination'])


class Rawdev(object):

    """
    Base class for raw storage devices such as iscsi and local disks
    """

    def __init__(self, params, root_dir, tag):
        """
        Init the default value for image object.

        :param params: Dictionary containing the test parameters.
        :param root_dir: Base directory for relative filenames.
        :param tag: Image tag defined in parameter images
        """
        host_set_flag = params.get("host_setup_flag")
        if host_set_flag is not None:
            self.exec_cleanup = int(host_set_flag) & 2 == 2
        else:
            self.exec_cleanup = False
        if params.get("force_cleanup") == "yes":
            self.exec_cleanup = True
        self.image_name = tag


class Iscsidev(Rawdev):

    """
    Class for handle iscsi devices for VM
    """

    def __init__(self, params, root_dir, tag):
        """
        Init the default value for image object.

        :param params: Dictionary containing the test parameters.
        :param root_dir: Base directory for relative filenames.
        :param tag: Image tag defined in parameter images
        """
        Rawdev.__init__(self, params, root_dir, tag)
        self.emulated_file_remove = False
        self.emulated_image = params.get("emulated_image")
        if self.emulated_image:
            self.emulated_image = os.path.join(root_dir, self.emulated_image)
            if params.get("emulated_file_remove", "no") == "yes":
                self.emulated_file_remove = True
        params["iscsi_thread_id"] = self.image_name
        self.iscsidevice = iscsi.Iscsi.create_iSCSI(params, root_dir=root_dir)
        self.device_id = params.get("device_id")
        self.iscsi_init_timeout = int(params.get("iscsi_init_timeout", 10))


class LVMdev(Rawdev):

    """
    Class for handle LVM devices for VM
    """

    def __init__(self, params, root_dir, tag):
        """
        Init the default value for image object.

        :param params: Dictionary containing the test parameters.
        :param root_dir: Base directory for relative filenames.
        :param tag: Image tag defined in parameter images
        """
        super(LVMdev, self).__init__(params, root_dir, tag)
        if params.get("emulational_device", "yes") == "yes":
            self.lvmdevice = lvm.EmulatedLVM(params, root_dir=root_dir)
        else:
            self.lvmdevice = lvm.LVM(params)
