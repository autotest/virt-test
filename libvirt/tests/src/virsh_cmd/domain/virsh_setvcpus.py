import re
import os
import logging
import commands
from autotest.client.shared import error
from virttest import remote, virsh, libvirt_xml
from xml.dom.minidom import parse


def run(test, params, env):
    """
    Test command: virsh setvcpus.

    The conmand can change the number of virtual CPUs in the guest domain.
    1.Prepare test environment,destroy or suspend a VM.
    2.Perform virsh setvcpus operation.
    3.Recover test environment.
    4.Confirm the test result.
    """

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    xml_file = params.get("setvcpus_xml_file", "vm.xml")
    virsh.dumpxml(vm_name, extra="--inactive", to_file=xml_file)
    tmp_file = params.get("setvcpus_tmp_file", "tmp.xml")
    pre_vm_state = params.get("setvcpus_pre_vm_state")
    command = params.get("setvcpus_command", "setvcpus")
    options = params.get("setvcpus_options")
    domain = params.get("setvcpus_domain")
    count = params.get("setvcpus_count")
    extra_param = params.get("setvcpus_extra_param")
    count_option = "%s %s" % (count, extra_param)
    status_error = params.get("status_error")

    def get_current_vcpus():
        """
        Get current vcpu number.
        """
        vcpus_set = ""
        virsh.dumpxml(vm_name, extra="", to_file=tmp_file)
        dom = parse(tmp_file)
        root = dom.documentElement
        vcpus_2 = root.getElementsByTagName("vcpu")
        for n in vcpus_2:
            vcpus_set += n.getAttribute("current")
            vcpus_set = int(vcpus_set)
        dom.unlink()
        return vcpus_set

    if vm.is_alive():
        vm.destroy()
    vm_xml = libvirt_xml.VMXML()
    vm_xml.set_vm_vcpus(vm_name, 2)
    vm.start()
    vm.wait_for_login()

    if status_error == "no":
        vcpus_new = len(vm.vcpuinfo())
    domid = vm.get_id()
    domuuid = vm.get_uuid()
    if pre_vm_state == "paused":
        vm.pause()
    elif pre_vm_state == "shut off":
        vm.destroy()

    if domain == "remote_name":
        remote_ssh_addr = params.get("remote_ip", None)
        remote_addr = params.get("local_ip", None)
        remote_password = params.get("remote_password", None)
        host_type = virsh.driver()
        if host_type == "qemu":
            remote_string = "qemu+ssh://%s/system" % remote_addr
        elif host_type == "xen":
            remote_string = "xen+ssh://%s" % remote_addr
        command = "virsh -c %s setvcpus %s 1 --live" % (remote_string, vm_name)
        if virsh.has_command_help_match(command, "--live") is None:
            status_error = "yes"
        session = remote.remote_login(
            "ssh", remote_ssh_addr, "22", "root", remote_password, "#")
        session.cmd_output('LANG=C')
        status, output = session.cmd_status_output(command, internal_timeout=5)
        session.close()
        vcpus_current = len(vm.vcpuinfo())
    else:
        if domain == "name":
            dom_option = vm_name
        elif domain == "id":
            dom_option = domid
            if params.get("setvcpus_hex_id") is not None:
                dom_option = hex(int(domid))
            elif params.get("setvcpus_invalid_id") is not None:
                dom_option = params.get("setvcpus_invalid_id")
        elif domain == "uuid":
            dom_option = domuuid
            if params.get("setvcpus_invalid_uuid") is not None:
                dom_option = params.get("setvcpus_invalid_uuid")
        else:
            dom_option = domain
        option_list = options.split(" ")
        for item in option_list:
            if virsh.has_command_help_match(command, item) is None:
                status_error = "yes"
                break
        status = virsh.setvcpus(
            dom_option, count_option, options, ignore_status=True).exit_status
        if pre_vm_state == "paused":
            virsh.resume(vm_name, ignore_status=True)
        if status_error == "no":
            if status == 0:
                if pre_vm_state == "shut off":
                    if options == "--config":
                        vcpus_set = len(vm.vcpuinfo())
                    elif options == "--current":
                        vcpus_set = get_current_vcpus()
                    elif options == "--maximum --config":
                        vcpus_set = ""
                        dom = parse("/etc/libvirt/qemu/%s.xml" % vm_name)
                        vcpus_set = dom.getElementsByTagName(
                            "vcpu")[0].firstChild.data
                        vcpus_set = int(vcpus_set)
                        dom.unlink()
                else:
                    vcpus_set = len(vm.vcpuinfo())
                if domain == "id":
                    cmd_chk = "cat /etc/libvirt/qemu/%s.xml" % vm_name
                    output1 = commands.getoutput(cmd_chk)
                    logging.info("guest-info:\n%s" % output1)

    virsh.destroy(vm_name)
    virsh.undefine(vm_name)
    virsh.define(xml_file)
    if os.path.exists(xml_file):
        os.remove(xml_file)
    if os.path.exists(tmp_file):
        os.remove(tmp_file)

    # check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    else:
        if status != 0:
            raise error.TestFail("Run failed with right command")
        else:
            if options == "--maximum --config":
                if vcpus_set != 4:
                    raise error.TestFail("Run failed with right command1")
            elif domain == "id":
                if options == "--config":
                    if vcpus_set != vcpus_new or not re.search('<vcpu current=\'1\'>%s</vcpu>' % vcpus_new, output1):
                        raise error.TestFail("Run failed with right command2")
                elif options == "--config --live":
                    if vcpus_set != 1 or not re.search('<vcpu current=\'1\'>%s</vcpu>' % vcpus_new, output1):
                        raise error.TestFail("Run failed with right command3")
                else:
                    if vcpus_set != 1 or re.search('<vcpu current=\'1\'>%s</vcpu>' % vcpus_new, output1):
                        raise error.TestFail("Run failed with right command4")
            else:
                if vcpus_set != 1:
                    raise error.TestFail("Run failed with right command5")
