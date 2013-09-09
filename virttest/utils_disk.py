"""
Virtualization test - Virtual disk related utility functions

@copyright: Red Hat Inc.
"""
import os
import glob
import shutil
import tempfile
import logging
import ConfigParser
import re
from autotest.client import utils
from autotest.client.shared import error


# Whether to print all shell commands called
DEBUG = False


@error.context_aware
def cleanup(folder):
    """
    If folder is a mountpoint, do what is possible to unmount it. Afterwards,
    try to remove it.

    :param folder: Directory to be cleaned up.
    """
    error.context("cleaning up unattended install directory %s" % folder)
    if os.path.ismount(folder):
        utils.run('fuser -k %s' % folder, ignore_status=True, verbose=DEBUG)
        utils.run('umount %s' % folder, verbose=DEBUG)
    if os.path.isdir(folder):
        shutil.rmtree(folder)


@error.context_aware
def clean_old_image(image):
    """
    Clean a leftover image file from previous processes. If it contains a
    mounted file system, do the proper cleanup procedures.

    :param image: Path to image to be cleaned up.
    """
    error.context("cleaning up old leftover image %s" % image)
    if os.path.exists(image):
        mtab = open('/etc/mtab', 'r')
        mtab_contents = mtab.read()
        mtab.close()
        if image in mtab_contents:
            utils.run('fuser -k %s' % image, ignore_status=True, verbose=DEBUG)
            utils.run('umount %s' % image, verbose=DEBUG)
        os.remove(image)


class Disk(object):

    """
    Abstract class for Disk objects, with the common methods implemented.
    """

    def __init__(self):
        self.path = None

    def get_answer_file_path(self, filename):
        return os.path.join(self.mount, filename)

    def copy_to(self, src):
        logging.debug("Copying %s to disk image mount", src)
        dst = os.path.join(self.mount, os.path.basename(src))
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        elif os.path.isfile(src):
            shutil.copyfile(src, dst)

    def close(self):
        os.chmod(self.path, 0755)
        cleanup(self.mount)
        logging.debug("Disk %s successfully set", self.path)


