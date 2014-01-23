import time
import logging
from autotest.client.shared import error


@error.context_aware
def run(test, params, env):
    """
    Generate a dump on NMI, then analyse the dump file:
    1) Boot a windows guest.
    2) Edit the guest's system registry if need.
    3) Reboot the guest.
    4) Send inject-nmi or nmi from host to guest.
    5) Send a reboot command or a system_reset monitor command (optional)
    6) Verify whether the dump files are generated.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error.context("Boot a windows guest", logging.info)
    timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    manual_reboot_cmd = params.get("manual_reboot_cmd")
    check_dump_cmd = params.get("check_dump_cmd")
    nmi_cmd = params.get("nmi_cmd")
    del_dump_cmd = params.get("del_dump_cmd")
    analyze_cmd = params.get("analyze_cmd")

    if del_dump_cmd:
        session.sendline(del_dump_cmd)

    if params.get("config_cmds"):
        error.context("Configure guest for dump", logging.info)
        # Wait guest fully boot up, or configure command may fail in windows
        time.sleep(30)
        reg_cmds = params.get("config_cmds").split(",")
        msg = "Configure the guest"
        for reg_cmd in reg_cmds:
            cmd = params.get(reg_cmd.strip())
            msg += " The command is %s " % cmd
            error.context(msg)
            s, o = session.cmd_status_output(cmd, 360)
            if s:
                raise error.TestFail("Fail command: %s. Output: %s" % (cmd, o))

    if params.get("reboot_after_config") == "yes":
        error.context("Reboot guest", logging.info)
        session = vm.reboot(timeout=timeout * 2)

    try:
        if nmi_cmd:
            error.context("Send inject-nmi or nmi from host to guest",
                          logging.info)
            vm.monitor.send_args_cmd(nmi_cmd)
        # Wait guest create dump file.
        if manual_reboot_cmd:
            bsod_time = params.get("bsod_time", 160)
            logging.info("Waiting guest for creating dump file"
                         " (%ssec)" % bsod_time)
            time.sleep(bsod_time)
            error.context("Send a system_reset monitor command", logging.info)
            vm.monitor.send_args_cmd(manual_reboot_cmd)

        session = vm.wait_for_login(timeout=timeout)

        if check_dump_cmd:
            error.context("Verify whether the dump files are generated",
                          logging.info)
            s, o = session.cmd_status_output(check_dump_cmd, 360)
            logging.debug("Output for check_dump_cmd command: %s" % o)
            if s:
                err_msg = "Could not find dump files in guest. Output: '%s'" % o
                raise error.TestFail(err_msg)
        if analyze_cmd:
            error.context("Analyze dump file in guest", logging.info)
            try:
                vm.copy_files_from(params["dump_path"], ".", timeout=100)
            except Exception:
                pass
            s, o = session.cmd_status_output(analyze_cmd, timeout=1200)
            if s:
                raise error.TestFail("Analysis Failed. Command: '%s'.\n\n"
                                     " Output: %s" % (analyze_cmd, o))
    finally:
        if session is not None and del_dump_cmd:
            try:
                session.sendline(del_dump_cmd)
            except Exception, e:
                # Ignore cleanup exception to avoid it overriding
                # the actual fault.
                logging.warn("Failed to delete dump files: '%s'", e)
