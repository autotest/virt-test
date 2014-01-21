import re
import os
import shutil
import logging
from autotest.client.shared import error
from virttest import virsh
from virttest.libvirt_xml import VMXML


def create_attach_xml(update_xmlfile, source_iso):
    """
    Create a xml file to update a device.

    :param update_xmlfile : path/file to save device XML
    :param source_iso : disk's source backing file.
    """
    try:
        _file = open(source_iso, 'wb')
        _file.seek((1024 * 1024) - 1)
        _file.write(str(0))
        _file.close()
    except IOError:
        raise error.TestFail("Create source_iso failed!")
    disk_class = VMXML.get_device_class('disk')
    disk = disk_class(type_name='file')
    # Static definition for comparison in check_attach()
    disk.device = 'cdrom'
    disk.driver = dict(name='file')
    disk.source = disk.new_disk_source(attrs={'file': source_iso})
    disk.target = dict(bus='ide', dev='hdc')
    disk.readonly = True
    shutil.copyfile(disk.xml, update_xmlfile)


def is_attached(vmxml_devices, source_file):
    """
    Check attached device and disk exist or not.

    :param source_file : disk's source file to check
    :param vmxml_devices: VMXMLDevices instance
    :return: True/False if backing file and device found
    """
    disks = vmxml_devices.by_device_tag('disk')
    for disk in disks:
        if disk.device != 'cdrom':
            continue
        if disk.target['dev'] != 'hdc':
            continue
        if disk.source.attrs['file'] != source_file:
            continue
        # All three conditions met
        return True
    logging.error('No cdrom device for "%s" in devices XML: "%s"',
                  source_file, vmxml_devices)
    return False


def libvirt_library_version():
    """Parse and return tuple of libvirt's x.y.z version numbers"""
    try:
        regex = r'[Uu]sing\s*[Ll]ibrary:\s*[Ll]ibvirt\s*'
        regex += r'(\d+)\.(\d+)\.(\d+)'
        lines = virsh.version().splitlines()
        ver_x = ver_y = ver_z = None
        for line in lines:
            mobj = re.search(regex, line)
            if bool(mobj):
                ver_x = int(mobj.group(1))
                ver_y = int(mobj.group(2))
                ver_z = int(mobj.group(3))
                break
        return (ver_x, ver_y, ver_z)
    except (ValueError, TypeError, AttributeError):
        # Early versions didn't have 'version' command
        logging.warning("Error determining libvirt version")
        return None


def version_cmp(ver_x1, ver_y1, ver_z1, ver_x2, ver_y2, ver_z2):
    """Compare ver_?1 to ver_?2 using cmp() logic"""
    if int(ver_x1) > int(ver_x2):
        return 1
    elif int(ver_x1) < int(ver_x2):
        return -1
    else:  # ver_x1 == ver_x2
        if int(ver_y1) > int(ver_y2):
            return 1
        elif int(ver_y1) < int(ver_y2):
            return -1
        else:  # ver_y1 == ver_y2
            if int(ver_z1) > int(ver_z2):
                return 1
            elif int(ver_z1) == int(ver_z2):
                return 0
            else:  # ver_z1 < ver_z2
                return -1


