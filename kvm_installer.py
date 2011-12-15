"""
Installer code that implement KVM specific bits.

See BaseInstaller class in base_installer.py for interface details.
"""

def _unload_kvm_modules(mod_list):
    logging.info("Unloading previously loaded KVM modules")
    for module in reversed(mod_list):
        utils.unload_module(module)


def _load_kvm_modules(mod_list, module_dir=None, load_stock=False):
    """
    Just load the KVM modules, without killing Qemu or unloading previous
    modules.

    Load modules present on any sub directory of module_dir. Function will walk
    through module_dir until it finds the modules.

    @param module_dir: Directory where the KVM modules are located.
    @param load_stock: Whether we are going to load system kernel modules.
    @param extra_modules: List of extra modules to load.
    """
    if module_dir:
        logging.info("Loading the built KVM modules...")
        kvm_module_path = None
        kvm_vendor_module_path = None
        abort = False

        list_modules = ['%s.ko' % (m) for m in mod_list]

        list_module_paths = []
        for folder, subdirs, files in os.walk(module_dir):
            for module in list_modules:
                if module in files:
                    module_path = os.path.join(folder, module)
                    list_module_paths.append(module_path)

        # We might need to arrange the modules in the correct order
        # to avoid module load problems
        list_modules_load = []
        for module in list_modules:
            for module_path in list_module_paths:
                if os.path.basename(module_path) == module:
                    list_modules_load.append(module_path)

        if len(list_module_paths) != len(list_modules):
            logging.error("KVM modules not found. If you don't want to use the "
                          "modules built by this test, make sure the option "
                          "load_modules: 'no' is marked on the test control "
                          "file.")
            raise error.TestError("The modules %s were requested to be loaded, "
                                  "but the only modules found were %s" %
                                  (list_modules, list_module_paths))

        for module_path in list_modules_load:
            try:
                utils.system("insmod %s" % module_path)
            except Exception, e:
                raise error.TestFail("Failed to load KVM modules: %s" % e)

    if load_stock:
        logging.info("Loading current system KVM modules...")
        for module in mod_list:
            utils.system("modprobe %s" % module)


def create_symlinks(test_bindir, prefix=None, bin_list=None, unittest=None):
    """
    Create symbolic links for the appropriate qemu and qemu-img commands on
    the kvm test bindir.

    @param test_bindir: KVM test bindir
    @param prefix: KVM prefix path
    @param bin_list: List of qemu binaries to link
    @param unittest: Path to configuration file unittests.cfg
    """
    qemu_path = os.path.join(test_bindir, "qemu")
    qemu_img_path = os.path.join(test_bindir, "qemu-img")
    qemu_unittest_path = os.path.join(test_bindir, "unittests")
    if os.path.lexists(qemu_path):
        os.unlink(qemu_path)
    if os.path.lexists(qemu_img_path):
        os.unlink(qemu_img_path)
    if unittest and os.path.lexists(qemu_unittest_path):
        os.unlink(qemu_unittest_path)

    logging.debug("Linking qemu binaries")

    if bin_list:
        for bin in bin_list:
            if os.path.basename(bin) == 'qemu-kvm':
                os.symlink(bin, qemu_path)
            elif os.path.basename(bin) == 'qemu-img':
                os.symlink(bin, qemu_img_path)

    elif prefix:
        kvm_qemu = os.path.join(prefix, "bin", "qemu-system-x86_64")
        if not os.path.isfile(kvm_qemu):
            raise error.TestError('Invalid qemu path')
        kvm_qemu_img = os.path.join(prefix, "bin", "qemu-img")
        if not os.path.isfile(kvm_qemu_img):
            raise error.TestError('Invalid qemu-img path')
        os.symlink(kvm_qemu, qemu_path)
        os.symlink(kvm_qemu_img, qemu_img_path)

    if unittest:
        logging.debug("Linking unittest dir")
        os.symlink(unittest, qemu_unittest_path)


def install_roms(rom_dir, prefix):
    logging.debug("Path to roms specified. Copying roms to install prefix")
    rom_dst_dir = os.path.join(prefix, 'share', 'qemu')
    for rom_src in glob.glob('%s/*.bin' % rom_dir):
        rom_dst = os.path.join(rom_dst_dir, os.path.basename(rom_src))
        logging.debug("Copying rom file %s to %s", rom_src, rom_dst)
        shutil.copy(rom_src, rom_dst)


class KvmInstallException(Exception):
    pass


class FailedKvmInstall(KvmInstallException):
    pass


class KvmNotInstalled(KvmInstallException):
    pass


class BaseInstaller(object):
    # default value for load_stock argument
    load_stock_modules = True
    def __init__(self, mode=None):
        self.install_mode = mode
        self._full_module_list = None

    def set_install_params(self, test, params):
        self.params = params

        load_modules = params.get('load_modules', 'no')
        if not load_modules or load_modules == 'yes':
            self.should_load_modules = True
        elif load_modules == 'no':
            self.should_load_modules = False
        default_extra_modules = str(None)
        self.extra_modules = eval(params.get("extra_modules",
                                             default_extra_modules))

        self.cpu_vendor = virt_utils.get_cpu_vendor()

        self.srcdir = test.srcdir
        if not os.path.isdir(self.srcdir):
            os.makedirs(self.srcdir)

        self.test_bindir = test.bindir
        self.results_dir = test.resultsdir

        # KVM build prefix, for the modes that do need it
        prefix = os.path.join(test.bindir, 'build')
        self.prefix = os.path.abspath(prefix)

        # Current host kernel directory
        default_host_kernel_source = '/lib/modules/%s/build' % os.uname()[2]
        self.host_kernel_srcdir = params.get('host_kernel_source',
                                             default_host_kernel_source)

        # Extra parameters that can be passed to the configure script
        self.extra_configure_options = params.get('extra_configure_options',
                                                  None)

        # Do we want to save the result of the build on test.resultsdir?
        self.save_results = True
        save_results = params.get('save_results', 'no')
        if save_results == 'no':
            self.save_results = False

        self._full_module_list = list(self._module_list())



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
