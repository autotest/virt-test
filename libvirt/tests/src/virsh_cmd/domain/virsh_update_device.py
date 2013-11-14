import re
import os
import difflib
from autotest.client.shared import error
from virttest import virsh, libvirt_xml
from xml.dom.minidom import parseString


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
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    if vm.is_alive() and params.get("start_vm") == "no":
        vm.destroy()

    def create_attach_xml(update_xmlfile, source_iso):
        """
        Create a xml file to update a device.

        :param update_xmlfile : Temp xml saves device information.
        :param source_iso : disk's source file.
        """
        try:
            f = open(source_iso, 'wb')
            f.seek((1024 * 1024) - 1)
            f.write(str(0))
            f.close()
        except IOError:
            raise error.TestFail("Create source_iso failed!")

        content = """
<disk device='cdrom' type='file'>
<driver name='file'/>
<source file='%s'/>
<target bus='ide' dev='hdc'/>
<readonly/>
</disk>
""" % source_iso
        xmlfile = open(update_xmlfile, 'w')
        xmlfile.write(content)
        xmlfile.close()

    def check_attach(source_file, output):
        """
        Check attached device and disk exist or not.

        :param source_file : disk's source file.
        :param output :VM's xml information .
        """
        dom = parseString(output)
        source = dom.getElementsByTagName("source")
        output2 = ""
        for n in source:
            output2 += n.getAttribute("file")
        target = dom.getElementsByTagName("target")
        output3 = ""
        for n in target:
            output3 += n.getAttribute("dev")
        dom.unlink

        source_iso = "%s" % source_file
        if not re.search(source_iso, output2):
            raise error.TestFail("didn't see 'attached disk")
        if not re.search('hdc', output3):
            raise error.TestFail("didn't see 'attached device")

    domid = vm.get_id()
    domuuid = vm.get_uuid()

    # Prepare tmp directory and files.
    tmp_iso = os.path.join(test.virtdir, "tmp.iso")
    tmp2_iso = os.path.join(test.virtdir, "tmp2.iso")
    update_xmlfile = os.path.join(test.tmpdir, "xml_file")

    # Get all parameters for configuration.
    flag = params.get("updatedevice_flag", "")
    twice = "yes" == params.get("updatedevice_twice", "no")
    diff_iso = params.get("updatedevice_diff_iso", "no")
    vm_ref = params.get("updatedevice_vm_ref", "")
    status_error = params.get("status_error", "no")
    extra = params.get("updatedevice_extra", "")

    create_attach_xml(update_xmlfile, tmp_iso)
    vm_xml = os.path.join(test.tmpdir, "vm_xml")
    virsh.dumpxml(vm_name, extra="", to_file=vm_xml)
    vmxml_before = libvirt_xml.VMXML.new_from_inactive_dumpxml(vm_name)

    if vm_ref == "id":
        vm_ref = domid
        if twice:
            virsh.update_device(domainarg=domid, filearg=update_xmlfile,
                                ignore_status=True)
        if diff_iso == "yes":
            os.remove(update_xmlfile)
            create_attach_xml(update_xmlfile, tmp2_iso)
    elif vm_ref == "uuid":
        vm_ref = domuuid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref.find("updatedevice_invalid") != -1:
        vm_ref = params.get(vm_ref)
    elif vm_ref == "name":
        vm_ref = "%s %s" % (vm_name, extra)

    status = virsh.update_device(domainarg=vm_ref, filearg=update_xmlfile,
                                 flagstr=flag, ignore_status=True, debug=True).exit_status

    output = "%s" % libvirt_xml.VMXML.new_from_dumpxml(vm_name)
    if params.has_key("updatedevice_diff_file"):
        vm_xml_after = os.path.join(test.tmpdir, "vm_xml_after")
        virsh.dumpxml(vm_name, extra="", to_file=vm_xml_after)
    vm.destroy()
    output_shut = "%s" % libvirt_xml.VMXML.new_from_dumpxml(vm_name)

    # Recover environment
    vm.undefine()
    vmxml_before.define()
    if os.path.exists(tmp_iso):
        os.remove(tmp_iso)
    if os.path.exists(tmp2_iso):
        os.remove(tmp2_iso)

    # Check status_error
    flag_list = flag.split("--")
    for item in flag_list:
        option = item.strip()
        if option == "":
            continue
        if virsh.has_command_help_match("update-device", option) is None:
            status_error = "yes"
            break
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
        else:
            if flag == "--persistent" or flag == "--config":
                if not re.search(tmp_iso, output_shut):
                    raise error.TestFail("virsh update-device function invalid"
                                         "didn't see 'attached device' in XML")
            else:
                if params.has_key("updatedevice_diff_file"):
                    context_before = file(vm_xml, 'r').read().splitlines()
                    context_after = file(vm_xml_after, 'r').read().splitlines()
                    output_diff = difflib.Differ().compare(context_before,
                                                           context_after)
                    if not re.search(tmp_iso, "\n".join(list(output_diff))):
                        raise error.TestFail("virsh update-device function "
                                             "invalid; can't see 'attached device'in before/after")
                else:
                    if re.search(tmp_iso, output_shut):
                        raise error.TestFail("virsh attach-device without "
                                             "--persistent/--config function invalid;can see "
                                             "'attached device'in XML")
            if diff_iso == "yes":
                check_attach(tmp2_iso, output)
            if vm_ref == "name":
                check_attach(tmp_iso, output)
