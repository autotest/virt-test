import os
import re
import logging
import tempfile
from virttest import virsh
from virttest import data_dir
from virttest import utils_libvirtd
from virttest.libvirt_xml.vm_xml import VMXML
from autotest.client.shared import error


def get_pci_info():
    """
    Get infomation for all PCI devices including:
    1) whether device has reset under its sysfs dir.
    2) Whether device has driver dir under its sysfs dir.

    :return: A dict using libvirt canonical nodedev name as keys
             and dicts like {'reset': True, 'driver': True} as values
    """
    devices = {}
    pci_path = '/sys/bus/pci/devices'
    for device in os.listdir(pci_path):
        # Generate a virsh nodedev format device name
        dev_name = re.sub(r'\W', '_', 'pci_' + device)

        dev_path = os.path.join(pci_path, device)
        # Check whether device has `reset` file
        reset_path = os.path.join(dev_path, 'reset')
        has_reset = os.path.isfile(reset_path)

        # Check whether device has `driver` file
        driver_path = os.path.join(dev_path, 'driver')
        has_driver = os.path.isdir(driver_path)

        info = {'reset': has_reset, 'driver': has_driver}
        devices[dev_name] = info
    return devices


def test_nodedev_reset(devices, expect_succeed):
    """
    Test nodedev-reset command on a list of devices

    :param devices        : A list of node devices to be tested.
    :param expect_succeed : 'yes' for expect command run successfully
                           and 'no' for fail.
    :raise TestFail       : If result doesn't meet expectation.
    """
    for device in devices:
        result = virsh.nodedev_reset(device)
        logging.debug(result)

        # Check whether exit code match expectation.
        if (result.exit_status == 0) != (expect_succeed == 'yes'):
            raise error.TestFail(
                'Result do not meet expect_succeed (%s). Result:\n %s' %
                (expect_succeed, result))


def test_active_nodedev_reset(device, vm, expect_succeed):
    """
    Test nodedev-reset when the specified device is attached to a VM

    :param devices        : Specified node device to be tested.
    :param vm             : VM the device is to be attached to.
    :param expect_succeed : 'yes' for expect command run successfully
                            and 'no' for fail.
    :raise TestFail       : If result doesn't meet expectation.
    :raise TestError      : If failed to recover environment.
    """
    # Split device name such as `pci_0000_00_19_0` and fill the XML.
    hostdev_xml = """
<hostdev mode='subsystem' type='%s' managed='yes'>
    <source>
        <address domain='0x%s' bus='0x%s' slot='0x%s' function='0x%s'/>
    </source>
</hostdev>""" % tuple(device.split('_'))

    try:
        # The device need to be detached before attach to VM.
        virsh.nodedev_detach(device)
        try:
            # Backup VM XML.
            vmxml = VMXML.new_from_inactive_dumpxml(vm.name)

            # Generate a temp file to store host device XML.
            dev_fd, dev_fname = tempfile.mkstemp(dir=data_dir.get_tmp_dir())
            os.close(dev_fd)

            dev_file = open(dev_fname, 'w')
            dev_file.write(hostdev_xml)
            dev_file.close()

            # Only live VM allows attach device.
            if not vm.is_alive():
                vm.start()

            try:
                result = virsh.attach_device(vm.name, dev_fname)
                logging.debug(result)

                test_nodedev_reset([device], expect_succeed)
            finally:
                # Detach device from VM.
                result = virsh.detach_device(vm.name, dev_fname)
                # Raise error when detach failed.
                if result.exit_status:
                    raise error.TestError(
                        'Failed to dettach device %s from %s. Result:\n %s'
                        % (device, vm.name, result))
        finally:
            # Cleanup temp XML file and recover test VM.
            os.remove(dev_fname)
            vmxml.sync()
    finally:
        # Reattach node device
        result = virsh.nodedev_reattach(device)
        # Raise error when reattach failed.
        if result.exit_status:
            raise error.TestError(
                'Failed to reattach nodedev %s. Result:\n %s'
                % (device, result))


def run(test, params, env):
    """
    Test command: virsh nodedev-reset <device>

    When `device_option` is:
    1) resettable   : Reset specified device if it is resettable.
    2) non-exist    : Try to reset specified device which doesn't exist.
    3) non-pci      : Try to reset all local non-PCI devices.
    4) active       : Try to reset specified device which is attached to VM.
    5) unresettable : Try to reset all unresettable PCI devices.
    """
    # Retrive parameters
    expect_succeed = params.get('expect_succeed', 'yes')
    device_option = params.get('device_option', 'valid')
    unspecified = 'REPLACE_WITH_TEST_DEVICE'
    specified_device = params.get('specified_device', unspecified)

    # Backup original libvirtd status and prepare libvirtd status
    logging.debug('Preparing libvirtd')
    libvirtd = params.get("libvirtd", "on")
    libvirtd_status = utils_libvirtd.libvirtd_is_running()
    if libvirtd == "off" and libvirtd_status:
        utils_libvirtd.libvirtd_stop()
    elif libvirtd == "on" and not libvirtd_status:
        utils_libvirtd.libvirtd_start()

    # Get whether PCI devices are resettable from sysfs.
    devices = get_pci_info()

    # Devide PCI devices into to catagories.
    resettable_nodes = []
    unresettable_nodes = []
    for device in devices:
        info = devices[device]
        if info['reset'] and info['driver']:
            resettable_nodes.append(device)
        else:
            unresettable_nodes.append(device)

    # Find out all non-PCI devices.
    all_devices = virsh.nodedev_list().stdout.strip().splitlines()
    non_pci_nodes = []
    for device in all_devices:
        if device not in devices:
            non_pci_nodes.append(device)

    try:
        if device_option == 'resettable':
            # Test specified resettable device.
            if specified_device != unspecified:
                if specified_device in resettable_nodes:
                    test_nodedev_reset([specified_device], expect_succeed)
                else:
                    raise error.TestNAError(
                        'Param specified_device is not set!')
            else:
                raise error.TestNAError('Param specified_device is not set!')
        elif device_option == 'non-exist':
            # Test specified non-exist device.
            if specified_device != unspecified:
                if specified_device not in all_devices:
                    test_nodedev_reset([specified_device], expect_succeed)
                else:
                    raise error.TestError('Specified device exists!')
            else:
                raise error.TestNAError('Param specified_device is not set!')
        elif device_option == 'non-pci':
            # Test all non-PCI device.
            if non_pci_nodes:
                test_nodedev_reset(non_pci_nodes, expect_succeed)
            else:
                raise error.TestNAError('No non-PCI device found!')
        elif device_option == 'active':
            # Test specified device if attached to VM.
            if specified_device != unspecified:
                vm_name = params.get('main_vm', 'virt-tests-vm1')
                vm = env.get_vm(vm_name)
                test_active_nodedev_reset(
                    specified_device, vm, expect_succeed)
            else:
                raise error.TestNAError('Param specified_device is not set!')
        elif device_option == 'unresettable':
            # Test all unresettable device.
            if unresettable_nodes:
                test_nodedev_reset(unresettable_nodes, expect_succeed)
            else:
                raise error.TestNAError('No unresettable device found!')
        else:
            raise error.TestError(
                'Unrecognisable device option %s!' % device_option)
    finally:
        # Restore libvirtd status
        logging.debug('Restoring libvirtd')
        current_libvirtd_status = utils_libvirtd.libvirtd_is_running()
        if current_libvirtd_status and not libvirtd_status:
            utils_libvirtd.libvirtd_stop()
        elif not current_libvirtd_status and libvirtd_status:
            utils_libvirtd.libvirtd_start()
