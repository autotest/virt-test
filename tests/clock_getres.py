import logging
import os
from autotest.client.shared import error
from virttest import utils_test


@error.context_aware
def run(test, params, env):
    """
    Verify if guests using kvm-clock as the time source have a sane clock
    resolution.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    source_name = "test_clock_getres/test_clock_getres.c"
    source_name = os.path.join(test.virtdir, "deps", source_name)
    dest_name = "/tmp/test_clock_getres.c"
    bin_name = "/tmp/test_clock_getres"

    if not os.path.isfile(source_name):
        raise error.TestError("Could not find %s" % source_name)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    vm.copy_files_to(source_name, dest_name)
    session.cmd("gcc -lrt -o %s %s" % (bin_name, dest_name))
    session.cmd(bin_name)
    logging.info("PASS: Guest reported appropriate clock resolution")
    sub_test = params.get("sub_test")
    if sub_test:
        error.context("Run sub test '%s' after checking"
                      " clock resolution" % sub_test, logging.info)
        utils_test.run_virt_sub_test(test, params, env, sub_test)
