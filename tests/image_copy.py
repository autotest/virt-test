import os, logging
from autotest_lib.client.common_lib import error
from autotest_lib.client.bin import utils
from autotest_lib.client.virt import virt_utils


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
    dst_path = os.path.join(test.bindir, dst_path)
    cmd = 'cp %s %s' % (src_path, dst_path)

    error.context("Mount the NFS share directory")
    if not virt_utils.mount(src, mount_dest_dir, 'nfs', 'ro'):
        raise error.TestError('Could not mount NFS share %s to %s' %
                              (src, mount_dest_dir))

    error.context("Check the existence of source image")
    if not os.path.exists(src_path):
        raise error.TestError('Could not find %s in NFS share' % src_path)

    error.context("Copy image '%s' from NFS" % image, logging.debug)
    utils.system(cmd)
