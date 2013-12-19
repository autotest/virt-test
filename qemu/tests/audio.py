from autotest.client.shared import error


@error.context_aware
def run(test, params, env):
    """
    Test guest audio:

    1) Boot guest with -soundhw ***
    2) Log into guest
    3) Write a file which contains random content to audio device, check
       whether it succeeds.
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    random_content_size = params.get("random_content_size")
    audio_device = params.get("audio_device")

    error.context("Verifying whether /dev/dsp is present")
    session.cmd("test -c %s" % audio_device)
    error.context("Trying to write to the device")
    session.cmd("dd if=/dev/urandom of=%s bs=%s count=1" %
                (audio_device, random_content_size))
