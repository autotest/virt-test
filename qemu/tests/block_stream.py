import re, os, logging, time
from autotest.client.shared import utils, error
from virttest import qemu_monitor, env_process, data_dir, storage


@error.context_aware
def run_block_stream(test, params, env):
    """
    Test block streaming functionality.

    1) Create a image_bak.img with the backing file image.img
    2) Start the image_bak.img in qemu command line.
    3) Request for block-stream ide0-hd0/virtio0
    4) Wait till the block job finishs
    5) Check for backing file in image_bak.img
    6) TODO: Check for the size of the image_bak.img should not exceeds the image.img
    7) TODO(extra): Block job completion can be check in QMP
    """
    image_format = params["image_format"]
    image_name = storage.get_image_filename(params, data_dir.get_data_dir())
    backing_file_name = "%s_bak" % image_name
    snapshot_format = params.get("snapshot_format", "qcow2")
    qemu_img = params["qemu_img_binary"]


    def check_block_jobs_info(device_id):
        """
        Verify the status of block-jobs reported by monitor command info block-jobs.
        @return: parsed output of info block-jobs
        """
        fail = 0
        status = {}
        try:
            status = vm.get_job_status(device_id)
        except qemu_monitor.MonitorError, e:
            logging.error(e)
            fail += 1
            return status
        return status

    try:
        backing_file = "%s.%s" % (backing_file_name, image_format)
        # Remove the existing backing file
        if os.path.isfile(backing_file):
            os.remove(backing_file)

        # Create the new backing file
        create_cmd = "%s create -b %s -f %s %s" % (qemu_img,
                                                   image_name,
                                                   snapshot_format,
                                                   backing_file)
        error.context("Creating backing file")
        utils.system(create_cmd)

        info_cmd = "%s info %s" % (qemu_img, image_name)
        error.context("Image file can not be find")
        results = utils.system_output(info_cmd)
        logging.info("Infocmd output of basefile: %s" ,results)

        # Set the qemu harddisk to the backing file
        logging.info("Original image file is: %s", image_name)
        params['image_name'] = backing_file_name
        logging.info("Param image_name changed to: %s", params['image_name'])

        # Start virtual machine, using backing file as its harddisk
        vm_name = params['main_vm']
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.verify_alive()
        timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=timeout)

        info_cmd = "%s info %s" % (qemu_img, backing_file)
        error.context("Image file can not be find")
        results = utils.system_output(info_cmd)
        logging.info("Infocmd output of backing file before block streaming: "
                     "%s", results)

        if not re.search("backing file:", str(results)):
            raise error.TestFail("Backing file is not available in the "
                                 "backdrive image")

        device_id = vm.get_block({"file": backing_file})
        vm.block_stream(device_id, speed=0)

        while True:
            info = check_block_jobs_info(device_id)
            if info.get("type","") == "stream":
                logging.info("[(Completed bytes): %s (Total bytes): %s "
                             "(Speed in bytes/s): %s]", info["len"],
                             info["offset"], info["speed"])
                time.sleep(10)
                continue
            if not info:
                logging.info("Block job completed")
                break

        info_cmd = "%s info %s" % (qemu_img, backing_file)
        error.context("Image file can not be find")
        results = utils.system_output(info_cmd)
        logging.info("Infocmd output of backing file after block streaming: %s",
                     results)

        if re.search("backing file:", str(results)):
            raise error.TestFail(" Backing file is still available in the "
                                 "backdrive image")
        # TODO
        # The file size should be more/less equal to the "backing file" size

        # Shutdown the virtual machine
        vm.destroy()
        # Relogin with the backup-harddrive
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.verify_alive()
        timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=timeout)
        logging.info("Checking whether the guest with backup-harddrive boot "
                     "and respond after block stream completion")
        error.context("checking responsiveness of guest")
        session.cmd(params["alive_check_cmd"])

        # Finally shutdown the virtual machine
        vm.destroy()
    finally:
        # Remove the backing file
        if os.path.isfile(backing_file):
            os.remove(backing_file)
