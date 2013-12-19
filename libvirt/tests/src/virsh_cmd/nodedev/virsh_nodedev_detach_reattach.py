import os
import logging
from autotest.client.shared import error
from virttest import virsh
from virttest.libvirt_xml import nodedev_xml


def driver_readlink(device_name):
    """
    readlink the driver of device.
    """
    nodedevxml = nodedev_xml.NodedevXML.new_from_dumpxml(device_name)
    driver_path = ('%s/driver') % (nodedevxml.get_sysfs_path())
    try:
        driver = os.readlink(driver_path)
    except (OSError, UnicodeError):
        return None
    return driver


def do_nodedev_detach_reattach(device_name, options=""):
    """
    do the detach and reattach.

    (1).do detach.
    (2).check the result of detach.
    (3).do reattach.
    (4).check the result of reattach
    """
    # do the detach
    logging.debug('Node device name is %s.', device_name)
    CmdResult = virsh.nodedev_detach(device_name, options)
    # check the exit_status.
    if CmdResult.exit_status:
        raise error.TestFail("Failed to detach %s.\n"
                             "Detail: %s."
                             % (device_name, CmdResult.stderr))
    # check the driver.
    driver = driver_readlink(device_name)
    logging.debug('Driver after detach is %s.', driver)
    if (driver is None) or (not driver.endswith('pci-stub')):
        raise error.TestFail("Driver for %s is not pci-stub "
                             "after nodedev-detach" % (device_name))
    else:
        pass
    logging.debug('Nodedev-detach %s successed.', device_name)
    # do the reattach.
    CmdResult = virsh.nodedev_reattach(device_name, options)
    # check the exit_status.
    if CmdResult.exit_status:
        raise error.TestFail("Failed to reattach %s.\n"
                             "Detail: %s."
                             % (device_name, CmdResult.stderr))
    # check the driver.
    driver = driver_readlink(device_name)
    if (driver is None) or (not driver.endswith('pci-stub')):
        pass
    else:
        raise error.TestFail("Driver for %s is not be reset after "
                             "nodedev-reattach" % (device_name))
    logging.debug('Nodedev-reattach %s successed.', device_name)


def run(test, params, env):
    """
    Test virsh nodedev-detach and virsh nodedev-reattach

    (1).Init variables for test.
    (2).Check variables.
    (3).do nodedev_detach_reattach.
    """
    # Init variables
    device_name = params.get('nodedev_device_name', 'ENTER.YOUR.PCI.DEVICE')
    device_opt = params.get('nodedev_device_opt', '')
    status_error = ('yes' == params.get('status_error', 'no'))
    # check variables.
    if device_name.count('ENTER'):
        raise error.TestNAError('Param device_name is not configured.')
    # do nodedev_detach_reattach
    try:
        do_nodedev_detach_reattach(device_name, device_opt)
    except error.TestFail, e:
        # Do nodedev detach and reattach failed.
        if status_error:
            return
        else:
            raise error.TestFail("Test failed in positive case."
                                 "error: %s" % e)
    # Do nodedev detach and reattach success.
    if status_error:
        raise error.TestFail('Test successed in negative case.')
