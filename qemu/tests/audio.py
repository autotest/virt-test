import logging
from autotest.client.shared import error

def run_audio(test, params, env):
    """
    Test guest audio:
    1) Boot guest with -soundhw ***
    2) Log into guest
    3) Write a file which contains random content to device /dev/dsp,check
    succeed or not
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    random_content_size = params.get("random_content_size")
    audio_test_cmd = params.get("audio_test_cmd") % random_content_size

    s, o = session.cmd_status_output(audio_test_cmd)
    if s != 0:
        raise error.TestFail("Test audio fail: %s" % o)
    logging.info("Guest audio test successfully finish")
