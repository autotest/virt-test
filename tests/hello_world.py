import logging, time
from autotest.client import utils
from autotest.client.shared import error

@error.context_aware
def run_hello_world(test, params, env):
    """
    KVM Autotest 'hello world' Test

    1) Boot the vm
    2) Echo hello,world in guest using shell session.
    3) Echo hello,world in guest and get the output.
    4) Send a monitor command.
    5) Echo hello,world in the host using shell
    6) Get a parameter from the config file.

    @param test: KVM test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    error.context("Boot the vm", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    try:
        timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=timeout)

        #send command to the guest,using session command.
        error.context("Echo hello,world in guest using shell session",
                      logging.info)
        session.sendline("echo hello,world")

        error.context("Echo hello,world in guest and get the output",
                      logging.info)
        status, cmd_output = session.cmd_status_output("echo hello,world",
                                                       timeout=60)
        logging.info("Exit status: '%s', output: '%s'", status, cmd_output)
    finally:
        session.close()

    #send command to the guest,using monitor command.
    error.context("Send a monitor command", logging.info)
    monitor_cmd_ouput = vm.monitor.info("status")
    logging.info("Monitor returns '%s'", monitor_cmd_ouput)

    #send command to host
    error.context("Echo hello,world in the host using shell", logging.info)
    host_cmd_output = utils.system_output("echo hello,world")
    logging.info("The host cmd outputs '%s'", host_cmd_output)

    error.context("Get a parameter from the config file", logging.info)
    sleep_time = int(params.get("sleep_time"))
    logging.info("Sleep '%d' seconds.", sleep_time)
    time.sleep(sleep_time)
