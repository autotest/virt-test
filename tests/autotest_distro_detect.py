import os
import tempfile
import string
from virttest import utils_test


def generate_control_file(params):
    control_template = '''AUTHOR = "Cleber Rosa <crosa@redhat.com>"
NAME = "Distro Detect"
TIME = "SHORT"
TEST_CATEGORY = "Functional"
TEST_CLASS = "General"
TEST_TYPE = "client"

DOC = """
This test checks for the accuracy of the distro detection code of autotest
"""

import logging
from autotest.client.shared import distro


def step_init():
    job.next_step(step_test)


def step_test():
    expected_name = '$distro_name'
    expected_version = '$distro_version'
    expected_release = '$distro_release'
    expected_arch = '$distro_arch'

    detected = distro.detect()
    failures = []

    logging.debug("Expected distro name = %s", expected_name)
    logging.debug("Detected distro name = %s", detected.name)
    if expected_name != detected.name:
        failures.append("name")

    logging.debug("Expected distro version = %s", expected_version)
    logging.debug("Detected distro version = %s", detected.version)
    if expected_version != str(detected.version):
        failures.append("version")

    logging.debug("Expected distro release = %s", expected_release)
    logging.debug("Detected distro release = %s", detected.release)
    if expected_release != str(detected.release):
        failures.append("release")

    logging.debug("Expected distro arch = %s", expected_arch)
    logging.debug("Detected distro arch = %s", detected.arch)
    if expected_arch != detected.arch:
        failures.append("arch")

    if failures:
        msg = "Detection failed for distro: %s" % ", ".join(failures)
        raise error.TestFail(msg)

'''
    temp_fd, temp_path = tempfile.mkstemp()
    template = string.Template(control_template)
    control = template.substitute(params)
    os.write(temp_fd, control)
    os.close(temp_fd)
    return temp_path


def run_autotest_distro_detect(test, params, env):
    """
    Run an distro detection check on guest

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    # Collect test parameters
    timeout = int(params.get("test_timeout", 90))
    control_path = generate_control_file(params)
    outputdir = test.outputdir

    utils_test.run_autotest(vm, session, control_path, timeout, outputdir,
                            params)
