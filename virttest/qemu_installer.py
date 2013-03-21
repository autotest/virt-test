"""
Installer code that implement KVM specific bits.

See BaseInstaller class in base_installer.py for interface details.
"""

import os, logging
from autotest.client import utils
from autotest.client.shared import error
import base_installer


__all__ = ['GitRepoInstaller', 'LocalSourceDirInstaller',
           'LocalSourceTarInstaller', 'RemoteSourceTarInstaller']


class QEMUBaseInstaller(base_installer.BaseInstaller):
    '''
    Base class for KVM installations
    '''

    #
    # Name of acceptable QEMU binaries that may be built or installed.
    # We'll look for one of these binaries when linking the QEMU binary
    # to the test directory
    #
    qemu_system = 'qemu-system-' + utils.system_output('uname -i')
    ACCEPTABLE_QEMU_BIN_NAMES = ['qemu-kvm', qemu_system]

    #
    # The default names for the binaries
    #
    QEMU_BIN = 'qemu'
    QEMU_IMG_BIN = 'qemu-img'
    QEMU_IO_BIN = 'qemu-io'
    QEMU_FS_PROXY_BIN = 'virtfs-proxy-helper'


    def _kill_qemu_processes(self):
        """
        Kills all qemu processes and all processes holding /dev/kvm down

        @return: None
        """
        logging.debug("Killing any qemu processes that might be left behind")
        utils.system("pkill qemu", ignore_status=True)
        # Let's double check to see if some other process is holding /dev/kvm
        if os.path.isfile("/dev/kvm"):
            utils.system("fuser -k /dev/kvm", ignore_status=True)


    def _cleanup_links_qemu(self):
        '''
        Removes previously created links, if they exist

        @return: None
        '''
        qemu_path = os.path.join(self.test_builddir, self.QEMU_BIN)
        qemu_img_path = os.path.join(self.test_builddir, self.QEMU_IMG_BIN)
        qemu_io_path = os.path.join(self.test_builddir, self.QEMU_IO_BIN)
        qemu_fs_proxy_path = os.path.join(self.test_builddir,
                                          self.QEMU_FS_PROXY_BIN)

        # clean up previous links, if they exist
        for path in (qemu_path, qemu_img_path, qemu_io_path,
                     qemu_fs_proxy_path):
            if os.path.lexists(path):
                os.unlink(path)


    def _cleanup_link_unittest(self):
        '''
        Removes previously created links, if they exist

        @return: None
        '''
        qemu_unittest_path = os.path.join(self.test_builddir, "unittests")

        if os.path.lexists(qemu_unittest_path):
            os.unlink(qemu_unittest_path)


    def _create_symlink_unittest(self):
        '''
        Create symbolic links for qemu and qemu-img commands on test bindir

        @return: None
        '''
        unittest_src = os.path.join(self.install_prefix,
                                    'share', 'qemu', 'tests')
        unittest_dst = os.path.join(self.test_builddir, "unittests")

        if os.path.lexists(unittest_dst):
            logging.debug("Unlinking unittest dir")
            os.unlink(unittest_dst)

        logging.debug("Linking unittest dir")
        os.symlink(unittest_src, unittest_dst)


    def _qemu_bin_exists_at_prefix(self):
        '''
        Attempts to find the QEMU binary at the installation prefix

        @return: full path of QEMU binary or None if not found
        '''
        result = None

        for name in self.ACCEPTABLE_QEMU_BIN_NAMES:
            qemu_bin_name = os.path.join(self.install_prefix, 'bin', name)
            if os.path.isfile(qemu_bin_name):
                result = qemu_bin_name
                break

        if result is not None:
            logging.debug('Found QEMU binary at %s', result)
        else:
            logging.debug('Could not find QEMU binary at prefix %s',
                          self.install_prefix)

        return result

    def install(self):
        self.install_unittests()
        self._clean_previous_installs()
        self._get_packages()
        self._install_packages()
        create_symlinks(test_bindir=self.test_bindir,
                        bin_list=self.qemu_bin_paths,
                        unittest=self.unittest_prefix)
        self.reload_modules_if_needed()
        if self.save_results:
            virt_utils.archive_as_tarball(self.srcdir, self.results_dir)

    def _qemu_img_bin_exists_at_prefix(self):
        '''
        Attempts to find the qemu-img binary at the installation prefix

        @return: full path of qemu-img binary or None if not found
        '''
        qemu_img_bin_name = os.path.join(self.install_prefix,
                                         'bin', self.QEMU_IMG_BIN)
        if os.path.isfile(qemu_img_bin_name):
            logging.debug('Found qemu-img binary at %s', qemu_img_bin_name)
            return qemu_img_bin_name
        else:
            logging.debug('Could not find qemu-img binary at prefix %s',
                          self.install_prefix)
            return None


    def _qemu_io_bin_exists_at_prefix(self):
        '''
        Attempts to find the qemu-io binary at the installation prefix

        @return: full path of qemu-io binary or None if not found
        '''
        qemu_io_bin_name = os.path.join(self.install_prefix,
                                         'bin', self.QEMU_IO_BIN)
        if os.path.isfile(qemu_io_bin_name):
            logging.debug('Found qemu-io binary at %s', qemu_io_bin_name)
            return qemu_io_bin_name
        else:
            logging.debug('Could not find qemu-io binary at prefix %s',
                          self.install_prefix)
            return None


    def _qemu_fs_proxy_bin_exists_at_prefix(self):
        '''
        Attempts to find the qemu fs proxy binary at the installation prefix

        @return: full path of qemu fs proxy binary or None if not found
        '''
        qemu_fs_proxy_bin_name = os.path.join(self.install_prefix,
                                              'bin', self.QEMU_FS_PROXY_BIN)
        if os.path.isfile(qemu_fs_proxy_bin_name):
            logging.debug('Found qemu fs proxy binary at %s',
                          qemu_fs_proxy_bin_name)
            return qemu_fs_proxy_bin_name
        else:
            logging.debug('Could not find qemu fs proxy binary at prefix %s',
                          self.install_prefix)
            return None


    def _create_symlink_qemu(self):
        """
        Create symbolic links for qemu and qemu-img commands on test bindir

        @return: None
        """
        logging.debug("Linking QEMU binaries")

        qemu_dst = os.path.join(self.test_builddir, self.QEMU_BIN)
        qemu_img_dst = os.path.join(self.test_builddir, self.QEMU_IMG_BIN)
        qemu_io_dst = os.path.join(self.test_builddir, self.QEMU_IO_BIN)
        qemu_fs_proxy_dst = os.path.join(self.test_builddir,
                                         self.QEMU_FS_PROXY_BIN)

        qemu_bin = self._qemu_bin_exists_at_prefix()
        if qemu_bin is not None:
            os.symlink(qemu_bin, qemu_dst)
        else:
            raise error.TestError('Invalid qemu path')

        qemu_img_bin = self._qemu_img_bin_exists_at_prefix()
        if qemu_img_bin is not None:
            os.symlink(qemu_img_bin, qemu_img_dst)
        else:
            raise error.TestError('Invalid qemu-img path')

        qemu_io_bin = self._qemu_io_bin_exists_at_prefix()
        if qemu_io_bin is not None:
            os.symlink(qemu_io_bin, qemu_io_dst)
        else:
            raise error.TestError('Invalid qemu-io path')

        qemu_fs_proxy_bin = self._qemu_fs_proxy_bin_exists_at_prefix()
        if qemu_fs_proxy_bin is not None:
            os.symlink(qemu_fs_proxy_bin, qemu_fs_proxy_dst)
        else:
            logging.warning('Qemu fs proxy path %s not found on source dir')



        @param test: kvm test object
        @param params: Dictionary with test arguments
        """
        super(SourceDirInstaller, self).set_install_params(test, params)

        self.mod_install_dir = os.path.join(self.prefix, 'modules')
        self.installed_kmods = False  # it will be set to True in case we
                                      # installed our own modules

        srcdir = params.get("srcdir", None)
        self.path_to_roms = params.get("path_to_rom_images", None)

        if self.install_mode == 'localsrc':
            if srcdir is None:
                raise error.TestError("Install from source directory specified"
                                      "but no source directory provided on the"
                                      "control file.")
            else:
                shutil.copytree(srcdir, self.srcdir)

        elif self.install_mode == 'localtar':
            tarball = params.get("tarball")
            if not tarball:
                raise error.TestError("KVM Tarball install specified but no"
                                      " tarball provided on control file.")
            logging.info("Installing KVM from a local tarball")
            logging.info("Using tarball %s")
            tarball = utils.unmap_url("/", params.get("tarball"), "/tmp")
            utils.extract_tarball_to_dir(tarball, self.srcdir)

        if self.install_mode in ['localtar', 'srcdir']:
            self.repo_type = virt_utils.check_kvm_source_dir(self.srcdir)
            p = os.path.join(self.srcdir, 'configure')
            self.configure_options = virt_installer.check_configure_options(p)


    def _build(self):
        make_jobs = utils.count_cpus()
        os.chdir(self.srcdir)
        # For testing purposes, it's better to build qemu binaries with
        # debugging symbols, so we can extract more meaningful stack traces.
        cfg = "./configure --prefix=%s" % self.prefix
        if "--disable-strip" in self.configure_options:
            cfg += " --disable-strip"
        steps = [cfg, "make clean", "make -j %s" % make_jobs]
        logging.info("Building KVM")
        for step in steps:
            utils.system(step)


    def _install_kmods_old_userspace(self, userspace_path):
        """
        Run the module install command.

        This uses a simple mechanism of looking up the installer name
        for deciding what action to do.

        @return: None
        '''
        if 'unit' in self.name:
            self._cleanup_link_unittest()
            self._create_symlink_unittest()

        elif 'qemu' in self.name:
            self._cleanup_links_qemu()
            self._create_symlink_qemu()


    def uninstall(self):
        '''
        Performs the uninstallation of KVM userspace component

        @return: None
        '''
        self._kill_qemu_processes()
        self._cleanup_links()
        super(QEMUBaseInstaller, self).uninstall()


class GitRepoInstaller(QEMUBaseInstaller,
                       base_installer.GitRepoInstaller):
    '''
    Installer that deals with source code on Git repositories
    '''
    pass


class LocalSourceDirInstaller(QEMUBaseInstaller,
                              base_installer.LocalSourceDirInstaller):
    '''
    Installer that deals with source code on local directories
    '''
    pass


class LocalSourceTarInstaller(QEMUBaseInstaller,
                              base_installer.LocalSourceTarInstaller):
    '''
    Installer that deals with source code on local tarballs
    '''
    pass


class RemoteSourceTarInstaller(QEMUBaseInstaller,
                               base_installer.RemoteSourceTarInstaller):
    '''
    Installer that deals with source code on remote tarballs
    '''
    pass
