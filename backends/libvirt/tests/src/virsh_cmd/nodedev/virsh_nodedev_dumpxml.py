import logging
from autotest.client import utils
from autotest.client.shared import error
from virttest import virsh
from virttest.libvirt_xml import nodedev_xml


def do_nodedev_dumpxml(dev_name, dev_opt=""):
    """
    Do dumpxml and check the result.

    (1).execute nodedev-dumpxml command.
    (2).compare info in xml with info in sysfs.

    :param dev_name: name of device.
    :raise TestFail: if execute command failed
                     or check result failed.
    """
    result = virsh.nodedev_dumpxml(dev_name, options=dev_opt)
    if result.exit_status:
        raise error.TestError("Dumpxml node device %s failed.\n"
                              "Detail:%s." % (dev_name, result.stderr))
    logging.debug('Executing "virsh nodedev-dumpxml %s" finished.', dev_name)
    # compare info in xml with info in sysfs.
    nodedevxml = nodedev_xml.NodedevXML.new_from_dumpxml(dev_name)
    if not nodedevxml.validates:
        raise error.TestError("nodedvxml of %s is not validated." % (dev_name))
    # Get the dict of key to value in xml.
    # key2value_dict_xml contain the all keys and values in xml need checking.
    key2value_dict_xml = nodedevxml.get_key2value_dict()
    # Get the dict of key to path in sysfs.
    # key2syspath_dict contain the all keys and the path of file which contain
    #                 information for each key.
    key2syspath_dict = nodedevxml.get_key2syspath_dict()
    # Get the values contained in files.
    # key2value_dict_sys contain the all keys and values in sysfs.
    key2value_dict_sys = {}
    for key, filepath in key2syspath_dict.items():
        value = utils.read_one_line(filepath)
        key2value_dict_sys[key] = value

    # Compare the value in xml and in syspath.
    for key in key2value_dict_xml:
        value_xml = key2value_dict_xml.get(key)
        value_sys = key2value_dict_sys.get(key)
        if not value_xml == value_sys:
            raise error.TestError("key: %s in xml is %s,"
                                  "but in sysfs is %s." %
                                 (key, value_xml, value_sys))
        else:
            continue

    logging.debug("Compare info in xml and info in sysfs finished"
                  "for device %s.", dev_name)


def run(test, params, env):
    """
    Test command virsh nodedev-dumpxml.

    (1).get param from params.
    (2).do nodedev dumpxml.
    (3).clean up.
    """
    # Init variables.
    status_error = ('yes' == params.get('status_error', 'no'))
    device_name = params.get('nodedev_device_name', None)
    device_opt = params.get('nodedev_device_opt', "")

    # do nodedev dumpxml.
    try:
        do_nodedev_dumpxml(dev_name=device_name, dev_opt=device_opt)
        if status_error:
            raise error.TestFail('Nodedev dumpxml successed in negative test.')
        else:
            pass
    except error.TestError, e:
        if status_error:
            pass
        else:
            raise error.TestFail('Nodedev dumpxml failed in positive test.'
                                 'Error: %s' % e)
