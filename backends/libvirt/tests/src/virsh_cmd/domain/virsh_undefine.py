import os
import logging
from autotest.client.shared import error
from virttest import libvirt_vm, virsh, remote, utils_libvirtd, aexpect


def run(test, params, env):
    """
    Test virsh undefine command.

    Undefine an inactive domain, or convert persistent to transient.
    1.Prepare test environment.
    2.Backup the VM's information to a xml file.
    3.When the libvirtd == "off", stop the libvirtd service.
    4.Perform virsh undefine operation.
    5.Recover test environment.(libvirts service,VM)
    6.Confirm the test result.
    """

    vm_ref = params.get("undefine_vm_ref", "vm_name")
    extra = params.get("undefine_extra", "")
    libvirtd_state = params.get("libvirtd", "on")
    status_error = params.get("status_error")
    undefine_twice = params.get("undefine_twice", 'no')
    local_ip = params.get("local_ip", "LOCAL.EXAMPLE.COM")
    remote_ip = params.get("remote_ip", "REMOTE.EXAMPLE.COM")
    xml_file = os.path.join(test.tmpdir, 'tmp.xml')
    remote_user = params.get("remote_user", "user")
    remote_pwd = params.get("remote_pwd", "password")
    remote_prompt = params.get("remote_prompt", "#")

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vm_id = vm.get_id()
    vm_uuid = vm.get_uuid()

    # Back up xml file.Xen host has no guest xml file to define a guset.
    virsh.dumpxml(vm_name, extra="--inactive", to_file=xml_file)

    # Confirm how to reference a VM.
    if vm_ref == "vm_name":
        vm_ref = vm_name
    elif vm_ref == "id":
        vm_ref = vm_id
    elif vm_ref == "hex_vm_id":
        vm_ref = hex(int(vm_id))
    elif vm_ref == "uuid":
        vm_ref = vm_uuid
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)

    # Turn libvirtd into certain state.
    if libvirtd_state == "off":
        utils_libvirtd.libvirtd_stop()

    # Test virsh undefine command.
    if vm_ref != "remote":
        vm_ref = "%s %s" % (vm_ref, extra)
        cmdresult = virsh.undefine(vm_ref,
                                   ignore_status=True, debug=True)
        status = cmdresult.exit_status
        if status:
            logging.debug("Error status, command output: %s", cmdresult.stdout)
        if undefine_twice == "yes":
            status2 = virsh.undefine(vm_ref,
                                     ignore_status=True).exit_status
    else:
        if remote_ip.count("EXAMPLE.COM") or local_ip.count("EXAMPLE.COM"):
            raise error.TestNAError("remote_ip and/or local_ip parameters not"
                                    " changed from default values")
        try:
            uri = libvirt_vm.complete_uri(local_ip)
            session = remote.remote_login("ssh", remote_ip, "22", remote_user,
                                          remote_pwd, remote_prompt)
            cmd_undefine = "virsh -c %s undefine %s" % (uri, vm_name)
            status, output = session.cmd_status_output(cmd_undefine)
            logging.info("Undefine output: %s", output)
        except (error.CmdError, remote.LoginError, aexpect.ShellError), detail:
            logging.error("Detail: %s", detail)
            status = 1

    # Recover libvirtd state.
    if libvirtd_state == "off":
        utils_libvirtd.libvirtd_start()

    # Shutdown VM.
    if virsh.domain_exists(vm.name):
        try:
            if vm.is_alive():
                vm.destroy()
        except error.CmdError, detail:
            logging.error("Detail: %s", detail)

    # Check if VM exists.
    vm_exist = virsh.domain_exists(vm.name)

    # Check if xml file exists.
    xml_exist = False
    if (os.path.exists("/etc/libvirt/qemu/%s.xml" % vm_name) or
            os.path.exists("/etc/xen/%s" % vm_name)):
        xml_exist = True

    # Recover main VM.
    if not virsh.domain_exists(vm.name):
        s_define = virsh.define(xml_file)
        if s_define is not True or not virsh.domain_exists(vm.name):
            logging.error("Failed to define %s.", vm.name)

    # Check results.
    if status_error == 'yes':
        if status == 0:
            raise error.TestFail("virsh undefine return unexpected result.")
    else:
        if status != 0:
            raise error.TestFail("virsh undefine failed.")
        if undefine_twice == "yes":
            if status2 == 0:
                raise error.TestFail("Undefine the same VM twice succeeded.")
        if vm_exist:
            raise error.TestFail("VM still exists after undefine.")
        if xml_exist:
            raise error.TestFail("Xml file still exists after undefine.")
