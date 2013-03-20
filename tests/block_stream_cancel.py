import os, logging
from autotest.client.shared import error, utils
from autotest.client.virt import storage
from autotest.client.virt import utils_misc

@error.context_aware
def run_block_stream_cancel(test, params, env):
    """
    block_stream_cancel test:
    1). bootup guest and create live snapshot
    2). start block stream job specify a non-existed snapshot as base
    3). set block job speed (configurable step)
    4). cancel block job

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    image_file = storage.get_image_filename(params, test.bindir)
    snapshot_file = os.path.splitext(image_file)[0] + "-snp"
    speed = int(params.get("limited_speed", 0))
    wait_time = int(params.get("wait_time", 5))

    try:
        error.context("Create live snapshot", logging.info)
        device_id = vm.live_snapshot(image_file, snapshot_file)
        if not device_id:
            raise error.TestFail("Fail to create livesnapshot")
        error.context("Start block stream job", logging.info)
        if vm.monitor.block_stream(device_id):
            raise error.TestFail("Fail to start block stream job")
        if speed:
            error.context("Set speed to %s MB/s" % speed, logging.info)
            if vm.monitor.set_block_job_speed(device_id, speed):
                raise error.TestFail("Fail to reset speed to %s MB/s" % speed)
        if not vm.monitor.query_block_job(device_id):
            raise error.TestFail("No active block job on the device")
        error.context("Cancel block stream job", logging.info)
        vm.monitor.cancel_block_job(device_id)
        if not utils_misc.wait_for(lambda:
                                   not vm.monitor.query_block_job(device_id),
                                   timeout=wait_time,
                                   text="Wait for canceling block job"):
            raise error.TestFail("Job still running, after %ss" % wait_time)
    finally:
        utils.system("rm -f %s" % snapshot_file)
