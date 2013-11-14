import os
import time
from virttest import remote

from autotest.client.shared import error
from virttest import virsh, aexpect, utils_libvirtd


def run(test, params, env):
    """
    Test command: virsh edit.

    The command can edit XML configuration for a domain
    1.Prepare test environment,destroy or suspend a VM.
    2.When the libvirtd == "off", stop the libvirtd service.
    3.Perform virsh edit operation.
    4.Recover test environment.
    5.Confirm the test result.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    domid = vm.get_id()
    domuuid = vm.get_uuid()
    vcpucount_result = virsh.vcpucount(vm_name, options="--config --maximum")
    if vcpucount_result.exit_status:
        raise error.TestError("Failed to get vcpucount. Detail:\n%s"
                              % vcpucount_result)
    original_vcpu = vcpucount_result.stdout.strip()
    expected_vcpu = str(int(original_vcpu) + 1)

    libvirtd = params.get("libvirtd", "on")
    vm_ref = params.get("edit_vm_ref")
    status_error = params.get("status_error")

    def modify_vcpu(source, edit_cmd):
        """
        Modify vm's cpu information.

        :param source : virsh edit's option.
        :param dic_mode : a edit commad line .
        :return: True if edit successed,False if edit failed.
        """
        session = aexpect.ShellSession("sudo -s")
        try:
            session.sendline("virsh edit %s" % source)
            session.sendline(edit_cmd)
            session.send('\x1b')
            session.send('ZZ')
            remote.handle_prompts(session, None, None, r"[\#\$]\s*$")
            session.close()
            return True
        except:
            return False

    def edit_vcpu(source, guest_name):
        """
        Modify vm's cpu information by virsh edit command.

        :param source : virsh edit's option.
        :param guest_name : vm's name.
        :return: True if edit successed,False if edit failed.
        """
        dic_mode = {
            "edit": r":%s /[0-9]*<\/vcpu>/" + expected_vcpu + r"<\/vcpu>",
            "recover": r":%s /[0-9]*<\/vcpu>/" + original_vcpu + r"<\/vcpu>"}
        status = modify_vcpu(source, dic_mode["edit"])
        if not status:
            return status
        if params.get("paused_after_start_vm") == "yes":
            virsh.resume(guest_name, ignore_status=True)
            virsh.destroy(guest_name)
        elif params.get("start_vm") == "yes":
            virsh.destroy(guest_name)
        vcpus = vm.dominfo()["CPU(s)"]
        # Recover cpuinfo
        # Use name rather than source, since source could be domid
        status = modify_vcpu(guest_name, dic_mode["recover"])
        if status and vcpus != expected_vcpu:
            return False
        return status

    # run test case
    xml_file = os.path.join(test.tmpdir, 'tmp.xml')
    virsh.dumpxml(vm_name, extra="--inactive", to_file=xml_file)

    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    try:
        if vm_ref == "id":
            status = edit_vcpu(domid, vm_name)
        elif vm_ref == "uuid":
            status = edit_vcpu(domuuid, vm_name)
        elif vm_ref == "name" and status_error == "no":
            status = edit_vcpu(vm_name, vm_name)
        else:
            status = False
            if vm_ref.find("invalid") != -1:
                vm_ref = params.get(vm_ref)
            elif vm_ref == "name":
                vm_ref = "%s %s" % (vm_name, params.get("edit_extra_param"))
            edit_status = virsh.edit(vm_ref).exit_status
            if edit_status == 0:
                status = True
    except:
        status = False

    # recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # Recover VM
    if vm.is_alive():
        vm.destroy()
    virsh.undefine(vm_name)
    virsh.define(xml_file)

    # check status_error
    if status_error == "yes":
        if status:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if not status:
            raise error.TestFail("Run failed with right command")
