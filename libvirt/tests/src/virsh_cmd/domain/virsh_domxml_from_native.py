import re
import os
from autotest.client.shared import error
from autotest.client import utils
from virttest import virsh, utils_libvirtd


def run(test, params, env):
    """
    Test command: virsh domxml-from-native.

    Convert native guest configuration format to domain XML format.
    1.Prepare test environment.
    2.When the libvirtd == "off", stop the libvirtd service.
    3.Perform virsh domxml-from-native operation.
    4.Recover test environment.(If the libvirtd service is stopped ,start
      the libvirtd service.)
    5.Confirm the test result.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vm.verify_alive()

    def virsh_convxml(guest_args):
        """
        Put dumpxml vm'infomation to a file

        :param guest_args : File which will save config information.
        """
        pid = vm.get_pid()
        cmdline = utils.system_output("cat -v /proc/%d/cmdline" % pid)
        cmdline = re.sub(r'\^@', ' ', cmdline)
        cmdline_tmp = re.sub(r'\s-drive\s[^\s]+', '\s', cmdline)
        guest_file = file(guest_args, 'w')
        guest_file.write(cmdline_tmp)
        guest_file.close()

    libvirtd = params.get("libvirtd")
    dfn_format = params.get("dfn_format")
    guest_args = params.get("dfn_guest_args", "")
    invalid_guest_args = params.get("dfn_invalid_guest_args")
    status_error = params.get("status_error")

    # put vm's information to a file
    if guest_args != "":
        if os.path.dirname(guest_args) is "":
            guest_args = os.path.join(test.tmpdir, guest_args)
        virsh_convxml(guest_args)

    # libvirtd off
    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    # Ignore exception with ignore_status=True.
    ret = virsh.domxml_from_native(dfn_format, guest_args, invalid_guest_args,
                                   ignore_status=True)
    status = ret.exit_status

    # recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # clean up
    if os.path.exists(guest_args):
        os.remove(guest_args)

    # check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
