import logging
import re
from autotest.client.shared import error


@error.context_aware
def run_check_roms(test, params, env):
    """
    QEMU check roms test:

    1) start VM with additional option ROMS
    2) run "info roms" in qemu monitor
    3) check the roms are loaded once not twice

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment
    """
    error.context("start VM with additional option roms", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    fw_filter = params["fw_filter"]
    addr_filter = params["addr_filter"]

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

    logging.info("ROMS reported by firmware: '%s'", list_fw)
    logging.info("ROMS reported by QEMU: '%s'", list_addr)

    error.context("check result for the roms", logging.info)
    ret = set(list_fw).intersection(list_addr)
    if ret:
        raise error.TestFail("ROM '%s' is intended to be loaded by the firmware, "
                             "but is was also loaded by QEMU itself." % ret)
