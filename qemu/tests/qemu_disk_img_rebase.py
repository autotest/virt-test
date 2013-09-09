import re
import copy
import logging
from autotest.client import utils
from autotest.client.shared import error
from qemu.tests import qemu_disk_img
from virttest import storage


class RebaseTest(qemu_disk_img.QemuImgTest):

    def __init__(self, test, params, env, tag):
        self.tag = tag
        t_params = params.object_params(tag)
        super(RebaseTest, self).__init__(test, t_params, env, tag)

    @error.context_aware
    def rebase(self, t_params={}):
        """
        Rebase snapshot, AKA changes backing file to new image;
        """
        error.context("rebase snapshot to backingfile", logging.info)
        params = self.params.object_params(self.tag)
        params.update(t_params)
        cache_mode = params.get("cache_mode")
        super(RebaseTest, self).rebase(params, cache_mode)
        return params

    def check_backingfile(self):
        out = self.get_info()
        if not out:
            msg = "Fail to get image('%s') info" % self.image_filename
            raise error.TestFail(msg)
        backingfile = re.search(r'backing file: +(.*)', out, re.M)
        if backingfile:
            if not (self.base_image_filename in backingfile.group(0)):
                msg = "Expected backing file: %s" % self.base_image_filename
                msg += " Actual backing file: %s" % backingfile
                raise error.TestFail(msg)
        else:
            msg = ("Could not find backing file for image '%s'" %
                   self.image_filename)
            raise error.TestFail(msg)

    def clean(self):
        params = self.params
        for sn in params.get("image_chain").split()[1:]:
            _params = params.object_params(sn)
            _image = storage.get_image_filename(_params, self.data_dir)
            utils.run("rm -f %s" % _image)


def run_qemu_disk_img_rebase(test, params, env):
    """
    'qemu-img' rebase function test:

    @param test: Qemu test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    base_image = params.get("images", "image1").split()[0]
    params_bak = copy.deepcopy(params)
    params.update(
        {"image_name_%s" % base_image: params["image_name"],
         "image_format_%s" % base_image: params["image_format"]})
    image_chain = params.get("image_chain", "").split()
    for idx, tag in enumerate(image_chain):
        params["image_chain"] = " ".join(image_chain[:idx + 1])
        rebase_test = RebaseTest(test, params, env, tag)
        n_params = rebase_test.create_snapshot()
        rebase_test.start_vm(n_params)
        t_file = params["guest_file_name_%s" % tag]
        ret = rebase_test.save_file(t_file)
        if not ret:
            raise error.TestError("Fail to save tmp file")
        rebase_test.destroy_vm()

    # rebase snapshot image
    rebase_chain = params.get("rebase_list", "").split(";")
    for images in rebase_chain:
        images = map(lambda x: x.strip(), images.split(">"))
        try:
            image = images[0]
            base = images[1]
        except IndexError:
            msg = "Invalid format of'rebase_chain' params \n"
            msg += "format like: 'image > base;image> base2;image2 > base2'"
            raise error.TestError(msg)
        params["image_chain"] = " ".join([base, image])
        params["base_image_filename"] = image

        rebase_test = RebaseTest(test, params, env, image)
        t_params = rebase_test.rebase()
        rebase_test.check_backingfile()
        rebase_test.start_vm(t_params)
        check_files = params.get("check_files", "").split()
        for _file in check_files:
            ret = rebase_test.check_file(_file)
            if not ret:
                raise error.TestError("Check md5sum fail (file:%s)" % _file)
        rebase_test.destroy_vm()
        rebase_test.check_image()

    # clean up snapshot files
    rebase_test = RebaseTest(test, params_bak, env, base_image)
    rebase_test.clean()
