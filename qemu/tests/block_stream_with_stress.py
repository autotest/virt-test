import os, logging
from autotest.client.shared import error
from virttest import utils_test
from virttest import storage, utils_misc, data_dir

@error.context_aware
def run_block_stream_with_stress(test, params, env):
    """
    block_stream_with_stress test:
    1). boot guest
    2). make guest under heavyload status
    3). create live snpshot file and start block stream job
    4). wait for it done correctly

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    image_filename = storage.get_image_filename(params, data_dir.get_data_dir())
    device_id = vm.get_block({"file": image_filename})
    snapshot_file = os.path.splitext(image_filename)[0] + "-snp"
    sub_test = params.get("pre_test")
    start_cmd = params.get("start_cmd")

    def is_job_done():
        """
        Query block job status to check is job finished
        """
        job = vm.monitor.query_block_job(device_id)
        if job:
            processed = float(job["offset"]) / job["len"] * 100
            logging.debug("%s, rocessed: %.2f" % (job["type"], processed))
            return False
        logging.info("block stream job done")
        return True

    try:
        utils_test.run_virt_sub_test(test, params, env, sub_type=sub_test)
        error.context("Heavy load in guest ...", logging.info)
        if start_cmd.startswith("stress"):
            cpu = int(params.get("smp", 1))
            mem = int(params.get("mem", 1024))
            start_cmd = start_cmd.format(cpu=cpu,
                                         vm=cpu * 2,
                                         mem=(mem - 512) / cpu)
        session.sendline(start_cmd)
        error.context("Creating live snapshot", logging.info)
        if vm.monitor.live_snapshot(device_id, snapshot_file):
            raise error.TestFail("Fail to create live snapshot")
        error.context("Start block device stream job", logging.info)
        if vm.monitor.block_stream(device_id):
            raise error.TestFail("Fail to start block stream job")
        if not utils_misc.wait_for(is_job_done,
                               timeout=int(params.get("job_timeout", 2400)),
                               text="wait job done, it will take long time"):
            raise error.TestFail("Wait job finish timeout")
    finally:
        if session:
            session.close()
        if os.path.isfile(snapshot_file):
            os.remove(snapshot_file)
