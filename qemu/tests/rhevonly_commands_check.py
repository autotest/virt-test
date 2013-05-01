import re, logging
from autotest.client import utils
from autotest.client.shared import error

@error.context_aware
def run_rhevonly_commands_check(test, params, env):
    """
    rhevonly_commands_check test:
    1). bootup vm with human and qmp monitor
    2). check commands in black_list is inavaliable in monitor

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    black_list = list()
    black_list.extend(params.get("black_list").split())
    logging.info("Get black commands list: %s", black_list)
    if utils.system("rpm -q qemu-kvm-rhev", ignore_status=True) != 0:
        if vm.monitor.protocol == "human":
            cmds = vm.monitor.cmd("help")
            if cmds:
                cmd_list = re.findall("^(.*?) ", cmds, re.M)
                supported_cmds = [c for c in cmd_list if c]
        else:
            cmds = vm.monitor.cmd("query-commands")
            if cmds:
                supported_cmds = [n["name"] for n in cmds if
                                  n.has_key("name")]
        error.context("Verify black commands is inavaliable in monitor",
                      logging.info)
        ret = filter(lambda x: x in black_list, supported_cmds)
        if ret:
            raise error.TestFail("Unexpect commands found: %s" % ret)
    else:
        raise error.TestWarn("Unnecessary run this test on rhev package")
