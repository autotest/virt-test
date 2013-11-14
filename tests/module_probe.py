import logging
from autotest.client.shared import error
from autotest.client import utils
from virttest import base_installer, utils_misc


def run(test, params, env):
    """
    load/unload kernel modules several times.

    This tests the kernel pre-installed kernel modules
    """
    installer_object = base_installer.NoopInstaller('noop',
                                                    'module_probe',
                                                    test, params)
    logging.debug('installer object: %r', installer_object)

    # unload the modules before starting:
    installer_object.unload_modules()

    load_count = int(params.get("load_count", 100))
    try:
        for _ in range(load_count):
            try:
                installer_object.load_modules()
            except base_installer.NoModuleError, e:
                logging.error(e)
                break
            except Exception, e:
                raise error.TestFail("Failed to load modules [%r]: %s" %
                                     (installer_object.module_list, e))
            installer_object.unload_modules()
    finally:
        try:
            installer_object.load_modules()
        except base_installer.NoModuleError:
            pass
