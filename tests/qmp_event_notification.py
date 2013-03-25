import logging, time, commands
from autotest.client.shared import error
from autotest.client.virt import utils_misc


def run_qmp_event_notification(test, params, env):
    """
    Test hdparm setting on linux guest os, this case will:
    1) Set/record parameters value of hard disk to low performance status.
    2) Perform device/cache read timings then record the results.
    3) Set/record parameters value of hard disk to high performance status.
    4) Perform device/cache read timings then compare two results.

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environmen.
    """

    if not utils_misc.qemu_has_option("qmp"):
        logging.info("Host qemu does not support qmp. Ignore this case!")
        return
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    callback = {"host_cmd": commands.getoutput,
                "guest_cmd": session.get_command_output,
                "monitor_cmd": vm.monitor.send_args_cmd,
                "qmp_cmd": vm.monitors[1].send_args_cmd}

    def send_cmd(cmd):
        if cmd_type in callback.keys():
            return callback[cmd_type](cmd)
        else:
            raise error.TestError("cmd_type is not supported")


    event_cmd = params.get("event_cmd")
    cmd_type = params.get("event_cmd_type")
    event_check = params.get("event_check")
    timeout = int(params.get("check_timeout",360))
    action_check = params.get("action_check")


    if params.get("pre_event_cmd"):
        send_cmd(params.get("pre_event_cmd"))

    cmd_o = send_cmd(event_cmd)

    end_time = time.time() + timeout
    qmp_monitors = []
    for monitor in vm.monitors:
        monitor_params = params.object_params(monitor.name)
        if monitor_params.get("monitor_type") == "qmp":
            qmp_monitors += [monitor]
    qmp_num = len(qmp_monitors)
    logging.info("Try to get qmp events in %s seconds!" % timeout)
    while time.time() < end_time:
        for monitor in qmp_monitors:
            event = monitor.get_event(event_check)
            if event_check == "WATCHDOG":
                if event and event['data']['action'] == action_check:
                    logging.info("Receive watchdog %s event notification"
                                  % action_check)
                    qmp_num -= 1
                    qmp_monitors.remove(monitor)
            else:
                if event:
                    logging.info("Receive qmp %s event notification"
                                  % event_check)
                    qmp_num -= 1
                    qmp_monitors.remove(monitor)
        time.sleep(5)
        if qmp_num <= 0:
            break

    if qmp_num >0:
        raise error.TestFail("Did not receive qmp %s event notification"
                       % event_check)

    if params.get("post_event_cmd"):
        send_cmd(params.get("post_event_cmd"))
    session.close()