class FloppyDisk(Disk):

    """
    Represents a floppy disk. We can copy files to it, and setup it in
    convenient ways.
    """
    @error.context_aware
    def __init__(self, path, qemu_img_binary, tmpdir, vfd_size):
        error.context("Creating unattended install floppy image %s" % path)
        self.mount = tempfile.mkdtemp(prefix='floppy_virttest_', dir=tmpdir)
        self.path = path
        self.vfd_size = vfd_size
        clean_old_image(path)
        try:
            c_cmd = '%s create -f raw %s %s' % (qemu_img_binary, path,
                                                self.vfd_size)
            utils.run(c_cmd, verbose=DEBUG)
            f_cmd = 'mkfs.msdos -s 1 %s' % path
            utils.run(f_cmd, verbose=DEBUG)
        except error.CmdError, e:
            logging.error("Error during floppy initialization: %s" % e)
            cleanup(self.mount)
            raise

    def close(self):
        """
        Copy everything that is in the mountpoint to the floppy.
        """
        pwd = os.getcwd()
        try:
            os.chdir(self.mount)
            path_list = glob.glob('*')
            for path in path_list:
                self.copy_to(path)
        finally:
            os.chdir(pwd)

        cleanup(self.mount)

    def copy_to(self, src):
        logging.debug("Copying %s to floppy image", src)
        mcopy_cmd = "mcopy -s -o -n -i %s %s ::/" % (self.path, src)
        utils.run(mcopy_cmd, verbose=DEBUG)

    def _copy_virtio_drivers(self, virtio_floppy):
        """
        Copy the virtio drivers on the virtio floppy to the install floppy.

        1) Mount the floppy containing the viostor drivers
        2) Copy its contents to the root of the install floppy
        """
        pwd = os.getcwd()
        try:
            m_cmd = 'mcopy -s -o -n -i %s ::/* %s' % (
                virtio_floppy, self.mount)
            utils.run(m_cmd, verbose=DEBUG)
        finally:
            os.chdir(pwd)

    def setup_virtio_win2003(self, virtio_floppy, virtio_oemsetup_id):
        """
        Setup the install floppy with the virtio storage drivers, win2003 style.

        Win2003 and WinXP depend on the file txtsetup.oem file to install
        the virtio drivers from the floppy, which is a .ini file.
        Process:

        1) Copy the virtio drivers on the virtio floppy to the install floppy
        2) Parse the ini file with config parser
        3) Modify the identifier of the default session that is going to be
           executed on the config parser object
        4) Re-write the config file to the disk
        """
        self._copy_virtio_drivers(virtio_floppy)
        txtsetup_oem = os.path.join(self.mount, 'txtsetup.oem')

        if not os.path.isfile(txtsetup_oem):
            raise IOError('File txtsetup.oem not found on the install '
                          'floppy. Please verify if your floppy virtio '
                          'driver image has this file')

        parser = ConfigParser.ConfigParser()
        parser.read(txtsetup_oem)

        if not parser.has_section('Defaults'):
            raise ValueError('File txtsetup.oem does not have the session '
                             '"Defaults". Please check txtsetup.oem')

        default_driver = parser.get('Defaults', 'SCSI')
        if default_driver != virtio_oemsetup_id:
            parser.set('Defaults', 'SCSI', virtio_oemsetup_id)
            fp = open(txtsetup_oem, 'w')
            parser.write(fp)
            fp.close()

    def setup_virtio_win2008(self, virtio_floppy):
        """
        Setup the install floppy with the virtio storage drivers, win2008 style.

        Win2008, Vista and 7 require people to point out the path to the drivers
        on the unattended file, so we just need to copy the drivers to the
        driver floppy disk. Important to note that it's possible to specify
        drivers from a CDROM, so the floppy driver copy is optional.
        Process:

        1) Copy the virtio drivers on the virtio floppy to the install floppy,
           if there is one available
        """
        if os.path.isfile(virtio_floppy):
            self._copy_virtio_drivers(virtio_floppy)
        else:
            logging.debug(
                "No virtio floppy present, not needed for this OS anyway")


class CdromDisk(Disk):

    """
    Represents a CDROM disk that we can master according to our needs.
    """

    def __init__(self, path, tmpdir):
        self.mount = tempfile.mkdtemp(prefix='cdrom_virttest_', dir=tmpdir)
        self.path = path
        clean_old_image(path)
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))

    @error.context_aware
    def close(self):
        error.context("Creating unattended install CD image %s" % self.path)
        g_cmd = ('mkisofs -o %s -max-iso9660-filenames '
                 '-relaxed-filenames -D --input-charset iso8859-1 '
                 '%s' % (self.path, self.mount))
        utils.run(g_cmd, verbose=DEBUG)

        os.chmod(self.path, 0755)
        cleanup(self.mount)
        logging.debug("unattended install CD image %s successfully created",
                      self.path)


class CdromInstallDisk(Disk):

    """
    Represents a install CDROM disk that we can master according to our needs.
    """

    def __init__(self, path, tmpdir, source_cdrom, extra_params):
        self.mount = tempfile.mkdtemp(prefix='cdrom_unattended_', dir=tmpdir)
        self.path = path
        self.extra_params = extra_params
        self.source_cdrom = source_cdrom
        cleanup(path)
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        cp_cmd = ('cp -r %s/isolinux/ %s/' % (source_cdrom, self.mount))
        listdir = os.listdir(self.source_cdrom)
        for i in listdir:
            if i == 'isolinux':
                continue
            os.symlink(os.path.join(self.source_cdrom, i),
                       os.path.join(self.mount, i))
        utils.run(cp_cmd)

    def get_answer_file_path(self, filename):
        return os.path.join(self.mount, 'isolinux', filename)

    @error.context_aware
    def close(self):
        error.context("Creating unattended install CD image %s" % self.path)
        f = open(os.path.join(self.mount, 'isolinux', 'isolinux.cfg'), 'w')
        f.write('default /isolinux/vmlinuz append initrd=/isolinux/initrd.img '
                '%s\n' % self.extra_params)
        f.close()
        m_cmd = ('mkisofs -o %s -b isolinux/isolinux.bin -c isolinux/boot.cat '
                 '-no-emul-boot -boot-load-size 4 -boot-info-table -f -R -J '
                 '-V -T %s' % (self.path, self.mount))
        utils.run(m_cmd)
        os.chmod(self.path, 0755)
        cleanup(self.mount)
        cleanup(self.source_cdrom)
        logging.debug("unattended install CD image %s successfully created",
                      self.path)


