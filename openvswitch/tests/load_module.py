import sys
import traceback
import logging
from autotest.client.shared import openvswitch, error, utils


@error.context_aware
def run_load_module(test, params, env):
    """
    Run basic test of OpenVSwitch driver.
    """
    _e = None
    ovs = None
    try:
        try:
            error.context("Remove all bridge from OpenVSwitch.")
            ovs = openvswitch.OpenVSwitch(test.tmpdir)
            ovs.init_system()
            ovs.check()
            for br in ovs.list_br():
                ovs.del_br(br)

            ovs.clean()

            for _ in range(int(params.get("mod_loaditer", 100))):
                utils.run("modprobe openvswitch")
                utils.run("rmmod openvswitch")

        except Exception:
            _e = sys.exc_info()
            raise
    finally:
        try:
            if ovs:
                if ovs.cleanup:
                    ovs.clean()
        except Exception:
            e = sys.exc_info()
            if _e is None:
                raise
            else:
                logging.error("Cleaning function raised exception too: \n" +
                              "".join(traceback.format_exception(e[0],
                                                                 e[1],
                                                                 e[2])))
                raise _e[0], _e[1], _e[2]
