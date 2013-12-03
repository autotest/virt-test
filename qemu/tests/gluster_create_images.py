import logging
from autotest.client.shared import error
from virttest import env_process


@error.context_aware
def run_gluster_create_images(test, params, env):
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
    error.context("Create gluster fs image")
    gluster_params = params.object_params("gluster")
    image_name = gluster_params.get("image_name")

    env_process.preprocess_image(test, gluster_params, image_name)
