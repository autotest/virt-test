import logging, commands
from qemu.tests import autotest_control


def run_netperf2(test, params, env):
    """
    Run netperf2 on two guests:
    1) One as client while the other is server
    2) Run netserver on server guest using control.server
    3) Run netperf on client guest using control.client

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment
    """
    server_vm = env.get_vm(params["main_vm"])
    server_vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session1 = server_vm.wait_for_login(timeout=login_timeout)

    client_vm = env.get_vm(params.get("client_vm"))
    client_vm.verify_alive()
    session2 = client_vm.wait_for_login(timeout=login_timeout)


    def fix_control(type, session, control):
        content = """
job.run_test('netperf2',
              server_ip='%s',
              client_ip='%s',
              role='%s',
              tag='%s')
""" % (server_vm.get_address(), client_vm.get_address(), type, type)
        cmd = 'echo "%s" > /tmp/%s' % (content, control)

        commands.getoutput(cmd)
        session.get_command_output("service iptables stop")
        session.close()

    fix_control("server", session1, "control.server")
    fix_control("client", session2, "control.client")

    params['test_name'] = 'netperf2'
    params['test_timeout'] = '600'

    # Setup netserver on server_vm
    logging.info("Setting up server vm")
    autotest_control.run_autotest_control_background(test, params, env,
                                           test_name = "netperf2",
                        test_control_file = "/tmp/control.server")

    # Run netperf on client vm
    logging.info("Setting up client vm")
    params['test_control_file'] = '/tmp/control.client'
    params['main_vm'] = params.get("client_vm")
    autotest_control.run_autotest_control(test, params, env)
