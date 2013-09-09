"""
kill_app.py - Kill specific application.

This test was created as a successor of almost the same rv_disconnect and
rv_video_close tests.
Simply close selected app. If app is not running, ends with error. Application
could be closed during migration or for any unwanted reason. This test checks
if application is running when it should .

"""
import logging
import os
from autotest.client.shared import error


def run_kill_app(test, params, env):
    """
    Test kills application. Application is given by name kill_app_name in
    params.
    It has to be defined if application is on guest or client with parameter
    kill_on_vms which should contain name(s) of vm(s) (separated with ',')

    @param test: KVM test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    kill_on_vms = params.get("kill_on_vms", "")
    vms = kill_on_vms.split(',')
    app_name = params.get("kill_app_name", None)
    logging.debug("vms %s", vms)
    if not vms:
        raise error.TestFail("Kill app test launched without any VM parameter")
    else:
        for vm in vms:
            logging.debug("vm %s", vm)
            if params.has_key(vm):
                kill_app(vm, app_name, params, env)


def kill_app(vm_name, app_name, params, env):
    """
    Kill selected app on selected VM

    @params vm_name - VM name in parameters
    @params app_name - name of application
    """
    vm = env.get_vm(params[vm_name])

    vm.verify_alive()
    vm_session = vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))
    # get PID of remote-viewer and kill it
    logging.info("Get PID of %s", app_name)
    vm_session.cmd("pgrep %s" % app_name)

    logging.info("Try to kill %s", app_name)
    vm_session.cmd("pkill %s" % app_name
                   .split(os.path.sep)[-1])
    vm.verify_alive()
    vm_session.close()
