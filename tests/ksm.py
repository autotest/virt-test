import re
import os
import logging
import shutil
from autotest.client.shared import utils, error
from virttest import utils_misc


def test_setting_params(ksmctler, params):
    """
    Test setting writable params.

    1.Get default values and create new values according delta
    2.Set new values
    3.Recover default values
    """
    value_delta = int(params.get("ksm_value_delta", 10))
    ksm_run = int(params.get("ksm_run", 1))
    writable_features = ksmctler.get_writable_features()
    # Get default value of ksm parameters
    default_values = {}
    for key in writable_features:
        default_values[key] = int(ksmctler.get_ksm_feature(key))
    # New value to be set
    set_values = {}
    for key in default_values.keys():
        if key == "run":
            set_values[key] = ksm_run
        else:
            set_values[key] = default_values[key] + value_delta
    logging.debug("\nDefault parameters:%s\n"
                  "Set parameters:%s", default_values, set_values)

    try:
        # Setting new value
        try:
            ksmctler.set_ksm_feature(set_values)
            # Restart ksm service to check
            ksmctler.restart_ksm()
        except error.CmdError, detail:
            raise error.TestFail("Set parameters failed:%s" % str(detail))

        fail_flag = 0
        for key,value in set_values.items():
            if ksmctler.get_ksm_feature(key) != str(value):
                logging.error("Set value do not match:%s - %s", key, value)
                fail_flag = 1
        if fail_flag:
            raise error.TestFail("Set writable parameters failed.")
    finally:
        logging.debug("Recover parameters' default value...")
        ksmctler.set_ksm_feature(default_values)


def test_ksmtuned_service(ksmctler, params):
    """
    Test if ksmtuned service works well.

    1.Set debug options for ksmtuned
    2.Check if debug log is created
    """
    def backup_config(ksmtuned_conf):
        shutil.copy(ksmtuned_conf, "%s.bak" % ksmtuned_conf)
        return "%s.bak" % ksmtuned_conf

    def debug_ksmtuned(log_path, debug, ksmtuned_conf="/etc/ksmtuned.conf"):
        try:
            fd = open(ksmtuned_conf, 'r')
            contents = fd.readlines()
            fd.close()
        except IOError, e:
            raise error.TestFail("Open ksmtuned config file failed:%s" % e)

        new_contents = []
        for con in contents:
            if re.match("^.*LOGFILE.*", con):
                con = "LOGFILE=%s\n" % log_path
            elif re.match("^.*DEBUG.*", con):
                con = "DEBUG=%s\n" % debug
            new_contents.append(con)
        logging.debug("\nksmtuned configures:\n%s", new_contents)
        ni = iter(new_contents)
        try:
            fd = open(ksmtuned_conf, 'w')
            fd.writelines(ni)
            fd.close()
        except IOError, e:
            raise error.TestFail("Write options to config file failed:%s" % e)

    log_path = params.get("ksmtuned_log_path", "/var/log/test_ksmtuned")
    debug = params.get("ksmtuned_debug", 1)

    is_ksmtuned_running = False
    if ksmctler.get_ksmtuned_pid():
        is_ksmtuned_running = True
    else:
        ksmctler.start_ksmtuned()

    # Configure file of ksmtuned: /etc/ksmtuned.conf
    ksmtuned_conf = "/etc/ksmtuned.conf"
    try:
        ksmtuned_backup = backup_config(ksmtuned_conf)
        debug_ksmtuned(log_path, debug)
        ksmctler.restart_ksmtuned()
        if not os.path.isfile(log_path):
            raise error.TestFail("Debug file of ksmtuned is not created.")
    finally:
        try:
            shutil.move(ksmtuned_backup, ksmtuned_conf)
        except OSError:
            pass
        try:
            os.remove(log_path)
        except OSError:
            pass    # file do not exists


def run(test, params, env):
    """
    Simple test for ksm services.
    """
    ksm_ref = params.get("ksm_ref")
    ksmctler = utils_misc.KSMController()
    if ksm_ref == "set_params":
        test_setting_params(ksmctler, params)
    elif ksm_ref == "ksmtuned":
        test_ksmtuned_service(ksmctler, params)