def run(test, params, env):
    """
    Test command: virsh update-device.

    Update device from an XML <file>.
    1.Prepare test environment.Make sure a cdrom exists in VM.
      If not, please attach one cdrom manually.
    2.Perform virsh update-device operation.
    3.Recover test environment.
    4.Confirm the test result.
    """

    # Prepare initial vm state
    vm_name = params.get("main_vm")
    vmxml = VMXML.new_from_dumpxml(vm_name, options="--inactive")
    vm = env.get_vm(vm_name)
    start_vm = "yes" == params.get("start_vm", "no")
    if vm.is_alive() and not start_vm:
        vm.destroy()
        domid = "domid invalid; domain is shut-off"
    else:
        domid = vm.get_id()
    # Get all parameters for configuration.
    flag = params.get("updatedevice_flag", "")
    twice = "yes" == params.get("updatedevice_twice", "no")
    diff_iso = "yes" == params.get("updatedevice_diff_iso", "no")
    vm_ref = params.get("updatedevice_vm_ref", "")
    status_error = "yes" == params.get("status_error", "no")
    extra = params.get("updatedevice_extra", "")

    # Parse flag list, skip testing early if flag is not supported
    flag_list = flag.split("--")
    for item in flag_list:
        option = item.strip()
        if option == "":
            continue
        if not bool(virsh.has_command_help_match("update-device", option)):
            raise error.TestNAError("virsh update-device doesn't support --%s"
                                    % option)

    # As per RH BZ 961443 avoid testing before behavior changes
    current_version = libvirt_library_version()
    # SKIP tests using --config if libvirt is 0.9.10 or earlier
    skip_if_config = (0, 9, 19)
    # SKIP tests using --persistent if libvirt 1.0.5 or earlier
    skip_if_persistent = (1, 0, 5)
    if 'config' in flag_list:
        cmp_args = current_version + skip_if_config
        if version_cmp(*cmp_args) < 1:  # current <= skip_if_config
            raise error.TestNAError("BZ 961443: --config behavior change "
                                    "in version %s" % skip_if_config)
    if 'persistent' in flag_list:
        cmp_args = current_version + skip_if_persistent
        if version_cmp(*cmp_args) < 1:  # current <= skip_if_persistent
            raise error.TestNAError("BZ 961443: --persistent behavior change "
                                    "in version %s" % skip_if_persistent)

    # Prepare tmp directory and files.
    test_iso = os.path.join(test.virtdir, "test.iso")
    test_diff_iso = os.path.join(test.virtdir, "test_diff.iso")
    update_xmlfile = os.path.join(test.tmpdir, "update.xml")
    create_attach_xml(update_xmlfile, test_iso)

    try:
        if vm_ref == "id":
            vm_ref = domid
            if twice:
                # Don't pass in any flags
                virsh.update_device(domainarg=domid, filearg=update_xmlfile,
                                    ignore_status=True, debug=True)
            if diff_iso == "yes":
                # Swap filename of device backing file in update.xml
                os.remove(update_xmlfile)
                create_attach_xml(update_xmlfile, test_diff_iso)
        elif vm_ref == "uuid":
            vm_ref = vmxml.uuid
        elif vm_ref == "hex_id":
            vm_ref = hex(int(domid))
        elif vm_ref.find("updatedevice_invalid") != -1:
            vm_ref = params.get(vm_ref)
        elif vm_ref == "name":
            vm_ref = "%s %s" % (vm_name, extra)

        cmdresult = virsh.update_device(domainarg=vm_ref,
                                        filearg=update_xmlfile,
                                        flagstr=flag,
                                        ignore_status=True,
                                        debug=True)
        status = cmdresult.exit_status

        active_vmxml = VMXML.new_from_dumpxml(vm_name)
        inactive_vmxml = VMXML.new_from_dumpxml(vm_name,
                                                options="--inactive")
    finally:
        vm.destroy(gracefully=False, free_mac_addresses=False)
        vmxml.undefine()
        vmxml.restore()
        vmxml.define()
        if os.path.exists(test_iso):
            os.remove(test_iso)
        if os.path.exists(test_diff_iso):
            os.remove(test_diff_iso)

    # Result handling logic set errmsg only on error
    errmsg = None
    if status_error:
        if status == 0:
            errmsg = "Run successfully with wrong command!"
    else:  # Normal test
        if status != 0:
            errmsg = "Run failed with right command"
        if diff_iso:  # Expect the backing file to have updated
            active_attached = is_attached(active_vmxml.devices,
                                          test_diff_iso)
            inactive_attached = is_attached(active_vmxml.devices,
                                            test_diff_iso)
        else:  # Expect backing file to remain the same
            active_attached = is_attached(active_vmxml.devices, test_iso)
            inactive_attached = is_attached(active_vmxml.devices, test_iso)

        # Check behavior of combination before individual!
        if "config" in flag_list and "live" in flag_list:
            if not active_attached:
                errmsg = ("Active domain XML not updated when "
                          "--config --live options used")
            if not inactive_attached:
                errmsg = ("Inactive domain XML not updated when "
                          "--config --live options used")

        elif "live" in flag_list and inactive_attached:
            errmsg = ("Inactive domain XML updated when "
                      "--live option used")

        elif "config" in flag_list and active_attached:
            errmsg = ("Active domain XML updated when "
                      "--config option used")

        # persistent option behavior depends on start_vm
        if "persistent" in flag_list:
            if start_vm:
                if not active_attached or not inactive_attached:
                    errmsg = ("XML not updated when --persistent "
                              "option used on active domain")

            else:
                if not inactive_attached:
                    errmsg = ("XML not updated when --persistent "
                              "option used on inactive domain")
        if len(flag_list) == 0:
            # Not specifying any flag is the same as specifying --current
            if start_vm:
                if not active_attached:
                    errmsg = "Active domain XML not updated"
                elif inactive_attached:
                    errmsg = ("Inactive domain XML updated when active "
                              "requested")

    # Log some debugging info before destroying instances
    if errmsg is not None:
        logging.debug("Active XML:")
        logging.debug(str(active_vmxml))
        logging.debug("Inactive XML:")
        logging.debug(str(inactive_vmxml))
        logging.debug("active_attached: %s", str(active_attached))
        logging.debug("inctive_attached: %s", str(inactive_attached))
        logging.debug("Device XML:")
        logging.debug(open(update_xmlfile, "r").read())

    # clean up tmp files
    del vmxml
    del active_vmxml
    del inactive_vmxml
    os.unlink(update_xmlfile)

    if errmsg is not None:
        raise error.TestFail(errmsg)
