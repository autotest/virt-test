import os, logging
from autotest_lib.client.common_lib import error
from autotest_lib.client.bin import utils
from autotest_lib.client.virt import virt_utils
from autotest_lib.client.virt import virt_test_utils


@error.context_aware
def run_image_copy(test, params, env):
    """
    Copy guest images from nfs server.
    1) Mount the NFS share directory
    2) Check the existence of source image
    3) If it exists, copy the image from NFS

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """


    vm = env.get_vm(params["main_vm"])
    if vm is not None:
        vm.destroy()
    mount_dest_dir = params.get('dst_dir', '/mnt/images')
    if not os.path.exists(mount_dest_dir):
        try:
            os.makedirs(mount_dest_dir)
        except OSError, err:
            logging.warning('mkdir %s error:\n%s', mount_dest_dir, err)

    if not os.path.exists(mount_dest_dir):
        raise error.TestError('Failed to create NFS share dir %s' %
                              mount_dest_dir)

    src = params.get('images_good')
    image_name = params.get('image_name')
    image_format = params.get('image_format')

    image = '%s.%s' % (os.path.basename(image_name), image_format)
    src_path = os.path.join(mount_dest_dir, image)
    dst_path = '.'.join([image_name, image_format])
    pwd = os.path.join(test.bindir, "images")
    dst_path = os.path.join(test.bindir, dst_path)
    if params.get("rename_error_image", "no") == "yes":
        error_image = os.path.basename(image_name) + "-error"
        error_image += '.' + params['image_format']
        error_dst_path = os.path.join(pwd, error_image)
        mv_cmd = "/bin/mv %s %s" % (dst_path, error_dst_path)
        utils.system(mv_cmd, timeout=360, ignore_status=True)
    cmd = 'cp %s %s' % (src_path, dst_path)

    try:
        error.context("Mount the NFS share directory")
        if not virt_utils.mount(src, mount_dest_dir, 'nfs', 'ro'):
            raise error.TestError('Could not mount NFS share %s to %s' %
                                  (src, mount_dest_dir))

        error.context("Check the existence of source image")
        if not os.path.exists(src_path):
            raise error.TestError('Could not find %s in NFS share' % src_path)

        error.context("Copy image '%s' from NFS" % image, logging.debug)
        utils.system(cmd)
    finally:
        if params.get("sub_type"):
            params['image_name'] += "-error"
            params['boot_once'] = "c"
            vm.create(params=params)
            virt_test_utils.run_virt_sub_test(test, params, env,
                                         params.get("sub_type"))

