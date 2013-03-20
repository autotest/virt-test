import os, logging
from autotest.client.shared import error, utils
from autotest.client.virt import storage

@error.context_aware
def run_block_stream_set_speed(test, params, env):
    """
    block_stream_set_speed test:
    1). bootup guest and create livesnapshot
    2). start block stream job w/o limited speed, then query job status
    3). set block job speed and check speed set correctly

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    image_file = storage.get_image_filename(params, test.bindir)
    device_id = vm.get_block({"file": image_file})
    snapshot_file = os.path.splitext(image_file)[0] + "-snp"
    speed = int(params.get("limited_speed", 0))

    try:
        error.context("Creating live snapshot", logging.info)
        device_id = vm.live_snapshot(image_file, snapshot_file)
        if not device_id:
            raise error.TestFail("Fail to create live snapshot")
        error.context("Start block stream", logging.info)
        vm.monitor.block_stream(device_id, params.get("init_speed"))
        error.context("Query job status", logging.info)
        if not vm.monitor.query_block_job(device_id):
            raise error.TestFail("Fail to start block job", logging.info)
        error.context("Set limited speed", logging.info)
        vm.monitor.set_block_job_speed(device_id, speed)
        job = vm.monitor.query_block_job(device_id)
        if speed < job["speed"] / 1048576:
            raise error.TestFail("Current speed greater than limited speed",
                                 logging.info)
    finally:
        utils.system("rm -f %s" % snapshot_file)
