"""
Installer code that implement KVM specific bits.

See BaseInstaller class in base_installer.py for interface details.
"""

import os, logging
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.virt import base_installer


__all__ = ['GitRepoInstaller', 'LocalSourceDirInstaller',
           'LocalSourceTarInstaller', 'RemoteSourceTarInstaller']


class KVMBaseInstaller(base_installer.BaseInstaller):
    '''
    Base class for KVM installations
    '''

    #
    # Name of acceptable QEMU binaries that may be built or installed.
    # We'll look for one of these binaries when linking the QEMU binary
    # to the test directory
    #
    ACCEPTABLE_QEMU_BIN_NAMES = ['qemu-kvm',
                                 'qemu-system-x86_64']

    #
    # The default names for the binaries
    #
    QEMU_BIN = 'qemu'
    QEMU_IMG_BIN = 'qemu-img'
    QEMU_IO_BIN = 'qemu-io'


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
        qemu_path = os.path.join(self.test_bindir, self.QEMU_BIN)
        qemu_img_path = os.path.join(self.test_bindir, self.QEMU_IMG_BIN)

        # clean up previous links, if they exist
        for path in (qemu_path, qemu_img_path):
            if os.path.lexists(path):
                os.unlink(path)


    def _cleanup_link_unittest(self):
        '''
        Removes previously created links, if they exist

        @return: None
        '''
        qemu_unittest_path = os.path.join(self.test_bindir, "unittests")

        if os.path.lexists(qemu_unittest_path):
            os.unlink(qemu_unittest_path)


    def _create_symlink_unittest(self):
        '''
        Create symbolic links for qemu and qemu-img commands on test bindir

        @return: None
        '''
        unittest_src = os.path.join(self.install_prefix,
                                    'share', 'qemu', 'tests')
        unittest_dst = os.path.join(self.test_bindir, "unittests")

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
            logging.debug('Could not find QEMU binary at prefix %s', self.install_prefix)

        return result


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
            logging.debug('Could not find qemu-img binary at prefix %s',
                          self.install_prefix)
            return None


    def _create_symlink_qemu(self):
        """
        Create symbolic links for qemu and qemu-img commands on test bindir

        @return: None
        """
        logging.debug("Linking QEMU binaries")

        qemu_dst = os.path.join(self.test_bindir, self.QEMU_BIN)
        qemu_img_dst = os.path.join(self.test_bindir, self.QEMU_IMG_BIN)
        qemu_io_dst = os.path.join(self.test_bindir, self.QEMU_IO_BIN)

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
            raise error.TestError('Invalid qemu-img path')

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
        super(KVMBaseInstaller, self).uninstall()


class GitRepoInstaller(KVMBaseInstaller,
                       base_installer.GitRepoInstaller):
    '''
    Installer that deals with source code on Git repositories
    '''
    pass


class LocalSourceDirInstaller(KVMBaseInstaller,
                              base_installer.LocalSourceDirInstaller):
    '''
    Installer that deals with source code on local directories
    '''
    pass

