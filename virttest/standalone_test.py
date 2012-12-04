import os, logging, imp, sys, time, traceback, Queue
from autotest.client.shared import error
from autotest.client import utils
import utils_misc, utils_params, utils_env, env_process, data_dir, bootstrap


class Test(object):
    """
    Mininal test class used to run a virt test.
    """

    env_version = utils_env.get_env_version()
    def __init__(self, params, options):
        self.params = utils_params.Params(params)
        self.bindir = data_dir.get_root_dir()
        self.testdir = os.path.join(self.bindir, 'tests')
        self.virtdir = os.path.join(self.bindir, 'shared')
        self.builddir = os.path.join(self.bindir, params.get("vm_type"))

        self.srcdir = os.path.join(self.builddir, 'src')
        if not os.path.isdir(self.srcdir):
            os.makedirs(self.srcdir)

        self.tmpdir = os.path.join(self.bindir, 'tmp')
        if not os.path.isdir(self.tmpdir):
            os.makedirs(self.tmpdir)

        self.iteration = 0
        if options.config is None:
            self.tag = ".".join(params['name'].split(".")[12:])
        else:
            self.tag = ".".join(params['shortname'].split("."))
        self.debugdir = None
        self.outputdir = None
        self.resultsdir = None
        self.logfile = None
        self.file_handler = None
        self.background_errors = Queue.Queue()


    def set_debugdir(self, debugdir):
        self.debugdir = os.path.join(debugdir, self.tag)
        self.outputdir = self.debugdir
        if not os.path.isdir(self.debugdir):
            os.makedirs(self.debugdir)
        self.resultsdir = os.path.join(self.debugdir, 'results')
        if not os.path.isdir(self.resultsdir):
            os.makedirs(self.resultsdir)
        utils_misc.set_log_file_dir(self.debugdir)
        self.logfile = os.path.join(self.debugdir, 'debug.log')


    def write_test_keyval(self, d):
        utils.write_keyval(self.debugdir, d)


    def start_file_logging(self):
        self.file_handler = configure_file_logging(self.logfile)


    def stop_file_logging(self):
        logger = logging.getLogger()
        logger.removeHandler(self.file_handler)


    def verify_background_errors(self):
        """
        Verify if there are any errors that happened on background threads.

        @raise Exception: Any exception stored on the background_errors queue.
        """
        try:
            exc = self.background_errors.get(block=False)
        except Queue.Empty:
            pass
        else:
            raise exc[1], None, exc[2]


    def run_once(self):
        params = self.params

        # If a dependency test prior to this test has failed, let's fail
        # it right away as TestNA.
        if params.get("dependency_failed") == 'yes':
            raise error.TestNAError("Test dependency failed")

        # Report the parameters we've received and write them as keyvals
        logging.debug("Test parameters:")
        keys = params.keys()
        keys.sort()
        for key in keys:
            logging.debug("    %s = %s", key, params[key])

        # Open the environment file
        env_filename = os.path.join(self.bindir, params.get("vm_type"),
                                    params.get("env", "env"))
        env = utils_env.Env(env_filename, self.env_version)

        test_passed = False

        try:
            try:
                try:
                    subtest_dirs = []
                    tests_dir = self.testdir

                    other_subtests_dirs = params.get("other_tests_dirs", "")
                    for d in other_subtests_dirs.split():
                        subtestdir = os.path.join(tests_dir, d, "tests")
                        if not os.path.isdir(subtestdir):
                            raise error.TestError("Directory %s does not "
                                                  "exist" % (subtestdir))
                        subtest_dirs.append(subtestdir)

                    # Verify if we have the correspondent source file for it
                    subtest_dirs.append(self.testdir)
                    specific_testdir = os.path.join(self.bindir,
                                                    params.get("vm_type"),
                                                    "tests")
                    subtest_dirs.append(specific_testdir)
                    subtest_dir = None

                    # Get the test routine corresponding to the specified
                    # test type
                    t_types = params.get("type").split()
                    test_modules = {}
                    for t_type in t_types:
                        for d in subtest_dirs:
                            module_path = os.path.join(d, "%s.py" % t_type)
                            if os.path.isfile(module_path):
                                subtest_dir = d
                                break
                        if subtest_dir is None:
                            msg = ("Could not find test file %s.py on test"
                                   "dirs %s" % (t_type, subtest_dirs))
                            raise error.TestError(msg)
                        # Load the test module
                        f, p, d = imp.find_module(t_type, [subtest_dir])
                        test_modules[t_type] = imp.load_module(t_type, f, p, d)
                        f.close()

                    # Preprocess
                    try:
                        env_process.preprocess(self, params, env)
                    finally:
                        env.save()

                    # Run the test function
                    for t_type, test_module in test_modules.items():
                        run_func = getattr(test_module, "run_%s" % t_type)
                        try:
                            run_func(self, params, env)
                            self.verify_background_errors()
                        finally:
                            env.save()
                    test_passed = True

                except Exception, e:
                    try:
                        env_process.postprocess_on_error(self, params, env)
                    finally:
                        env.save()
                    raise

            finally:
                # Postprocess
                try:
                    try:
                        env_process.postprocess(self, params, env)
                    except Exception, e:
                        if test_passed:
                            raise
                        logging.error("Exception raised during "
                                      "postprocessing: %s", e)
                finally:
                    env.save()

        except Exception, e:
            if params.get("abort_on_error") != "yes":
                raise
            # Abort on error
            logging.info("Aborting job (%s)", e)
            if params.get("vm_type") == "kvm":
                for vm in env.get_all_vms():
                    if vm.is_dead():
                        continue
                    logging.info("VM '%s' is alive.", vm.name)
                    for m in vm.monitors:
                        logging.info("It has a %s monitor unix socket at: %s",
                                     m.protocol, m.filename)
                    logging.info("The command line used to start it was:\n%s",
                                 vm.make_qemu_command())
                raise error.JobError("Abort requested (%s)" % e)

        return test_passed


