import re
import os
from autotest.client.shared import error
from autotest.client import utils
from virttest import virsh, utils_libvirtd


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
    vm_name = params.get("main_vm")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    def compare(conv_arg):
        """
        Compare converted information with vm's information.

        @param: conv_arg : Converted information.
        @return: True if converted information has no different from
                 vm's information.
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

    # run test case
    dtn_format = params.get("dtn_format")
    file_xml = params.get("dtn_file_xml")
    extra_param = params.get("dtn_extra_param")
    libvirtd = params.get("libvirtd")
    status_error = params.get("status_error")
    virsh.dumpxml(vm_name, extra="", to_file=file_xml)
    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()
    ret = virsh.domxml_to_native(dtn_format, file_xml, extra_param,
                                 ignore_status=True)
    status = ret.exit_status
    conv_arg = ret.stdout.strip()

    # recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # clean up
    if os.path.exists(file_xml):
        os.remove(file_xml)

    # check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
        if compare(conv_arg) is not True:
            raise error.TestFail("Test failed!")
