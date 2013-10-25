import re
import logging
from autotest.client import utils
from autotest.client.shared import error
from virttest import utils_misc

@error.context_aware
def run_qemu_option_check(test, params, env):
    """
    QEMU support options check test

    Test Step:
        1) Get qemu support device options
        2) Check whether is in line with ecpection

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def get_qemu_support_device(qemu_binary):
        """
        Get qemu support device list
        """
        support_device = utils.system_output("%s -device ? 2>&1"
                                              % qemu_binary, timeout=10,
                                              ignore_status=True)
        if not support_device:
            raise error.TestNAError("Can not get qemu support device list")
        device_list = re.findall(r'name\s+"(.*)",', support_device)
        device_list_alias = re.findall(r'alias\s+"(.*?)"', support_device)
        device_list.extend(device_list_alias)
        return device_list


    def get_device_option(qemu_binary, device_name):
        """
        Get qemu device 'device_name' support options
        """
        if device_name not in get_qemu_support_device(qemu_binary):
            err_msg = "Oops, Your qemu version doesn't support devic '%s', "
            err_msg += "make sure you have inputted a correct device name"
            raise error.TestNAError(err_msg % device_name)
        device_support_option = utils.system_output("%s -device %s,? 2>&1" %
                                                    (qemu_binary, device_name),
                                                    timeout=10,
                                                    ignore_status=True)

        device_option_key_value_list = re.findall(".*?\.(.*)=(.*)",
                                                  device_support_option)
        return device_option_key_value_list


    device_name = params.get("device_name")
    expect_option = params.get("expect_option")
    expect_option_key_value = re.findall(".*?\.(.*?)=(.*?)\s+", expect_option)
    qemu_binary = utils_misc.get_qemu_binary(params)

    error.context("Get qemu support %s device options" % device_name,
                  logging.info)
    qemu_support_option = get_device_option(qemu_binary, device_name)

    error.context("Check if qemu support options is in line with expection",
                  logging.info)
    qemu_support_option_set = set(qemu_support_option)
    expect_support_option_set = set(expect_option_key_value)
    if qemu_support_option_set != expect_support_option_set:
        fail_msg = "Qemu support option not in line with expection, "
        if qemu_support_option_set - expect_support_option_set:
            fail_msg += ("qemu support option %s, but it is not expect;\n" %
                         list(qemu_support_option_set -
                              expect_support_option_set))
        if expect_support_option_set - qemu_support_option_set:
            fail_msg += ("qemu not support %s, but it is expected." %
                          list(expect_support_option_set -
                               qemu_support_option_set))
        raise error.TestFail(fail_msg)

    logging.info("Qemu support device %s option is in line with expection" %
                 device_name)