class GitInstaller(SourceDirInstaller):
    def _pull_code(self):
        """
        Retrieves code from git repositories.
        """
        params = self.params

        kernel_repo = params.get("git_repo")
        user_repo = params.get("user_git_repo")
        kmod_repo = params.get("kmod_repo")

        kernel_branch = params.get("kernel_branch", "master")
        user_branch = params.get("user_branch", "master")
        kmod_branch = params.get("kmod_branch", "master")

        kernel_lbranch = params.get("kernel_lbranch", "master")
        user_lbranch = params.get("user_lbranch", "master")
        kmod_lbranch = params.get("kmod_lbranch", "master")

        kernel_commit = params.get("kernel_commit", None)
        user_commit = params.get("user_commit", None)
        kmod_commit = params.get("kmod_commit", None)

        kernel_patches = eval(params.get("kernel_patches", "[]"))
        user_patches = eval(params.get("user_patches", "[]"))
        kmod_patches = eval(params.get("user_patches", "[]"))

        if not user_repo:
            message = "KVM user git repository path not specified"
            logging.error(message)
            raise error.TestError(message)

        userspace_srcdir = os.path.join(self.srcdir, "kvm_userspace")
        virt_utils.get_git_branch(user_repo, user_branch, userspace_srcdir,
                                 user_commit, user_lbranch)
        self.userspace_srcdir = userspace_srcdir

        if user_patches:
            os.chdir(self.userspace_srcdir)
            for patch in user_patches:
                utils.get_file(patch, os.path.join(self.userspace_srcdir,
                                                   os.path.basename(patch)))
                utils.system('patch -p1 < %s' % os.path.basename(patch))

        if kernel_repo:
            kernel_srcdir = os.path.join(self.srcdir, "kvm")
            virt_utils.get_git_branch(kernel_repo, kernel_branch, kernel_srcdir,
                                     kernel_commit, kernel_lbranch)
            self.kernel_srcdir = kernel_srcdir
            if kernel_patches:
                os.chdir(self.kernel_srcdir)
                for patch in kernel_patches:
                    utils.get_file(patch, os.path.join(self.userspace_srcdir,
                                                       os.path.basename(patch)))
                    utils.system('patch -p1 < %s' % os.path.basename(patch))
        else:
            self.kernel_srcdir = None

        if kmod_repo:
            kmod_srcdir = os.path.join (self.srcdir, "kvm_kmod")
            virt_utils.get_git_branch(kmod_repo, kmod_branch, kmod_srcdir,
                                     kmod_commit, kmod_lbranch)
            self.kmod_srcdir = kmod_srcdir
            if kmod_patches:
                os.chdir(self.kmod_srcdir)
                for patch in kmod_patches:
                    utils.get_file(patch, os.path.join(self.userspace_srcdir,
                                                       os.path.basename(patch)))
                    utils.system('patch -p1 < %s' % os.path.basename(patch))
        else:
            self.kmod_srcdir = None

        p = os.path.join(self.userspace_srcdir, 'configure')
        self.configure_options = virt_installer.check_configure_options(p)


    def _build(self):
        make_jobs = utils.count_cpus()
        cfg = './configure'
        if self.kmod_srcdir:
            logging.info('Building KVM modules')
            os.chdir(self.kmod_srcdir)
            module_build_steps = [cfg,
                                  'make clean',
                                  'make sync LINUX=%s' % self.kernel_srcdir,
                                  'make']
        elif self.kernel_srcdir:
            logging.info('Building KVM modules')
            os.chdir(self.userspace_srcdir)
            cfg += ' --kerneldir=%s' % self.host_kernel_srcdir
            module_build_steps = [cfg,
                            'make clean',
                            'make -C kernel LINUX=%s sync' % self.kernel_srcdir]
        else:
            module_build_steps = []

        for step in module_build_steps:
            utils.run(step)

        logging.info('Building KVM userspace code')
        os.chdir(self.userspace_srcdir)
        cfg += ' --prefix=%s' % self.prefix
        if "--disable-strip" in self.configure_options:
            cfg += ' --disable-strip'
        if self.extra_configure_options:
            cfg += ' %s' % self.extra_configure_options
        utils.system(cfg)
        utils.system('make clean')
        utils.system('make -j %s' % make_jobs)


    def _install(self):
        if self.kernel_srcdir:
            os.chdir(self.userspace_srcdir)
            # the kernel module install with --prefix doesn't work, and DESTDIR
            # wouldn't work for the userspace stuff, so we clear WANT_MODULE:
            utils.system('make install WANT_MODULE=')
            # and install the old-style-kmod modules manually:
            self._install_kmods_old_userspace(self.userspace_srcdir)
        elif self.kmod_srcdir:
            # if we have a kmod repository, it is easier:
            # 1) install userspace:
            os.chdir(self.userspace_srcdir)
            utils.system('make install')
            # 2) install kmod:
            self._install_kmods(self.kmod_srcdir)
        else:
            # if we don't have kmod sources, we just install
            # userspace:
            os.chdir(self.userspace_srcdir)
            utils.system('make install')

        if self.path_to_roms:
            install_roms(self.path_to_roms, self.prefix)
        self.install_unittests()
        create_symlinks(test_bindir=self.test_bindir, prefix=self.prefix,
                        bin_list=None,
                        unittest=self.unittest_prefix)


    def install(self):
        self._pull_code()
        self._build()
        self._install()
        self.reload_modules_if_needed()
        if self.save_results:
            virt_installer.save_build(self.srcdir, self.results_dir)


class PreInstalledKvm(BaseInstaller):
    # load_modules() will use the stock modules:
    load_stock_modules = True
    def install(self):
        logging.info("Expecting KVM to be already installed. Doing nothing")


class FailedInstaller:
    """
    Class used to be returned instead of the installer if a installation fails

    Useful to make sure no installer object is used if KVM installation fails.
    """
    def __init__(self, msg="KVM install failed"):
        self._msg = msg


    def load_modules(self):
        """Will refuse to load the KVM modules as install failed"""
        raise FailedKvmInstall("KVM modules not available. reason: %s" % (self._msg))


installer_classes = {
    'localsrc': SourceDirInstaller,
    'localtar': SourceDirInstaller,
    'git': GitInstaller,
    'yum': YumInstaller,
    'koji': KojiInstaller,
    'preinstalled': PreInstalledKvm,
}


def _installer_class(install_mode):
    c = installer_classes.get(install_mode)
    if c is None:
        raise error.TestError('Invalid or unsupported'
                              ' install mode: %s' % install_mode)
    return c


def make_installer(params):
    # priority:
    # - 'install_mode' param
    # - 'mode' param
    mode = params.get("install_mode", params.get("mode"))
    klass = _installer_class(mode)
    return klass(mode)
