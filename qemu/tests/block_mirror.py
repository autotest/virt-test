import os, logging, time
from autotest.client.shared import utils, error
from virttest import qemu_monitor, storage, env_process, data_dir, utils_misc


@error.context_aware
def run_block_mirror(test, params, env):
    """
    Test block mirroring functionality

    Test consists of two subtests:

    1) Mirror the guest and switch to the mirrored one
    2) Synchronize disk and then do continuous backup

    "qemu-img compare" is used to verify disk is mirrored successfully.
    """
    image_name = params.get("image_name", "image")
    image_format = params.get("image_format", "qcow2")
    image_mirror = utils_misc.get_path(data_dir.get_data_dir(),
                                       "%s-mirror.%s" % (image_name,
                                           image_format))
    block_mirror_cmd = params.get("block_mirror_cmd", "drive-mirror")
    qemu_img = params.get("qemu_img_binary")
    source_images = params.get("source_images", "image1").split()
    source_image = source_images[0]
    _params = params.object_params(source_image)
    speed = int(_params.get("default_speed", 0))
    sync = _params.get("full_copy").lower()
    if block_mirror_cmd.startswith("__"):
            sync = (sync == "full")
    mode = _params.get("create_mode", "absolute-paths")
    format = _params.get("target_format", "qcow2")
    check_event = _params.get("check_event")


    def check_block_jobs_info(device_id):
        """
        Verify block-jobs status reported by monitor command info block-jobs.

        @return: parsed output of info block-jobs
        """
        fail = 0
        status = dict()
        try:
            status = vm.get_job_status(device_id)
        except qemu_monitor.MonitorError, e:
            logging.error(e)
            fail += 1
            return status
        return status


    def run_mirroring(vm, device, dest, sync, speed=0, foramt="qcow2",
            mode="absolute-paths", complete = True):
        """
        Run block mirroring.

        @param vm: Virtual machine object
        @param device: Guest device that has to be mirrored
        @param dest: Location image has to be mirrored into
        @param speed: limited speed
        @param format: target image format
        @param mode: image create mode
        @param complete: If True, mirroring will complete (switch to mirror),
                         If False, finish image synchronization and keep
                         mirroring running (any changes will be mirrored)
        """
        vm.block_mirror(device, dest, speed, sync, format, mode)
        while True:
            status = check_block_jobs_info(device)
            if 'mirror' in status.get("type", ""):
                logging.info("[(Completed bytes): %s (Total bytes): %s "
                             "(Speed limit in bytes/s): %s]", status["offset"],
                             status["len"], status["speed"])
                if status["offset"] != int(status["len"]):
                    time.sleep(10)
                    continue
                elif vm.monitor.protocol == "qmp" and check_event == "yes":
                    if vm.monitor.get_event("BLOCK_JOB_READY") is None:
                        continue
                else:
                    logging.info("Target synchronized with source")
                    if complete:
                        logging.info("Start mirroring completing")
                        vm.pause()
                        vm.block_reopen(device, dest, format)
                        time.sleep(5)
                    else:
                        break
            elif not status:
                logging.info("Block job completed")
                break


    def compare_images(cmd, img1, img2):
        """
        Check if images are equal. Raise error.TestFail if images not equal.

        @param cmd: qemu-img executable
        @param img1: First image to compare
        @param img2: Second image to compare
        """
        logging.info("Comparing images")
        compare_cmd = "%s compare %s %s" % (cmd, img1, img2)
        rv = utils.run(compare_cmd, ignore_status=True)

        if rv.exit_status == 0:
            logging.info("Images are equal")
        elif rv.exit_status == 1:
            raise error.TestFail("Images differ - test failed")
        else:
            raise error.TestError("Error during image comparison")


    try:
        # Setup phase
        vm_name = params['main_vm']
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.create()

        timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=timeout)
        img_path = storage.get_image_filename(params, data_dir.get_data_dir())
        device_id = vm.get_block({"file": img_path})


        # Subtest 1 - Complete mirroring
        error.context("Testing complete mirroring")
        run_mirroring(vm, device_id, image_mirror, sync, speed, format, mode)
        _device_id = vm.get_block({"file": image_mirror})
        if device_id != _device_id:
            raise error.TestError("Mirrored image not being used by guest")
        error.context("Compare fully mirrored images")
        compare_images(qemu_img, img_path, image_mirror)
        vm.destroy()

        # Subtest 2 - Continuous backup
        error.context("Testing continuous backup")
        vm.create()
        session = vm.wait_for_login(timeout=timeout)
        run_mirroring(vm, device_id, image_mirror, sync,
                speed, format, mode, False)
        for fn in range(0,128):
            session.cmd("dd bs=1024 count=1024 if=/dev/urandom of=tmp%d.file"
                        % fn)
        time.sleep(10)
        vm.pause()
        time.sleep(5)
        error.context("Compare original and backup images")
        compare_images(qemu_img, img_path, image_mirror)
        vm.destroy()

    finally:
        if os.path.isfile(image_mirror):
            os.remove(image_mirror)