class GuestFSModiDisk(object):

    """
    class of guest disk using guestfs lib to do some operation(like read/write)
    on guest disk:
    """

    def __init__(self, disk):
        try:
            import guestfs
        except ImportError:
            install_cmd = "yum -y install python-libguestfs"
            try:
                utils.run(install_cmd)
                import guestfs
            except Exception:
                raise error.TestNAError('We need python-libguestfs (or the '
                                        'equivalent for your distro) for this '
                                        'particular feature (modifying guest '
                                        'files with libguestfs)')

        self.g = guestfs.GuestFS()
        self.disk = disk
        self.g.add_drive(disk)
        logging.debug("Launch the disk %s, wait..." % self.disk)
        self.g.launch()

    def os_inspects(self):
        self.roots = self.g.inspect_os()
        if self.roots:
            return self.roots
        else:
            return None

    def mounts(self):
        return self.g.mounts()

    def mount_all(self):
        def compare(a, b):
            if len(a[0]) > len(b[0]):
                return 1
            elif len(a[0]) == len(b[0]):
                return 0
            else:
                return -1

        roots = self.os_inspects()
        if roots:
            for root in roots:
                mps = self.g.inspect_get_mountpoints(root)
                mps.sort(compare)
                for mp_dev in mps:
                    try:
                        msg = "Mount dev '%s' partitions '%s' to '%s'"
                        logging.info(msg % (root, mp_dev[1], mp_dev[0]))
                        self.g.mount(mp_dev[1], mp_dev[0])
                    except RuntimeError, err_msg:
                        logging.info("%s (ignored)" % err_msg)
        else:
            raise error.TestError("inspect_vm: no operating systems found")

    def umount_all(self):
        logging.debug("Umount all device partitions")
        if self.mounts():
            self.g.umount_all()

    def read_file(self, file_name):
        """
        read file from the guest disk, return the content of the file

        @Param file_name: the file you want to read.
        """

        try:
            self.mount_all()
            o = self.g.cat(file_name)
            if o:
                return o
            else:
                err_msg = "Can't read file '%s', check is it exist?"
                raise error.TestError(err_msg % file_name)
        finally:
            self.umount_all()

    def write_to_image_file(self, file_name, content, w_append=False):
        """
        wirte content to the file on the guest disk.
        when using this method all the original content will be overriding.
        if you don't hope your original data be override make:
        'w_append=True'

        @Param  file_name: the file you want to write
        @Param  content: the content you want to write.
        @Param  w_append append the content or override
        """

        try:
            try:
                self.mount_all()
                if w_append:
                    self.g.write_append(file_name, content)
                else:
                    self.g.write(file_name, content)
            except Exception:
                raise error.TestError("write '%s' to file '%s' error!"
                                      % (content, file_name))
        finally:
            self.umount_all()

    def replace_image_file_content(self, file_name, find_con, rep_con):
        """
        replace file content matchs in the file with rep_con.
        suport using Regular expression

        @Param  file_name: the file you want to replace
        @Param  find_con: the orign content you want to replace.
        @Param  rep_con: the replace content you want.
        """

        try:
            self.mount_all()
            file_content = self.g.cat(file_name)
            if file_content:
                file_content_after_replace = re.sub(find_con, rep_con,
                                                    file_content)
                if file_content != file_content_after_replace:
                    self.g.write(file_name, file_content_after_replace)
            else:
                err_msg = "Can't read file '%s', check is it exist?"
                raise error.TestError(err_msg % file_name)
        finally:
            self.umount_all()
