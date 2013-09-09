import logging
import os
import shutil
import glob
import ConfigParser
from autotest.client.shared import error
from virttest import utils_misc, env_process


def run_unittest(test, params, env):
    """
    KVM RHEL-6 style unit test:
    1) Resume a stopped VM
    2) Wait for VM to terminate
    3) If qemu exited with code = 0, the unittest passed. Otherwise, it failed
    4) Collect all logs generated

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment
    """
    unittest_dir = os.path.join(test.builddir, 'unittests')
    if not os.path.isdir(unittest_dir):
        raise error.TestNAError("No unittest dir %s available (did you run the "
                                "build test first?)" % unittest_dir)
    os.chdir(unittest_dir)
    unittest_list = glob.glob('*.flat')
    if not unittest_list:
        raise error.TestNAError("No unittest files available (did you run the "
                                "build test first?)")
    logging.debug('Flat file list: %s', unittest_list)

    unittest_cfg = os.path.join(unittest_dir, 'unittests.cfg')
    parser = ConfigParser.ConfigParser()
    parser.read(unittest_cfg)
    test_list = parser.sections()

    if not test_list:
        raise error.TestError("No tests listed on config file %s" %
                              unittest_cfg)
    logging.debug('Unit test list: %s', test_list)

    if params.get('unittest_test_list'):
        test_list = params.get('unittest_test_list').split()
        logging.info('Original test list overriden by user')
        logging.info('User defined unit test list: %s', test_list)

    black_list = params.get('unittest_test_blacklist', '').split()
    if black_list:
        for b in black_list:
            if b in test_list:
                test_list.remove(b)
        logging.info('Tests blacklisted by user: %s', black_list)
        logging.info('Test list after blacklist: %s', test_list)

    nfail = 0
    tests_failed = []

    timeout = int(params.get('unittest_timeout', 600))

    extra_params_original = params.get('extra_params')

    for t in test_list:
        logging.info('Running %s', t)

        flat_file = None
        if parser.has_option(t, 'file'):
            flat_file = parser.get(t, 'file')

        if flat_file is None:
            nfail += 1
            tests_failed.append(t)
            logging.error('Unittest config file %s has section %s but no '
                          'mandatory option file', unittest_cfg, t)
            continue

        if flat_file not in unittest_list:
            nfail += 1
            tests_failed.append(t)
            logging.error('Unittest file %s referenced in config file %s but '
                          'was not found under the unittest dir', flat_file,
                          unittest_cfg)
            continue

        smp = None
        if parser.has_option(t, 'smp'):
            smp = int(parser.get(t, 'smp'))
            params['smp'] = smp

        extra_params = None
        if parser.has_option(t, 'extra_params'):
            extra_params = parser.get(t, 'extra_params')
            if not params.get('extra_params'):
                params['extra_params'] = ""
            params['extra_params'] += ' %s' % extra_params

        vm_name = params["main_vm"]
        params['kernel'] = os.path.join(unittest_dir, flat_file)

        testlog_path = os.path.join(test.debugdir, "%s.log" % t)

        testlog = None
        try:
            try:
                vm_name = params['main_vm']
                env_process.preprocess_vm(test, params, env, vm_name)
                vm = env.get_vm(vm_name)
                vm.create()
                vm.resume()
                testlog = vm.get_testlog_filename()

                msg = ("Waiting for unittest '%s' to complete, timeout %s" %
                       (t, timeout))
                if os.path.isfile(testlog):
                    msg += (", output in %s" % testlog)
                else:
                    testlog = None
                logging.info(msg)

                if not utils_misc.wait_for(vm.is_dead, timeout):
                    raise error.TestFail("Timeout elapsed (%ss)" % timeout)

                # Check qemu's exit status
                status = vm.process.get_status()

                # Check whether there's an isa_debugexit device in the vm
                isa_debugexit = 'isa-debug-exit' in vm.qemu_command

                if isa_debugexit:
                    good_status = 1
                else:
                    good_status = 0

                if status != good_status:
                    nfail += 1
                    tests_failed.append(t)
                    logging.error("Unit test %s failed", t)

            except Exception, e:
                nfail += 1
                tests_failed.append(t)
                logging.error('Exception happened during %s: %s', t, str(e))
        finally:
            try:
                if testlog is not None:
                    shutil.copy(vm.get_testlog_filename(), testlog_path)
                    logging.info("Unit test log collected and available "
                                 "under %s", testlog_path)
            except (NameError, IOError):
                logging.error("Not possible to collect logs")

        # Restore the extra params so other tests can run normally
        params['extra_params'] = extra_params_original

    if nfail != 0:
        raise error.TestFail("Unit tests failed: %s" % " ".join(tests_failed))
