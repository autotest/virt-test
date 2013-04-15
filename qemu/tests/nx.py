import os, logging
from autotest.client.shared import error


def run_nx(test, params, env):
    """
    try to exploit the guest to test whether nx(cpu) bit takes effect.

    1) boot the guest
    2) cp the exploit prog into the guest
    3) run the exploit

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    #
    exploit_file = os.path.join(test.bindir, 'tests_rsc/x64_sc_rdo.c')
    dst_dir = '/tmp'

    vm.copy_files_to(exploit_file, dst_dir)

    logging.info("Copy the Exploit file to guest succeed.")

    build_exploit = "gcc -o /tmp/nx_exploit /tmp/x64_sc_rdo.c"
    if session.get_command_status(build_exploit) != 0:
        raise error.TestError("Failed to build the exploit program")

    exec_exploit = "/tmp/nx_exploit"
    # if nx is enabled (by default), the program failed.
    # segmentation error. return value of shell is not zero.
    exec_res = session.get_command_status(exec_exploit)
    nx_on = params.get('nx_on')
    if nx_on == 'yes':
        print exec_res
        if exec_res is not None:
            logging.info('NX works good.')
            # using execstack to remove the protection
            enable_exec = 'cp /tmp/nx_exploit /tmp/nx_exploit_o && '
            enable_exec += 'execstack -s /tmp/nx_exploit'
            if session.get_command_status(enable_exec) != 0:
                raise error.TestError('Failed to enable the execstack')

            if session.get_command_status(exec_exploit) != 0:
                raise error.TestFail('NX is still protecting. Error.')
            else:
                logging.info('NX is disabled as desired. good')
        else:
            raise error.TestFail('Fatal Error: NX does not protect anything!')
    elif nx_on == "no":
        if exec_res:
            raise error.TestError('Error, the exploit program may be damaged.')
        else:
            logging.info('NX is disabled, and this TC passed.')
    session.close()
