import sys, os, logging, time
from autotest.client.shared import error
from autotest.client.virt import ppm_utils


def run_screendump(test, params, env):
    """
    KVM screendump test:
    1) Log into a guest
    2) Send a reboot command to the guest
    3) seed a screendump command to the guest before/during rebooting.
    4) verify the screendump file.

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    reboot_scrdump_filename = os.path.join(test.debugdir, "reboot_scrdump")
    logging.info("Fork a child process for doing 'screendump'")
    sys.stdout.flush()
    sys.stderr.flush()
    scrdump_count = int(params.get("scrdump_count", 100))
    logging.info("Screendump count: %d" % scrdump_count)
    timeout=int(params.get("login_timeout", 360))
    scrdump_time_interval = float(params.get("scrdump_time_interval", 1.0))
    pid = os.fork()
    if pid:
        # Parent
        session = vm.wait_for_login(timeout=timeout)

        try:
            time.sleep(int(params.get("sleep_before_reset", 10)))
            session = vm.reboot(session,
                                   params.get("reboot_method","shell"))
        finally:
            session.close()
            (pid, status) = os.waitpid(pid,0)
            if status == 1:
                raise error.TestFail("Screendump command failed")
            if status == 2:
                raise error.TestError("Got invalid screendump file.")
            logging.info("Screendump finished successfully")
    else:
        # Child process
        for i in range(scrdump_count):
            ppm_file = "%s_%s.ppm" % (reboot_scrdump_filename,i)
            cmd = "screendump %s" %ppm_file
            try:
                vm.monitor.cmd(cmd)
            except Exception:
                pass
            time.sleep(scrdump_time_interval)
        ppm_check = 1
        for i in range(scrdump_count):
            if ppm_utils.image_verify_ppm_file(ppm_file):
                logging.debug("Found screendump file: %s" % ppm_file)
            else:
                ppm_check = 0
                logging.error("Invalid screendump file: %s" % ppm_file)
        if 0 == ppm_check:
            os._exit(2)
        os._exit(0)