def print_stdout(sr, end=True):
    try:
        sys.stdout.switch()
    except AttributeError:
        pass
    if end:
        print(sr)
    else:
        print(sr),
    try:
        sys.stdout.switch()
    except AttributeError:
        pass


class Bcolors(object):
    """
    Very simple class with color support.
    """

    def __init__(self):
        self.HEADER = '\033[94m'
        self.PASS = '\033[92m'
        self.SKIP = '\033[93m'
        self.FAIL = '\033[91m'
        self.WARN = '\033[93m'
        self.ENDC = '\033[0m'
        allowed_terms = ['linux', 'xterm', 'xterm-256color', 'vt100']
        term = os.environ.get("TERM")
        if (not os.isatty(1)) or (not term in allowed_terms):
            self.disable()

    def disable(self):
        self.HEADER = ''
        self.PASS = ''
        self.SKIP = ''
        self.FAIL = ''
        self.ENDC = ''

# Instantiate bcolors to be used in the functions below.
bcolors = Bcolors()


def print_header(sr):
    """
    Print a string to stdout with HEADER (blue) color.
    """
    print_stdout(bcolors.HEADER + sr + bcolors.ENDC)


def print_skip():
    """
    Print SKIP to stdout with SKIP (yellow) color.
    """
    print_stdout(bcolors.SKIP + "SKIP" + bcolors.ENDC)


def print_pass(t_elapsed):
    """
    Print PASS to stdout with PASS (green) color.
    """
    print_stdout(bcolors.PASS + "PASS" + bcolors.ENDC + " (%.2f s)" % t_elapsed)


def print_fail(t_elapsed):
    """
    Print FAIL to stdout with FAIL (red) color.
    """
    print_stdout(bcolors.FAIL + "FAIL" + bcolors.ENDC + " (%.2f s)" % t_elapsed)


def print_warn(t_elapsed):
    """
    Print WARN to stdout with WARN (yellow) color.
    """
    print_stdout(bcolors.WARN + "WARN" + bcolors.ENDC + " (%.2f s)" % t_elapsed)


def configure_logging():
    """
    Remove all the handlers on the root logger
    """
    logger = logging.getLogger()
    for hdlr in logger.handlers:
        logger.removeHandler(hdlr)


