import logging, re
from autotest.client.shared import error

@error.context_aware
def run_check_roms(test, params, env):
    """
    KVM Autotest check roms:
    1) start VM with additional option roms
    2) run "info roms" in qemu monitor
    3) check the roms are loaded once not twice

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """

    error.context("start VM with additional option roms", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    fw_filter = params.get("fw_filter")
    addr_filter = params.get("addr_filter")
    if not fw_filter:
        raise error.TestError("Could not get fw_filter param.")
    if not addr_filter:
        raise error.TestError("Could not get addr_filter param.")

    error.context("run 'info roms' in qemu monitor", logging.info)
    o = vm.monitor.info("roms")

    # list_fw means rom being loaded by firmware
    # list_addr means rom being loaded by QEMU itself
    list_fw = []
    list_addr = []

    patt = re.compile(r'%s' % fw_filter, re.M)
    list_fw = patt.findall(str(o))

    patt = re.compile(r'%s' % addr_filter, re.M)
    list_addr = patt.findall(str(o))

    logging.info("Got roms by firmware: '%s'", list_fw)
    logging.info("Got roms by qemu: '%s'", list_addr)

    error.context("check result for the roms", logging.info)
    ret = set(list_fw).intersection(list_addr)
    if ret:
        raise error.TestFail("Rom: '%s' is intended to be loaded by the bios,"
                             " but is also loaded by qemu itself." % ret)
