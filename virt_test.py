import os, sys, logging, imp

from autotest.client import test
from autotest.client.shared import error
from autotest.client.virt import virt_utils, virt_env_process


class virt_test(test.test):
    """
    Shared test class infrastructure for tests such as the KVM test.

    It comprises a subtest load system, use of parameters, and an env
    file, all code that can be reused among those virt tests.
    """
    version = 1
    env_version = 1


    def initialize(self, params):
        # Change the value of the preserve_srcdir attribute according to
        # the value present on the configuration file (defaults to yes)
        if params.get("preserve_srcdir", "yes") == "yes":
            self.preserve_srcdir = True
        self.virtdir = os.path.dirname(sys.modules[__name__].__file__)


    def run_once(self, params):
        # Convert params to a Params object
        params = virt_utils.Params(params)

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
            self.write_test_keyval({key: params[key]})

        # Set the log file dir for the logging mechanism used by kvm_subprocess
        # (this must be done before unpickling env)
        virt_utils.set_log_file_dir(self.debugdir)

        # Open the environment file
        env_filename = os.path.join(self.bindir, params.get("env", "env"))
        env = virt_utils.Env(env_filename, self.env_version)

        test_passed = False

        try:
            try:
                try:
                    # Get the test routine corresponding to the specified
                    # test type
                    t_type = params.get("type")
                    # Verify if we have the correspondent source file for it
                    virt_dir = os.path.dirname(virt_utils.__file__)
                    subtest_dir_common = os.path.join(virt_dir, "tests")
                    subtest_dir_test = os.path.join(self.bindir, "tests")
                    subtest_dir = None
                    for d in [subtest_dir_test, subtest_dir_common]:
                        module_path = os.path.join(d, "%s.py" % t_type)
                        if os.path.isfile(module_path):
                            subtest_dir = d
                            break
                    if subtest_dir is None:
                        raise error.TestError("Could not find test file %s.py "
                                              "on either %s or %s directory" %
                                              (t_type, subtest_dir_test,
                                              subtest_dir_common))
                    # Load the test module
                    f, p, d = imp.find_module(t_type, [subtest_dir])
                    test_module = imp.load_module(t_type, f, p, d)
                    f.close()

                    # Preprocess
                    try:
                        virt_env_process.preprocess(self, params, env)
                    finally:
                        env.save()
                    # Run the test function
                    run_func = getattr(test_module, "run_%s" % t_type)
                    try:
                        run_func(self, params, env)
                    finally:
                        env.save()
                    test_passed = True

                except Exception, e:
                    logging.error("Test failed: %s: %s",
                                  e.__class__.__name__, e)
                    try:
                        virt_env_process.postprocess_on_error(
                            self, params, env)
                    finally:
                        env.save()
                    raise

            finally:
                # Postprocess
                try:
                    try:
                        virt_env_process.postprocess(self, params, env)
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
                        logging.info("'%s' has a %s monitor unix socket at: %s",
                                     vm.name, m.protocol, m.filename)
                    logging.info("The command line used to start '%s' was:\n%s",
                                 vm.name, vm.make_qemu_command())
                raise error.JobError("Abort requested (%s)" % e)
