import logging, commands, os, re
from autotest.client.shared import error, utils
from autotest.client.virt import utils_test

def run_ext_register_vm(test, params, env):
    """
    Boot and register test machine (vm) to the given autotest server.

    NOTE:
      Need to config the autotest server not to check host key, by
    setting "StrictHostKeyChecking" to "no" in /etc/ssh_config.

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    # session for autotest server
    prompt = params.get("shell_prompt")
    asvr_ip = params.get("asvr_ip", "10.66.70.163")
    asvr_user = params.get("asvr_user", "root")
    asvr_passwd = params.get("asvr_passwd", "123456")
    atest_basedir = params.get("atest_basedir", "/usr/local/autotest/cli")

    asvr_session = utils_test.get_svr_session(asvr_ip, "22",
                                                  asvr_user, asvr_passwd,
                                                  prompt)

    # get the ssh key of the server.
    (s, o) = asvr_session.get_command_status_output("cat ~/.ssh/id_rsa.pub")
    if s != 0:
        asvr_session.close()
        raise error.TestError("Get id_rsa.pub in the server failed.")
    o = o.strip() # to strip '\n'
    logging.debug("Check ssh key finished!\nstatus:\n%s\noutput:\n%s" % (s, o))


    # sessions for vms (the testing machines.)
    session_list = []
    vm_list = []
    # get the vm name list
    vm_nm_list = params.get("vms").split()
    add_host_cmd = utils_test.fix_atest_cmd(atest_basedir,
                                                params.get('add_host_cmd'),
                                                asvr_ip)
    get_tm_list_cmd = utils_test.fix_atest_cmd(atest_basedir,
                                                params.get('get_tm_list_cmd'),
                                                asvr_ip)

    try:
        tm_list = utils_test.get_svr_tm_lst(asvr_session, get_tm_list_cmd)

        for vm_nm in vm_nm_list:
            # login into vm
            vm = env.get_vm(vm_nm)
            vm.verify_alive()
            session = vm.wait_for_login(
                               timeout=int(params.get("login_timeout", 660)))
            vm_list.append(vm)
            session_list.append(session)
            vm_ip = vm.get_address()

            # vm is already registered?
            if vm_ip in tm_list:
                logging.debug("%s is registered, continue..." % vm_ip)
                continue

            # add the autotest server to trust list of the vm.
            if 0 != session.get_command_status("mkdir -p ~/.ssh && "\
                                "echo \"%s\" >> ~/.ssh/authorized_keys" % o):
                raise error.TestFail("Authorizing asvr failed.")

            logging.debug("Adding %s as test machine to the server..." % vm_ip)
            if 0 != asvr_session.get_command_status(add_host_cmd % vm_ip,
                                                    timeout=1200):
                raise error.TestFail("Adding host failed. vm_ip: %s" % vm_ip)

        # Check if the test machine is registered successfully.
        tm_list = utils_test.get_svr_tm_lst(asvr_session, get_tm_list_cmd)
        logging.debug("We got test machine list: \n%s" % str(tm_list))

        for vm in vm_list:
            if vm.get_address() not in tm_list:
                raise error.TestError("Adding %s failed." % vm.get_address())

    finally:
        if asvr_session:
            asvr_session.close()
        for s in session_list:
            if s:
                s.close()

    logging.debug("Finished good.")

