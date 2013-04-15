import logging, commands, os, re
from autotest.client.shared import error, utils
from virttest import utils_test, utils_misc

def run_ext_unregister_vm(test, params, env):
    """
    Get the addresses of the vms, if the ip is in the list of the svr,
    unregister it.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    prompt = params.get("shell_prompt")
    login_timeout = float(params.get("login_timeout", 660))
    asvr_ip = params.get("asvr_ip", "10.66.70.163")
    asvr_user = params.get("asvr_user", "root")
    asvr_passwd = params.get("asvr_passwd", "123456")
    atest_basedir = params.get("atest_basedir", "/usr/local/autotest/cli")
    get_tm_list_cmd = params.get('get_tm_list_cmd')
    unregister_cmd = params.get('unregister_cmd')

    vm_nm_list = params.get("vms").split()
    vm_ip_list = []
    for vm_nm in vm_nm_list:
        vm = env.get_vm(vm_nm)
        vm.verify_alive()

        session = vm.wait_for_login(timeout=login_timeout)
        vm_ip_list.append(vm.get_address())
        logging.debug("%s --> %s" % (vm_nm, vm.get_address()))
        session.close()

    asvr_session = utils_test.get_svr_session(asvr_ip,
                                                  usrname=asvr_user,
                                                  passwd=asvr_passwd,
                                                  prompt=prompt)

    try:
        # Get all test machines (tms).
        # gather the autotest server test machine info
        get_tm_list_cmd = utils_test.fix_atest_cmd(atest_basedir,
                                                       get_tm_list_cmd,
                                                       asvr_ip)
        (s, o) = asvr_session.get_command_status_output(get_tm_list_cmd,
                                                        timeout=1200)
        if s != 0:
            raise error.TestError("Could not get the test machine info.")

        # since we just need to get the ip address from the output,
        # we do not need a general ip filter here.
        tm_list = re.findall('\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', o)
        logging.debug("We got test machine list: \n%s" % str(tm_list))

        # unregister
        unregister_cmd = utils_test.fix_atest_cmd(atest_basedir,
                                                      unregister_cmd,
                                                      asvr_ip)
        for tm in vm_ip_list:
            if tm in tm_list:
                # do unregister
                if asvr_session.get_command_status(unregister_cmd % tm,
                                                   timeout=1200) != 0:
                    raise error.TestError("Failed to unregister %s" % tm)
                logging.debug("%s unregistered!" % tm)
    finally:
        if asvr_session:
            asvr_session.close()

    logging.debug("Unregistration PASSED!")
