import logging
from autotest.client.shared import error
from virttest import qemu_monitor


@error.context_aware
def run_monitor_cmds_check(test, params, env):
    """
    monitor_cmds_check test:
    1). bootup vm with human and qmp monitor
    2). check commands in black_list is unavaliable in monitor

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.

    Notes:
        Please run this test with qemu/control.kernel-version to ensure it
        only run when requried package installed;
    """

    def is_supported(cmd):
        try:
            vm.monitor.verify_supported_cmd(cmd)
            return True
        except qemu_monitor.MonitorNotSupportedCmdError:
            return False

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    protocol = vm.monitor.protocol

    black_cmds = params.get("black_cmds", "").split()
    error.context("Verify black commands are unavaliable in '%s' monitor"
                  % protocol, logging.info)
    logging.info("Black commands: %s" % black_cmds)
    cmds = [cmd for cmd in black_cmds if is_supported(cmd)]
    if cmds:
        msg = "Unexpected commands %s found in %s monitor" % (cmds, protocol)
        raise error.TestFail(msg)
