import os, time, logging
from autotest.client import utils
from autotest.client.shared import error
from virttest import storage, utils_misc


@error.context_aware
def run_block_stream_boot(test, params, env):
    """
    block_stream_with_reboot test:
    1). create live snapshot when boot/reboot
    2). start block device stream job wait for job done
    3). after job done check guest works fine

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """

    error.context("Bootup vm", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    image_file = storage.get_image_filename(params, test.bindir)
    snapshot_file = os.path.splitext(image_file)[0] + "-snp"
    reboot = "reboot" in params.get("name")

    try:
        if reboot:
            error.context("reboot guest", logging.info)
            session = vm.wait_for_login(timeout=timeout)
            bg = utils.InterruptedThread(vm.reboot, (session,))
            bg.start()
        else:
            #sleep some time for vm load os
            time.sleep(int(params.get("sleep_time", 3)))
        error.context("Creating live snapshot", logging.info)
        device_id = vm.live_snapshot(image_file, snapshot_file)
        if not device_id:
            raise error.TestFail("Fail to create livesnapshot")
        error.context("Start block stream job", logging.info)
        if vm.monitor.block_stream(device_id):
            raise error.TestFail("Fail to start block stream job")
        if utils_misc.wait_for(lambda:
                               not vm.monitor.query_block_job(device_id),
                               timeout=int(params.get("job_timeout", 3600)),
                               text="Wait for canceling block job") is None:
            raise error.TestFail("Wait job finish timeout")
        session = reboot and bg.join() or vm.wait_for_login(timeout=timeout)
        session.cmd(params.get("alive_check_cmd", "dir"))
    finally:
        utils.system("rm -f %s" % snapshot_file)
