import logging
import os
from autotest.client.shared import error
from virttest import libvirt_vm, virsh, remote, aexpect, virt_vm, utils_test
from virttest.libvirt_xml import vm_xml
import virttest.utils_libguestfs as lgf
from autotest.client import utils


def run(test, params, env):
    """
    Test the command virt-sysprep

    """

    def prepare_action(vm):
        """
        Do some actions before testing: Touch new file
        in "/var/log" and "/var/mail/" etc.
        """
        global o_ssh
        if vm.is_dead():
            vm.start()
        try:
            session = vm.wait_for_login()
            # Create tmp file and modify hostname
            session.cmd("touch /var/log/tmp.log")
            session.cmd("touch /var/mail/tmp")
            tmp_hostname = "%stmp" % sysprep_hostname
            session.cmd("hostname %s" % tmp_hostname)
            o_ssh = session.cmd_output("cd /etc/ssh && cat ssh_host_key.pub")

            # Confirm the file/hostname has been created/modified
            log_out = session.cmd_output("cd /var/log/ && ls | grep tmp.log")
            mail_out = session.cmd_output("cd /var/mail && ls | grep tmp")
            hname_out = session.cmd_output("hostname")
            if (not log_out.strip() or not mail_out.strip() or
                    hname_out.strip() != tmp_hostname):
                logging.debug("log:%s\nmail:%s\nhostname:%s"
                              % (log_out, mail_out, hname_out))
                raise error.TestFail("Prepare action failed!")
            session.close()
            vm.destroy()
        except (remote.LoginError, virt_vm.VMError,
                aexpect.ShellError), detail:
            if "session" in dir():
                session.close()
            raise error.TestFail("Prepare action failed: %s" % detail)

    def sysprep_action(vm_name, image_name, sysprep_target, hostname):
        """
        Execute "virt-sysprep" command
        """
        options = ""
        if hostname:
            options = "--hostname %s " % hostname
        if sysprep_target == "guest":
            disk_or_domain = vm_name
        else:
            disk_or_domain = image_name
        lgf.virt_sysprep_cmd(disk_or_domain, options, ignore_status=False)

    def modify_source(vm_name, target, dst_image):
        """
        Modify domain's configuration to change its disk source
        """
        try:
            virsh.detach_disk(vm_name, target, extra="--config",
                              ignore_status=False)
            dst_image_format = utils_test.get_image_info(dst_image)['format']
            options = "--config --subdriver %s" % dst_image_format
            virsh.attach_disk(vm_name, dst_image, target, extra=options,
                              ignore_status=False)
        except (remote.LoginError, virt_vm.VMError,
                aexpect.ShellError), detail:
            raise error.TestFail("Modify guest source failed: %s" % detail)

    def modify_network(vm_name, first_nic):
        """
        Modify domain's interface to make sure domain can be login.
        """
        iface_type = first_nic.type
        iface_source = first_nic.source.get('bridge')
        mac_address = first_nic.mac_address
        try:
            virsh.detach_interface(vm_name, "--type=%s --config" % iface_type,
                                   ignore_status=False)
            virsh.attach_interface(vm_name,
                                   "--type=%s --source %s --mac %s --config"
                                   % (iface_type, iface_source, mac_address),
                                   ignore_status=False)
        except (remote.LoginError, virt_vm.VMError,
                aexpect.ShellError), detail:
            raise error.TestFail("Modify network failed:%s" % detail)

    def result_confirm(vm):
        """
        Confirm tmp file has been cleaned up, hostname has been changed, etc.
        """
        global o_ssh
        try:
            if vm.is_dead():
                vm.start()
            session = vm.wait_for_login(nic_index=0)
            log_out = session.cmd_output("cd /var/log/ && ls | grep tmp.log")
            mail_out = session.cmd_output("cd /var/mail && ls | grep tmp")
            hname_out = session.cmd_output("hostname")
            ssh_out = session.cmd_output("cd /etc/ssh && cat ssh_host_key.pub")
            session.close()
            vm.destroy()
            if (log_out.strip() or mail_out.strip() or
                hname_out.strip() != sysprep_hostname or
                    ssh_out.strip() == o_ssh.strip()):
                logging.debug("log: %s\nmail:%s\nhostname:%s\nsshkey:%s" %
                              (log_out, mail_out, hname_out, ssh_out))
                return False
            return True
        except (remote.LoginError, virt_vm.VMError,
                aexpect.ShellError), detail:
            logging.error(str(detail))
            if "session" in dir():
                session.close()
            return False

    def clean_clone_vm():
        """
        Clean up cloned domain.
        """
        try:
            if virsh.domain_exists(vm_clone_name):
                if virsh.is_alive(vm_clone_name):
                    virsh.destroy(vm_clone_name, ignore_status=False)
                virsh.undefine(vm_clone_name, ignore_status=False)
            if os.path.exists(clone_image):
                os.remove(clone_image)
        except error.CmdError, detail:
            raise error.TestFail("Clean clone guest failed!:%s" % detail)

    sysprep_type = params.get("sysprep_type", 'clone')
    sysprep_target = params.get("sysprep_target", 'guest')
    sysprep_hostname = params.get("sysprep_hostname", 'sysprep_test')
    vm_name = params.get("main_vm", "virt-tests-vm1")
    file_system = params.get("sysprep_file_system", "ext3")
    vm = env.get_vm(vm_name)
    disks = vm.get_disk_devices()
    if len(disks):
        disk = disks.values()[0]
        image = disk['source']
        target = disks.keys()[0]
        image_info_dict = utils_test.get_image_info(image)
        if sysprep_type == "sparsify" and image_info_dict['format'] != 'qcow2':
            raise error.TestNAError("This test case needs qcow2 format image.")
    else:
        raise error.TestError("Can not get disk of %s" % vm_name)
    vt = utils_test.libguestfs.VirtTools(vm, params)
    fs_type = vt.get_primary_disk_fs_type()
    if fs_type != file_system:
        raise error.TestNAError("This test case gets wrong disk file system."
                                "get: %s, expected: %s" % (fs_type,
                                                           file_system))

    # Do some prepare action
    vm_clone_name = "%s_clone" % vm_name
    clone_image = "%s_clone.img" % image
    vmxml = vm_xml.VMXML.new_from_dumpxml(vm_name)
    first_nic = vmxml.get_devices(device_type="interface")[0]
    clean_clone_vm()

    # Clone guest to guest_clone
    dargs = {}
    dargs['files'] = [clone_image]
    dargs['ignore_status'] = True
    clone_result = lgf.virt_clone_cmd(vm_name, newname=vm_clone_name, **dargs)
    if clone_result.exit_status:
        raise error.TestFail("virt-clone failed:%s"
                             % clone_result.stderr.strip())
    try:
        # Modify network to make sure the clone guest can be logging.
        modify_network(vm_clone_name, first_nic)
        new_vm = libvirt_vm.VM(vm_clone_name, params, vm.root_dir,
                               vm.address_cache)
        prepare_action(new_vm)
        test_image = clone_image

        if sysprep_type == "resize":
            img_size = image_info_dict['vsize'] / 1024 / 1024 / 1024
            resize_image = "%s_resize.img" % clone_image
            utils.run("qemu-img create -f raw %s %dG" % (resize_image,
                                                         (img_size + 1)))
            lgf.virt_resize_cmd(clone_image, resize_image, timeout=600,
                                debug=True)
            modify_source(vm_clone_name, target, resize_image)
            test_image = resize_image
        elif sysprep_type == "sparsify":
            sparsify_image = "%s_sparsify.img" % clone_image
            lgf.virt_sparsify_cmd(clone_image, sparsify_image, compress=True,
                                  format=image_info_dict['format'],
                                  timeout=600)
            modify_source(vm_clone_name, target, sparsify_image)
            test_image = sparsify_image
        sysprep_action(vm_clone_name, test_image, sysprep_target,
                       sysprep_hostname)
        if not result_confirm(new_vm):
            raise error.TestFail("Test Falied!")
    finally:
        clean_clone_vm()
        if "resize_image" in dir():
            if os.path.exists(resize_image):
                os.remove(resize_image)
        if "sparsify_image" in dir():
            if os.path.exists(sparsify_image):
                os.remove(sparsify_image)
