from virttest import utils_test


def run_file_transfer(test, params, env):
    utils_test.run_image_copy(test, params, env)
