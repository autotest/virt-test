"""
Group of cpuid tests for X86 CPU
"""
import logging, re, sys, traceback, os
from autotest.client.shared import error, utils
from autotest.client.shared import test as test_module
from virttest import utils_misc, env_process


def run_cpuid(test, params, env):
    """
    Boot guest with different cpu_models and cpu flags and check if guest works correctly.

    @param test: kvm test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    qemu_binary = utils_misc.get_path('.', params.get("qemu_binary", "qemu"))

    class MiniSubtest(test_module.Subtest):
        """
        subtest base class for actual tests
        """
        def __new__(cls, *args, **kargs):
            self = test.__new__(cls)
            ret = None
            if args is None:
                args = []
            try:
                ret = self.test(*args, **kargs)
            finally:
                if hasattr(self, "clean"):
                    self.clean()
            return ret

        def clean(self):
            """
            cleans up running VM instance
            """
            if (hasattr(self, "vm")):
                vm = getattr(self, "vm")
                if vm.is_alive():
                    vm.pause()
                    vm.destroy(gracefully=False)

        def test(self):
            """
            stub for actual test code
            """
            raise error.TestFail("test() must be redifined in subtest")

    def print_exception(called_object):
        """
        print error including stack trace
        """
        exc_type, exc_value, exc_traceback = sys.exc_info()
        logging.error("In function (" + called_object.__name__ + "):")
        logging.error("Call from:\n" +
                      traceback.format_stack()[-2][:-1])
        logging.error("Exception from:\n" +
                      "".join(traceback.format_exception(
                                              exc_type, exc_value,
                                              exc_traceback.tb_next)))

    def extract_qemu_cpu_models(qemu_cpu_help_text):
        """
        Get all cpu models from qemu -cpu help text.

        @param qemu_cpu_help_text: text produced by <qemu> -cpu ?
        @return: list of cpu models
        """

        cpu_re = re.compile("x86\s+\[?([a-zA-Z0-9_-]+)\]?.*\n")
        return cpu_re.findall(qemu_cpu_help_text)

    class test_qemu_cpu_models_list(MiniSubtest):
        """
        check CPU models returned by <qemu> -cpu ? are what is expected
        """
        def test(self):
            """
            test method
            """
            if params.get("cpu_models") is None:
                raise error.TestNAError("define cpu_models parameter to check "
                                        "supported CPU models list")

            cmd = qemu_binary + " -cpu ?"
            result = utils.run(cmd)

            qemu_models = extract_qemu_cpu_models(result.stdout)
            cpu_models = params.get("cpu_models").split()
            missing = set(cpu_models) - set(qemu_models)
            if missing:
                raise error.TestFail("CPU models %s are not in output "
                                     "of command %s\n%s" %
                                     (missing, cmd, result.stdout))
            added = set(qemu_models) - set(cpu_models)
            if added:
                raise error.TestFail("Unexpected CPU models %s are in output "
                                     "of command %s\n%s" %
                                     (added, cmd, result.stdout))


    # subtests runner
    test_type = params.get("test_type")
    failed = []
    if test_type in locals():
        tests_group = locals()[test_type]
        try:
            tests_group()
        except:
            print_exception(tests_group)
            failed.append(test_type)
    else:
        raise error.TestError("Test group '%s' is not defined in"
                              " test" % test_type)

    if failed != []:
        raise error.TestFail("Test of cpu models %s failed." %
                              (str(failed)))
