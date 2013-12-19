import logging
import re
import time
from autotest.client.shared import error
from virttest import utils_test


@error.context_aware
def run(test, params, env):
    """
    KVM driver load test:
    1) Log into a guest
    2) Get the driver device id(Windows) or module name(Linux) from guest
    3) Unload/load the device driver
    4) Check if the device still works properly(Optinal)
    5) Repeat step 3-4 several times

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error.context("Try to log into guest.", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    # Use the last nic for send driver load/unload command
    nics = vm.virtnet
    nic_index = len(vm.virtnet) - 1
    session = vm.wait_for_login(nic_index=nic_index, timeout=timeout)

    driver_id_cmd = params["driver_id_cmd"]
    driver_id_pattern = params["driver_id_pattern"]
    driver_load_cmd = params["driver_load_cmd"]
    driver_unload_cmd = params["driver_unload_cmd"]

    error.context("Get the driver module infor from guest.", logging.info)
    output = session.cmd_output(driver_id_cmd)
    driver_id = re.findall(driver_id_pattern, output)
    if not driver_id:
        raise error.TestError("Can not find driver module info from guest:"
                              "%s" % output)

    driver_id = driver_id[0]
    if params["os_type"] == "windows":
        driver_id = '^&'.join(driver_id.split('&'))
    driver_load_cmd = driver_load_cmd.replace("DRIVER_ID", driver_id)
    driver_unload_cmd = driver_unload_cmd.replace("DRIVER_ID", driver_id)

    for repeat in range(0, int(params.get("repeats", "1"))):
        error.context("Unload and load the driver. Round %s" % repeat,
                      logging.info)
        session.cmd(driver_unload_cmd)
        time.sleep(5)
        session.cmd(driver_load_cmd)
        time.sleep(5)
        if params.get("test_after_load"):
            test_after_load = params.get("test_after_load")
            utils_test.run_virt_sub_test(test, params, env,
                                         sub_type=test_after_load)
