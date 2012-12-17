import re, os
from autotest.client.shared import error
from autotest.client import utils
from virttest import libvirt_vm, virsh


def run_virsh_domxml_to_native(test, params, env):
    """
    Test command: virsh domxml-to-native.

    Convert domain XML config to a native guest configuration format.
    1.Prepare test environment.
    2.When the libvirtd == "off", stop the libvirtd service.
    3.Perform virsh domxml-from-native operation.
    4.Recover test environment.
    5.Confirm the test result.
    """
    vm_name = params.get("main_vm", "vm1")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    def compare(conv_arg):
        """
        Compare converted infomation with vm's infomation.

        @param: conv_arg : Converted infomation.
        @return: True if converted infomation has no diffrent from
                 vm's infomation.
        """
        pid = vm.get_pid()
        cmdline_tmp = utils.system_output("cat -v /proc/%d/cmdline" % pid)
        cmdline = re.sub(r'\^@', ' ', cmdline_tmp)
        tmp = re.search('LC_ALL.[^\s]\s', conv_arg).group(0) +\
              re.search('PATH.[^\s]+\s', conv_arg).group(0) +\
              re.search('QEMU_AUDIO_DRV.[^\s]+\s', conv_arg).group(0)
        qemu_arg = tmp + cmdline
        conv_arg_lines = conv_arg.split('\x20')
        qemu_arg_lines = qemu_arg.split('\x20')

        i = 0
        result = True
        for arg in conv_arg_lines:
            print arg
            print qemu_arg_lines[i]
            if re.search("mode=readline", arg):
                i += 1
                continue
            elif re.search("mac=00:00:00:00:00:00", arg):
                i += 1
                continue
            elif re.search("127.0.0.1:0", arg):
                i += 1
                continue
            elif re.search("tap", arg):
                i += 1
                continue

            if arg != qemu_arg_lines[i]:
                result = False
            i += 1
        return result

    #run test case
    dtn_format = params.get("dtn_format")
    file_xml = params.get("dtn_file_xml")
    extra_param = params.get("dtn_extra_param")
    libvirtd = params.get("libvirtd")
    status_error = params.get("status_error")
    virsh.dumpxml(vm_name, file_xml)
    if libvirtd == "off":
        libvirt_vm.libvirtd_stop()
    ret = virsh.domxml_to_native(dtn_format, file_xml, extra_param,
                                 ignore_status = True)
    status = ret.exit_status
    conv_arg = ret.stdout.strip()

    #recover libvirtd service start
    if libvirtd == "off":
        libvirt_vm.libvirtd_start()

    #clean up
    if os.path.exists(file_xml):
        os.remove(file_xml)

    #check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
        if compare(conv_arg) != True:
            raise error.TestFail("Test failed!")
