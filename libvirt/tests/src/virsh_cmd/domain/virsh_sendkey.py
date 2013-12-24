import logging
import time
from autotest.client.shared import error
from virttest import virsh


def run(test, params, env):
    """
    Test send-key command, include all types of codeset and sysrq

    For normal sendkey test, we create a file to check the command
    execute by send-key. For sysrq test, check the /var/log/messages
    and guest status
    """

    if not virsh.has_help_command('send-key'):
        raise error.TestNAError("This version of libvirt does not support "
                                "the send-key test")

    vm_name = params.get("main_vm", "virt-tests-vm1")
    status_error = ("yes" == params.get("status_error", "no"))
    options = params.get("sendkey_options", "")
    params_test = ("yes" == params.get("sendkey_params", "no"))
    sysrq_test = ("yes" == params.get("sendkey_sysrq", "no"))
    readonly = params.get("readonly", False)
    username = params.get("username")
    password = params.get("password")
    create_file = params.get("create_file_name")

    def send_line(send_str):
        """
        send string to guest with send-key and end with Enter
        """
        for send_ch in list(send_str):
            virsh.sendkey(vm_name, "KEY_%s" % send_ch.upper(),
                          ignore_status=False)

        virsh.sendkey(vm_name, "KEY_ENTER", ignore_status=False)

    vm = env.get_vm(vm_name)
    session = vm.wait_for_login()

    if sysrq_test:
        # clear messages before test
        session.cmd("echo '' > /var/log/message")
        # enable sysrq
        session.cmd("echo 1 > /proc/sys/kernel/sysrq")

    # make sure the environment is clear
    session.cmd("rm -rf %s" % create_file)

    try:
        # wait for tty1 started
        tty1_stat = "ps aux|grep [/]sbin/.*tty.*tty1"
        timeout = 60
        while timeout >= 0 and \
                session.get_command_status(tty1_stat) != 0:
            time.sleep(1)
            timeout = timeout - 1
        if timeout < 0:
            raise error.TestFail("Can not wait for tty1 started in 60s")

        # send user and passwd to guest to login
        send_line(username)
        time.sleep(2)
        send_line(password)
        time.sleep(2)

        output = virsh.sendkey(vm_name, options, readonly=readonly)
        time.sleep(2)
        if output.exit_status != 0:
            if status_error:
                logging.info("Failed to sendkey to guest as expected, Error:"
                             "%s.", output.stderr)
                return
            else:
                raise error.TestFail("Failed to send key to guest, Error:%s." %
                                     output.stderr)
        elif status_error:
            raise error.TestFail("Expect fail, but succeed indeed.")

        if params_test:
            # check if created file exist
            cmd_ls = "ls %s" % create_file
            sec_status, sec_output = session.get_command_status_output(cmd_ls)
            if sec_status == 0:
                logging.info("Succeed to create file with send key")
            else:
                raise error.TestFail("Fail to create file with send key, "
                                     "Error:%s" % sec_output)
        elif sysrq_test:
            # check /var/log/message info according to different key
            if "KEY_H" in options:
                get_status = session.cmd_status("cat /var/log/messages|"
                                                "grep SysRq.*HELP")
            elif "KEY_M" in options:
                get_status = session.cmd_status("cat /var/log/messages|"
                                                "grep 'SysRq.*Show Memory'")
            elif "KEY_T" in options:
                get_status = session.cmd_status("cat /var/log/messages|"
                                                "grep 'SysRq.*Show State'")
            if get_status != 0:
                raise error.TestFail("SysRq does not take effect in guest, "
                                     "options is %s" % options)
            else:
                logging.info("Succeed to send SysRq command")

    finally:
        session.cmd("rm -rf %s" % create_file)
        session.close()
