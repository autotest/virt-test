import logging
from autotest.client import utils
from autotest.client.shared import error
from virttest import storage
from qemu.tests import qemu_disk_img


class ConvertTest(qemu_disk_img.QemuImgTest):

    def __init__(self, test, params, env):
        self.tag = params["image_convert"]
        t_params = params.object_params(self.tag)
        super(ConvertTest, self).__init__(test, t_params, env, self.tag)

    @error.context_aware
    def convert(self, t_params={}):
        """
        create image file from one format to another format
        """
        error.context("convert image file", logging.info)
        params = self.params.object_params(self.tag)
        params.update(t_params)
        cache_mode = params.get("cache_mode")
        super(ConvertTest, self).convert(params, self.data_dir, cache_mode)
        params["image_name"] = params["convert_name"]
        params["image_format"] = params["convert_format"]
        converted = storage.get_image_filename(params, self.data_dir)
        utils.run("sync")
        self.trash.append(converted)
        return params


def run_qemu_disk_img_convert(test, params, env):
    """
    'qemu-img' convert functions test:

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    base_image = params.get("images", "image1").split()[0]
    params.update(
        {"image_name_%s" % base_image: params["image_name"],
         "image_format_%s" % base_image: params["image_format"]})
    t_file = params["guest_file_name"]
    convert_test = ConvertTest(test, params, env)
    n_params = convert_test.create_snapshot()
    convert_test.start_vm(n_params)

    # save file md5sum before conversion
    ret = convert_test.save_file(t_file)
    if not ret:
        raise error.TestError("Fail to save tmp file")
    convert_test.destroy_vm()
    n_params = convert_test.convert()
    convert_test.start_vm(n_params)

    # check md5sum after conversion
    ret = convert_test.check_file(t_file)
    if not ret:
        raise error.TestError("image content changed after convert")
    convert_test.clean()