def configure_console_logging():
    """
    Simple helper for adding a file logger to the root logger.
    """
    logger = logging.getLogger()
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)

    fmt = '%(asctime)s %(levelname)-5.5s| %(message)s'
    formatter = logging.Formatter(fmt=fmt, datefmt='%H:%M:%S')

    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return stream_handler


def configure_file_logging(logfile):
    """
    Simple helper for adding a file logger to the root logger.
    """
    logger = logging.getLogger()
    file_handler = logging.FileHandler(filename=logfile)
    file_handler.setLevel(logging.DEBUG)

    fmt = '%(asctime)s %(levelname)-5.5s| %(message)s'
    formatter = logging.Formatter(fmt=fmt, datefmt='%H:%M:%S')

    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return file_handler


def create_config_files(options):
    """
    Check if the appropriate configuration files are present.

    If the files are not present, create them.

    @param options: OptParser object with options.
    """
    shared_dir = os.path.dirname(data_dir.get_data_dir())
    test_dir = os.path.dirname(shared_dir)
    shared_dir = os.path.join(shared_dir, "cfg")

    if (options.type and options.config):
        test_dir = os.path.join(test_dir, options.type)
    elif options.type:
        test_dir = os.path.join(test_dir, options.type)
    elif options.config:
        parent_config_dir = os.path.dirname(options.config)
        parent_config_dir = os.path.basename(parent_config_dir)
        test_dir = os.path.join(test_dir, parent_config_dir)

    bootstrap.create_config_files(test_dir, shared_dir, interactive=False)


def bootstrap_tests(options):
    """
    Bootstrap process (download the appropriate JeOS file to data dir).

    This function will check whether the JeOS is in the right location of the
    data dir, if not, it will download it non interactively.

    @param options: OptParse object with program command line options.
    """
    test_dir = os.path.dirname(sys.modules[__name__].__file__)

    if options.type:
        test_dir = os.path.abspath(os.path.join(os.path.dirname(test_dir),
                                                options.type))
    elif options.config:
        test_dir = os.path.dirname(os.path.dirname(options.config))
        test_dir = os.path.abspath(test_dir)

    check_modules = ["kvm", "kvm-%s" % utils_misc.get_cpu_vendor(verbose=False)]
    online_docs_url = "https://github.com/autotest/virt-test/wiki"

    kwargs = {'test_name': options.type,
              'test_dir': test_dir,
              'base_dir': data_dir.get_data_dir(),
              'default_userspace_paths': None,
              'check_modules': check_modules,
              'online_docs_url': online_docs_url,
              'restore_image': options.restore,
              'interactive': False}

    # Tolerance we have without printing a message for the user to wait (3 s)
    tolerance = 3
    failed = False
    wait_message_printed = False

    bg = utils.InterruptedThread(bootstrap.bootstrap, kwargs=kwargs)
    t_begin = time.time()
    bg.start()

    while bg.isAlive():
        t_elapsed = time.time() - t_begin
        if t_elapsed > tolerance and not wait_message_printed:
            print_stdout("Running setup. Please wait...")
            wait_message_printed = True
        time.sleep(0.1)

    reason = None
    try:
        bg.join()
    except Exception, e:
        failed = True
        reason = e

    t_end = time.time()
    t_elapsed = t_end - t_begin

    print_stdout(bcolors.HEADER + "SETUP:" + bcolors.ENDC, end=False)

    if not failed:
        print_pass(t_elapsed)
    else:
        print_fail(t_elapsed)
        print_stdout("Setup error: %s" % reason)
        sys.exit(-1)

    return True


