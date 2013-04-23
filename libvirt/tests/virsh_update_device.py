import re, os, commands, shutil
from autotest.client.shared import error
from virttest import remote, virsh, libvirt_xml
from xml.dom.minidom import parseString


def run_virsh_update_device(test, params, env):
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

        @param: update_xmlfile : Temp xml saves device infomation.
        @param: source_iso : disk's source file.
        """
        if os.system("touch %s" % source_iso):
            raise  error.TestFail("Create source_iso failed!")

        cmd = """cat << EOF > %s
<disk device='cdrom' type='file'>
<driver name='file'/>
<source file='%s'/>
<target bus='ide' dev='hdc'/>
<readonly/>
</disk>
EOF""" % (update_xmlfile, source_iso)
        if os.system(cmd):
            raise  error.TestFail("Create update_iso_xml failed!")


    def clean_up(tmp_dir):
        """
        Clean up tmp directory and files in the test.

        @param: tmp_dir: Tmp directory created in the test.
        """
        if os.path.exists(tmp_dir):
            if shutil.rmtree(tmp_dir):
                raise  error.TestFail("Clean up failed!")


    def check_attach(source_file, output):
        """
        Check attached device and disk exist or not.

        @param: source_file : disk's source file.
        @param: output :VM's xml infomation .
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

        source_iso = "%s"  % source_file
        if not re.search(source_iso, output2):
            clean_up(tmp_dir)
            raise  error.TestFail("didn't see 'attached disk")
        if not re.search('hdc', output3):
            clean_up(tmp_dir)
            raise  error.TestFail("didn't see 'attached device")


    domid = vm.get_id()
    domuuid = vm.get_uuid()

    # Prepare tmp directory and files.
    tmp_dir = os.path.join(test.virtdir, "tmp/")
    if not os.path.exists(tmp_dir):
        commands.getoutput("mkdir -p %s" % tmp_dir)
    tmp_iso = os.path.join(tmp_dir, "tmp.iso")
    tmp2_iso = os.path.join(tmp_dir, "tmp2.iso")
    update_xmlfile = os.path.join(tmp_dir, "xml_file")

    # Get all parameters for configuration.
    flag = params.get("updatedevice_flag", "")
    twice = params.get("updatedevice_twice", "no")
    diff_iso = params.get("updatedevice_diff_iso", "no")
    vm_ref = params.get("updatedevice_vm_ref", "")
    status_error = params.get("status_error", "no")
    extra = params.get("updatedevice_extra", "")

    create_attach_xml(update_xmlfile, tmp_iso)
    vm_xml = os.path.join(tmp_dir, "vm_xml")
    virsh.dumpxml(vm_name, vm_xml)

    if vm_ref == "id":
        vm_ref = domid
        if twice == "yes":
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

    output_shut = "%s" % libvirt_xml.VMXML.new_from_dumpxml(vm_name)
    if params.has_key("updatedevice_diff_file"):
        vm_xml_after = os.path.join(tmp_dir, "vm_xml_after")
        virsh.dumpxml(vm_name, vm_xml_after)
    vm.destroy()
    output = "%s" % libvirt_xml.VMXML.new_from_dumpxml(vm_name)
    virsh.undefine(vm_name)
    virsh.define(vm_xml)

    # Check status_error
    flag_list = flag.split("--")
    for item in flag_list:
        option = item.strip()
        if option == "":
            continue
        if virsh.has_command_help_match("update-device", option) == None:
            status_error = "yes"
            break
    if status_error == "yes":
        clean_up(tmp_dir)
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            clean_up(tmp_dir)
            raise error.TestFail("Run failed with right command")
        else:
            if flag == "--persistent" or flag == "--config":
                if not re.search(tmp_iso, output):
                    clean_up(tmp_dir)
                    raise error.TestFail("virsh update-device function invalid"
                                         "didn't see 'attached device' in XML")
            else:
                if params.has_key("updatedevice_diff_file"):
                    file_diff = "update-device_test.%s_diff" % vm_name
                    command = "diff %s %s >> %s" %\
                              (vm_xml, vm_xml_after, file_diff)
                    commands.getstatusoutput(command)
                    command = "cat %s" % file_diff
                    output_diff = commands.getoutput(command)
                    os.remove(file_diff)
                    if not re.search(tmp_iso, output_diff):
                        clean_up(tmp_dir)
                        raise  error.TestFail("virsh update-device function "
                        "invalid; can't see 'attached device'in before/after")
                else:
                    if re.search(tmp_iso, output):
                        clean_up(tmp_dir)
                        raise  error.TestFail("virsh attach-device without "
                        "--persistent/--config function invalid;can see "
                        "'attached device'in XML")
            if diff_iso == "yes":
                check_attach(tmp2_iso, output_shut)
            if  vm_ref == "name":
                check_attach(tmp_iso, output_shut)
            clean_up(tmp_dir)
