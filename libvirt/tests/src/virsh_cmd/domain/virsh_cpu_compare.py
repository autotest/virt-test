import os
from autotest.client.shared import error
from virttest import virsh
from virttest.libvirt_xml import vm_xml, capability_xml


def run(test, params, env):
    """
    Test command: virsh cpu-compare.

    Compare host CPU with a CPU described by an XML file.
    1.Get all parameters from configuration.
    2.Prepare temp file saves of CPU information.
    3.Perform virsh cpu-compare operation.
    4.Confirm the result.
    """

    def get_cpu_xml(target, mode, tmp_file, cpu_mode=""):
        """
        Get CPU information and put it into a file.

        :param target: Test target, host or guest's cpu description.
        :param mode: Test mode, decides file's detail.
        :param tmp_file: File saves CPU information.
        """
        try:
            cpu_xml_file = open(tmp_file, 'wb')
            if target == "host":
                libvirtxml = capability_xml.CapabilityXML()
            else:
                libvirtxml = vm_xml.VMCPUXML(vm_name=vm_name, mode=cpu_mode)
            if mode == "modify":
                if modify_target == "vendor":
                    libvirtxml['vendor'] = test_vendor
                else:
                    # Choose the last feature to test
                    if feature_action == "remove":
                        libvirtxml.remove_feature(feature_num)
                    elif feature_action == "repeat":
                        name = libvirtxml.get_feature_name(feature_num)
                        libvirtxml.add_feature(name)
                    else:
                        libvirtxml.set_feature(feature_num, feature_name)
                libvirtxml.xmltreefile.write(cpu_xml_file)
            elif mode == "clear":
                # Clear up file detail
                cpu_xml_file.truncate(0)
            else:
                libvirtxml.xmltreefile.write(cpu_xml_file)
            cpu_xml_file.close()
        except (IndexError, AttributeError):
            if target == "guest":
                vmxml.undefine()
                vmxml.define()
            raise error.TestError("Get CPU information failed!")

    # Get all parameters.
    ref = params.get("cpu_compare_ref")
    mode = params.get("cpu_compare_mode", "")
    modify_target = params.get("cpu_compare_modify_target", "vendor")
    feature_num = int(params.get("cpu_compare_feature_num", -1))
    feature_action = params.get("cpu_compare_feature_action", "modify")
    feature_name = params.get("cpu_compare_feature", "")
    test_vendor = params.get("cpu_compare_vendor", "")
    target = params.get("cpu_compare_target", "host")
    status_error = params.get("status_error", "no")
    extra = params.get("cpu_compare_extra", "")
    file_name = params.get("cpu_compare_file_name", "cpu.xml")
    cpu_mode = params.get("cpu_compare_cpu_mode", "")
    tmp_file = os.path.join(test.tmpdir, file_name)
    if target == "guest":
        vm_name = params.get("main_vm")
        vm = env.get_vm(vm_name)
        if vm.is_alive():
            vm.destroy()
        # Backup the VM's xml.
        vmxml = vm_xml.VMXML.new_from_dumpxml(vm_name)

    # Prepare temp file.
    get_cpu_xml(target, mode, tmp_file, cpu_mode)

    if ref == "file":
        ref = tmp_file
    ref = "%s %s" % (ref, extra)

    # Perform virsh cpu-compare operation.
    status = virsh.cpu_compare(ref, ignore_status=True, debug=True).exit_status

    # Recover VM.
    if target == "guest":
        vmxml.undefine()
        vmxml.define()

    # Check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