def run_tests(parser, options):
    """
    Runs the sequence of KVM tests based on the list of dctionaries
    generated by the configuration system, handling dependencies.

    @param parser: Config parser object.
    @return: True, if all tests ran passed, False if any of them failed.
    """
    debugdir = os.path.join(data_dir.get_root_dir(), 'logs',
                            'run-%s' % time.strftime('%Y-%m-%d-%H.%M.%S'))
    if not os.path.isdir(debugdir):
        os.makedirs(debugdir)
    debuglog = os.path.join(debugdir, "debug.log")
    configure_file_logging(debuglog)

    print_stdout(bcolors.HEADER +
                 "DATA DIR: %s" % data_dir.get_backing_data_dir() +
                 bcolors.ENDC)

    print_header("DEBUG LOG: %s" % debuglog)

    last_index = -1

    # Clean environment file
    d = parser.get_dicts().next()
    env_filename = os.path.join(data_dir.get_root_dir(),
                                options.type, d.get("env", "env"))
    env = utils_env.Env(env_filename, Test.env_version)
    env.destroy()

    for i, d in enumerate(parser.get_dicts()):
        if options.config is None:
            shortname = ".".join(d['name'].split(".")[12:])
        else:
            shortname = ".".join(d['shortname'].split("."))

        logging.info("Test %4d:  %s" % (i + 1, shortname))
        last_index += 1

    if last_index == -1:
        print_stdout("No tests generated by config file %s" % parser.filename)
        print_stdout("Please check the file for errors (bad variable names, "
                     "wrong indentation)")
        sys.exit(-1)

    n_tests = last_index + 1
    print_header("TESTS: %s" % n_tests)

    status_dct = {}
    failed = False
    # Add the parameter decide if setup host env in the test case
    # For some special tests we only setup host in the first and last case
    # When we need to setup host env we need the host_setup_flag as following:
    #    0(00): do nothing
    #    1(01): setup env
    #    2(10): cleanup env
    #    3(11): setup and cleanup env
    index = 0
    setup_flag = 1
    cleanup_flag = 2
    for dct in parser.get_dicts():
        if options.config is None:
            shortname = ".".join(d['name'].split(".")[12:])
        else:
            shortname = ".".join(d['shortname'].split("."))

        if index == 0:
            if dct.get("host_setup_flag", None) is not None:
                flag = int(dct["host_setup_flag"])
                dct["host_setup_flag"] = flag | setup_flag
            else:
                dct["host_setup_flag"] = setup_flag
        if index == last_index:
            if dct.get("host_setup_flag", None) is not None:
                flag = int(dct["host_setup_flag"])
                dct["host_setup_flag"] = flag | cleanup_flag
            else:
                dct["host_setup_flag"] = cleanup_flag
        index += 1

        # Add kvm module status
        dct["kvm_default"] = utils_misc.get_module_params(
                                             dct.get("sysfs_dir", "sys"), "kvm")

        if dct.get("skip") == "yes":
            continue

        dependencies_satisfied = True
        for dep in dct.get("dep"):
            for test_name in status_dct.keys():
                if not dep in test_name:
                    continue

                if not status_dct[test_name]:
                    dependencies_satisfied = False
                    break

        current_status = False
        if dependencies_satisfied:
            t = Test(dct, options)
            t.set_debugdir(debugdir)

            print_stdout("%s:" % t.tag, end=False)

            try:
                try:
                    t_begin = time.time()
                    t.start_file_logging()
                    current_status = t.run_once()
                    logging.info("PASS")
                    t.stop_file_logging()
                finally:
                    t_end = time.time()
                    t_elapsed = t_end - t_begin
            except error.TestNAError, reason:
                logging.info("SKIP -> %s: %s", reason.__class__.__name__,
                             reason)
                t.stop_file_logging()
                print_skip()
                status_dct[dct.get("name")] = False
                continue
            except error.TestWarn, reason:
                logging.info("WARN -> %s: %s", reason.__class__.__name__,
                             reason)
                t.stop_file_logging()
                print_warn(t_elapsed)
                status_dct[dct.get("name")] = True
                continue
            except Exception, reason:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                logging.error("")
                tb_info = traceback.format_exception(exc_type, exc_value,
                                                     exc_traceback.tb_next)
                tb_info = "".join(tb_info)
                for e_line in tb_info.splitlines():
                    logging.error(e_line)
                logging.error("")
                logging.error("FAIL -> %s: %s", reason.__class__.__name__,
                              reason)
                t.stop_file_logging()
                current_status = False
        else:
            if options.config is None:
                shortname = ".".join(d['name'].split(".")[12:])
            else:
                shortname = ".".join(d['shortname'].split("."))
            print_stdout("%s:" % shortname, end=False)
            print_skip()
            status_dct[dct.get("name")] = False
            continue

        if not current_status:
            failed = True
            print_fail(t_elapsed)

        else:
            print_pass(t_elapsed)

        status_dct[dct.get("name")] = current_status

    return not failed
