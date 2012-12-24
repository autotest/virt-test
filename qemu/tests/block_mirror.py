import re, os, logging, time
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
    image_orig = "%s.%s" % (image_name, image_format)
    image_mirror = utils_misc.get_path(data_dir.get_data_dir(),
                                       "%s-mirror.%s" % (image_name, image_format))
    drive_format = params.get("drive_format")
    block_mirror_cmd = params.get("block_mirror_cmd", "drive-mirror")
    device_id = "None"
    qemu_img = params.get("qemu_img_binary")


    def check_block_jobs_info():
        """
        Verify block-jobs status reported by monitor command info block-jobs.

        @return: parsed output of info block-jobs
        """
        fail = 0

        try:
            output = vm.monitor.info("block-jobs")
        except qemu_monitor.MonitorError, e:
            logging.error(e)
            fail += 1
            return None, None
        return (re.match("[\w ]+", str(output)), re.findall("\d+", str(output)))


    def run_mirroring(vm, cmd, device, dest, complete = True):
        """
        Run block mirroring.

        @param vm: Virtual machine object
        @param cmd: Command for start mirroring
        @param device: Guest device that has to be mirrored
        @param dest: Location image has to be mirrored into
        @param complete: If True, mirroring will complete (switch to mirror),
                         If False, finish image synchronization and keep
                         mirroring running (any changes will be mirrored)
        """
        vm.monitor.cmd("%s %s %s" % (cmd, device, dest))

        while True:
            blkjobout, blkjobstatus = check_block_jobs_info()
            if 'mirror' in blkjobout.group(0):
                logging.info("[(Completed bytes): %s (Total bytes): %s "
                             "(Speed limit in bytes/s): %s]", blkjobstatus[-3],
                             blkjobstatus[-2], blkjobstatus[-1])
                if int(blkjobstatus[-3]) != int(blkjobstatus[-2]):
                    time.sleep(10)
                    continue
                else:
                    logging.info("Target synchronized with source")
                    if complete:
                        logging.info("Start mirroring completing")
                        vm.monitor.cmd("stop")
                        vm.monitor.cmd("block_job_complete %s" % device)
                        time.sleep(5)
                    else:
                        break
            elif 'No' in blkjobout.group(0):
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
        vm_name = params.get('main_vm')
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.create()

        timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=timeout)
        img_path = storage.get_image_filename(params, data_dir.get_data_dir())

        if 'ide' in drive_format:
            device_id = " id0-hd0"
        elif 'virtio' in drive_format:
            device_id = " virtio0"
        else:
            raise error.TestNAError("Drive format %s is not supported" %
                                    drive_format)

        # Subtest 1 - Complete mirroring
        error.context("Testing complete mirroring")
        run_mirroring(vm, block_mirror_cmd, device_id, image_mirror)
        output = vm.monitor.info("block")
        if image_orig in output or image_mirror not in output:
            raise error.TestError("Mirrored image not being used by guest")
        error.context("Compare fully mirrored images")
        compare_images(qemu_img, img_path, image_mirror)
        vm.destroy()

        # Subtest 2 - Continuous backup
        error.context("Testing continuous backup")
        vm.create()
        session = vm.wait_for_login(timeout=timeout)
        run_mirroring(vm, block_mirror_cmd, device_id, image_mirror,False)
        if image_orig in output or image_mirror not in output:
            raise error.TestError("Mirrored image not used by guest")
        for fn in range(0,128):
            session.cmd("dd bs=1024 count=1024 if=/dev/urandom of=tmp%d.file"
                        % fn)
        time.sleep(10)
        vm.monitor.cmd("stop")
        time.sleep(5)
        error.context("Compare original and backup images")
        compare_images(qemu_img, img_path, image_mirror)
        vm.destroy()

    finally:
        if os.path.isfile(image_mirror):
            os.remove(image_mirror)
