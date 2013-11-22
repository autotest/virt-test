import logging
from autotest.client.shared import error
from virttest import env_process
from virttest import qemu_storage
from virttest import data_dir


@error.context_aware
def run_gluster_boot_snap_boot(test, params, env):
    """
    Run an gluster test.
    steps:
    1) create gluster brick if there is no one with good name
    2) create volume on brick
    3) create VM image on disk with specific format
    4) install vm on VM image
    5) boot VM
    6) start fio test on booted VM

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    image_name = params.get("image_name")
    timeout = int(params.get("login_timeout", 360))
    # Workaroud wrong config file order.
    params['image_name_backing_file_snapshot'] = params.get("image_name")
    params['image_format_backing_file_snapshot'] = params.get("image_format")
    params['image_name_snapshot'] = params.get("image_name") + "-snap"

    error.context("boot guest over glusterfs", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=timeout)
    error.context("shutdown VM", logging.info)
    vm.destroy()
    error.context("create snapshot of vm disk", logging.info)

    snapshot_params = params.object_params("snapshot")

    base_dir = params.get("images_base_dir", data_dir.get_data_dir())
    image = qemu_storage.QemuImg(snapshot_params, base_dir, image_name)
    image.create(snapshot_params)

    env_process.process(test, snapshot_params, env,
                        env_process.preprocess_image,
                        env_process.preprocess_vm)
