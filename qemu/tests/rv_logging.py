"""
rv_logging.py - Tests the logging done during a remote-viewer session
Verifying the qxl driver is logging correctly on the guest
Verifying that the spice vdagent daemon logs correctly on the guest

Requires: connected binaries remote-viewer, Xorg, gnome session

"""
import logging
import os
from autotest.client.shared import error
from virttest import utils_misc, utils_spice


def run_rv_logging(test, params, env):
    """
    Tests the logging of remote-viewer

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    # Get the necessary parameters to run the tests
    log_test = params.get("logtest")
    qxl_logfile = params.get("qxl_log")
    spicevdagent_logfile = params.get("spice_log")
    interpreter = params.get("interpreter")
    script = params.get("guest_script")
    script_params = params.get("script_params", "")
    dst_path = params.get("dst_dir", "guest_script")
    script_call = os.path.join(dst_path, script)
    testing_text = params.get("text_to_test")

    guest_vm = env.get_vm(params["guest_vm"])
    guest_vm.verify_alive()
    guest_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))
    guest_root_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)),
        username="root", password="123456")

    scriptdir = os.path.join("scripts", script)
    script_path = utils_misc.get_path(test.virtdir, scriptdir)

    # Copying the clipboard script to the guest to test spice vdagent
    logging.info("Transferring the clipboard script to the guest,"
                 "destination directory: %s, source script location: %s",
                 dst_path, script_path)
    guest_vm.copy_files_to(script_path, dst_path, timeout=60)

    # Some logging tests need the full desktop environment
    guest_session.cmd("export DISPLAY=:0.0")

    # Logging test for the qxl driver
    if(log_test == 'qxl'):
        logging.info("Running the logging test for the qxl driver")
        guest_root_session.cmd("grep -i qxl " + qxl_logfile)
    # Logging test for spice-vdagent
    elif(log_test == 'spice-vdagent'):
        logging.info("Running the logging test for spice-vdagent daemon")
        utils_spice.start_vdagent(guest_root_session, test_timeout=15)

        # Testing the log after stopping spice-vdagentd
        utils_spice.stop_vdagent(guest_root_session, test_timeout=15)
        output = guest_root_session.cmd("tail -n 3 " + spicevdagent_logfile +
                                        " | grep 'vdagentd quiting'")

        # Testing the log after starting spice-vdagentd
        utils_spice.start_vdagent(guest_root_session, test_timeout=15)
        output = guest_root_session.cmd("tail -n 2 " + spicevdagent_logfile +
                                        " | grep 'opening vdagent virtio channel'")

        # Testing the log after restart spice-vdagentd
        utils_spice.restart_vdagent(guest_root_session, test_timeout=10)
        output = guest_root_session.cmd("tail -n 2 " + spicevdagent_logfile +
                                        " | grep 'opening vdagent virtio channel'")

        cmd = ("echo \"SPICE_VDAGENTD_EXTRA_ARGS=-dd\">"
               "/etc/sysconfig/spice-vdagentd")
        guest_root_session.cmd(cmd)
        utils_spice.restart_vdagent(guest_root_session, test_timeout=10)

        # Finally test copying text within the guest
        cmd = "%s %s %s %s" % (interpreter, script_call,
                               script_params, testing_text)

        logging.info("This command here: " + cmd)

        try:
            logging.debug("------------ Script output ------------")
            output = guest_session.cmd(cmd)

            if "The text has been placed into the clipboard." in output:
                logging.info("Copying of text was successful")
            else:
                raise error.TestFail("Copying to the clipboard failed ELSE",
                                     output)
        except:
            raise error.TestFail("Copying to the clipboard failed try" +
                                 " block failed")

        logging.debug("------------ End of script output of the Copying"
                      " Session ------------")

        output = guest_root_session.cmd("tail -n 3 " + spicevdagent_logfile +
                                        " | grep 'clipboard grab'")

    else:
        # Couldn't find the right test to run
        guest_session.close()
        guest_root_session.close()
        raise error.TestFail("Couldn't find the right test to run,"
                             + " check cfg files.")
    guest_session.close()
