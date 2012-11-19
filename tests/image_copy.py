import os, logging
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_misc, data_dir


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
    image = '%s.%s' % (os.path.split(params['image_name'])[1],
                       params['image_format'])
    src_path = os.path.join(mount_dest_dir, image)
    dst_path = '%s/%s.%s' % (data_dir.get_data_dir(), params['image_name'], params['image_format'])

    if not utils_misc.mount(src, mount_dest_dir, 'nfs', 'ro'):
        raise error.TestError('Could not mount NFS share %s to %s' %
                              (src, mount_dest_dir))

    # Check the existence of source image
    if os.path.exists("%s.xz" % src_path):
        logging.debug('Copying image %s (from xz) ...', image)
        cmd = "xz -cd %s.xz > %s" % (src_path, dst_path)
    elif os.path.exists("%s.gz" % src_path):
        logging.debug('Copying image %s (from gzip) ...', image)
        cmd = "gzip -cd %s.gz > %s" % (src_path, dst_path)
    elif os.path.exists(src_path):
        logging.debug('Copying image %s (uncompressed) ...', image)
        cmd = 'cp %s %s' % (src_path, dst_path)
    else:
        raise error.TestError('Could not find %s in NFS share' % src_path)

    utils.system(cmd)
