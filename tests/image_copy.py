import os, logging
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_misc, data_dir, utils_test, asset


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

    src = params.get('images_good')
    asset_name = '%s' % (os.path.split(params['image_name'])[1])
    image = '%s.%s' % (params['image_name'], params['image_format'])
    dst_path = '%s/%s' % (data_dir.get_data_dir(), image)
    pwd = os.path.join(test.bindir, "images")
    if params.get("rename_error_image", "no") == "yes":
        error_image = os.path.basename(params['image_name']) + "-error"
        error_image += '.' + params['image_format']
        error_dst_path = os.path.join(pwd, error_image)
        mv_cmd = "/bin/mv %s %s" % (dst_path, error_dst_path)
        utils.system(mv_cmd, timeout=360, ignore_status=True)

    if src:
        mount_dest_dir = params.get('dst_dir', '/mnt/images')
        if not os.path.exists(mount_dest_dir):
            try:
                os.makedirs(mount_dest_dir)
            except OSError, err:
                logging.warning('mkdir %s error:\n%s', mount_dest_dir, err)

        if not os.path.exists(mount_dest_dir):
            raise error.TestError('Failed to create NFS share dir %s' %
                                  mount_dest_dir)

        error.context("Mount the NFS share directory")
        if not utils_misc.mount(src, mount_dest_dir, 'nfs', 'ro'):
            raise error.TestError('Could not mount NFS share %s to %s' %
                                  (src, mount_dest_dir))
        src_path = '%s/%s.%s' % (mount_dest_dir, asset_name, params['image_format'])
        asset_info = asset.get_file_asset(asset_name, src_path, dst_path)
        if asset_info is None:
            raise error.TestError('Could not find %s' % image)
    else:
        asset_info = asset.get_asset_info(asset_name)

    try:
        asset.download_file(asset_info, interactive=False, force=True)

    finally:
        if params.get("sub_type"):
            params['image_name'] += "-error"
            params['boot_once'] = "c"
            vm.create(params=params)
            utils_test.run_virt_sub_test(test, params, env,
                                         params.get("sub_type"))
