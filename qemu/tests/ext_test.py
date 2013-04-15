import logging, commands, os, re, time
from autotest.client.shared import error, utils
from virttest import utils_test, utils_misc

def run_ext_test(test, params, env):
    """
    Run the given test from the autotest server on the vms.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    prompt = params.get("shell_prompt")
    asvr_ip = params.get("asvr_ip", "10.66.70.163")
    asvr_user = params.get("asvr_user", "root")
    asvr_passwd = params.get("asvr_passwd", "123456")
    atest_basedir = params.get("atest_basedir", "/usr/local/autotest/cli")
    stat_tm_cmd = params.get('stat_tm_cmd')
    asvr_job_timeout = float(params.get('asvr_job_timeout', '1200'))
    login_timeout = float(params.get("login_timeout", "1200"))

    get_tm_list_cmd = utils_test.fix_atest_cmd(atest_basedir,
                                                params.get('get_tm_list_cmd'),
                                                asvr_ip)

    asvr_session = utils_test.get_svr_session(asvr_ip,
                                                  usrname=asvr_user,
                                                  passwd=asvr_passwd,
                                                  prompt=prompt)
    vm_nm_list = params.get("vms").split()
    vm_list = []

    try:
        # gather the autotest server test machine info
        tm_list = utils_test.get_svr_tm_lst(asvr_session, get_tm_list_cmd)
        logging.debug("We got test machine list: \n%s" % str(tm_list))

        for vm_nm in vm_nm_list:
            # login into vm
            vm = env.get_vm(vm_nm)
            vm.verify_alive()
            session = vm.wait_for_login(timeout=login_timeout)
            vm_list.append(vm)
            session.close()

        #FIXME: for now we only support only one vm.
        test_machine = vm_list[0].get_address()
        if test_machine not in tm_list:
            raise error.TestFail("tm %s is not registered." % test_machine)

        stat_tm_cmd = utils_test.fix_atest_cmd(atest_basedir,
                                                   stat_tm_cmd,
                                                   asvr_ip) % test_machine
        logging.debug("stat test machine command: %s" % stat_tm_cmd)


        def is_tm_ready():
            (s, o) = asvr_session.get_command_status_output(stat_tm_cmd)
            if s != 0:
                logging.error("Failed to get status of test machine.")
                return False
            logging.debug("Test machine status report:\n%s" % o)

            if len(re.findall("Status\:\ Ready", o)) != 1:
                return False
            return True


        logging.debug("Waiting for test machine to be ready...")
        if not utils_misc.wait_for(is_tm_ready, asvr_job_timeout, 5.0, 5.0):
            raise error.TestError("The test machine is not ready.")

        # get the name of the test to run, and get the job name.
        testname = params.get("testname")
        job_tag = params.get("job_tag")
        version_tag = params.get("version_tag", "kvm_auto")
        job_name = ''.join([testname, job_tag])
        # append the kvm version to the job name
        if version_tag == "kvm_auto":
            version_tag = utils_misc.get_version()
            job_name = ''.join([job_name, version_tag])


        create_job_cmd = params.get('create_job_cmd') % \
                                   (testname, test_machine, job_name)
        create_job_cmd = utils_test.fix_atest_cmd(atest_basedir,
                                                      create_job_cmd,
                                                      asvr_ip)
        logging.debug("Autotest server job cmd: %s" % create_job_cmd)

        # ./cli/atest would exit in a second actually, the timeout is just for
        # 'in case'.
        (s, o) = asvr_session.get_command_status_output(create_job_cmd,
                                                        timeout=3000)
        if s != 0:
            raise error.TestFail("Failed to create job in atserver")

        logging.debug("Job %s created.\n%s" % (testname, o))
        # get the job id.
        m = re.match(".*\n*Created job:.*\n.*\(id\ (\d+)\)", o)
        if m is None:
            raise error.TestError("Output of creating job is illegal.")

        job_id = m.group(1)
        logging.debug("We got job id: %s" % str(job_id))

        # Make sure the job is listed in autotest server,
        # and wait until it ends.
        let_svr_breath = int(params.get('let_svr_breath', '360'))
        query_job_cmd = utils_test.fix_atest_cmd(atest_basedir,
                                                params.get('query_job_cmd'),
                                                asvr_ip)

        def is_job_in_list():
            """
            Is the job with job_id in the job list of autotest server.
            """
            (s, o) = asvr_session.get_command_status_output(query_job_cmd)
            if s != 0:
                logging.error("Failed to query job in atserver.")
                return False

            # the job finished, or timeout.
            job_list = re.findall('\n(\d+)\ {2,}', o)
            if job_id in job_list:
                return True
            return False


        logging.debug("Waiting for job to be listed in server...")
        if not utils_misc.wait_for(is_job_in_list, asvr_job_timeout, 60.0, 3.0):
            raise error.TestFail("Failed to list the job, id: %s"% str(job_id))

        logging.debug("Waiting for job to finish...")
        if not utils_misc.wait_for(lambda: not is_job_in_list(),
                                    asvr_job_timeout,
                                    60.0, 10.0):
            raise error.TestFail("Job running timeout.")

        logging.debug("Job finished, waiting for a while for the cleanup...")
        time.sleep(let_svr_breath)

        # query status of the job
        stat_job_cmd = utils_test.fix_atest_cmd(atest_basedir,
                                                params.get('stat_job_cmd'),
                                                asvr_ip) % job_id
        (s, o) = asvr_session.get_command_status_output(stat_job_cmd,
                                                        timeout=1200)
        if s != 0:
            raise error.TestFail("Failed to get status of job %s" % job_id)
        logging.debug("Job status report:\n%s" % o)

## job stat command output
#
# Id  Name                      Priority Status Counts       Host Status
#  6  testname-katcTIME-kvm_ver Medium   Completed=1(100.0%) Completed="IPaddr"
##
        regex='%s\ +.+\ +.+\ +Completed\=\d+\(.+\)\ +Completed\=\"?%s\"?'%\
                    (str(job_id), test_machine)
        # since the job id and test machine ip is fixed in the regex,
        # the result should be unique.
        if len(re.findall(regex, o)) != 1:
            raise error.TestFail("The job is FAILED in autotest server.")
        logging.debug("Job %s: %s PASSED" % (str(job_id), job_name))

        # wait for test machine cleanup?
        if params.get('wait_tm_cleanup') == 'yes':
            logging.debug("Waiting for test machine to cleanup...")
            if not utils_misc.wait_for(is_tm_ready,asvr_job_timeout,10.0, 10.0):
                raise error.TestError("The test machine is not ready.")

    finally:
        if asvr_session:
            asvr_session.close()

    logging.debug("Finished good.")
