import logging
from autotest.client.shared import error
from virttest import aexpect

@error.context_aware
def run_pxe(test, params, env):
    """
    PXE test:

    1) Login to guest
    2) Try to boot from PXE
    3) Analyzing the tcpdump result

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    error.context("Login to guest", logging.info)
    timeout = int(params.get("pxe_timeout", 60))

    error.context("Try to boot from PXE", logging.info)
    output = aexpect.run_fg("tcpdump -nli %s" % vm.get_ifname(),
                                   logging.debug, "(pxe capture) ", timeout)[1]

    error.context("Analyzing the tcpdump result", logging.info)
    if not "tftp" in output:
        raise error.TestFail("Couldn't find any TFTP packets after %s seconds" %
                             timeout)
    logging.info("Found TFTP packet")
