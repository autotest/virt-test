#!/usr/bin/python
"""
Program to help setup kvm test environment

@copyright: Red Hat 2010
"""
import os, sys, logging
try:
    import autotest.common as common
except ImportError:
    import common
from virttest import utils_misc, data_dir

test_name = "kvm"
test_dir = os.path.dirname(sys.modules[__name__].__file__)
test_dir = os.path.abspath(test_dir)
base_dir = data_dir.get_data_dir()
default_userspace_paths = ["/usr/bin/qemu-kvm", "/usr/bin/qemu-img"]
check_modules = ["kvm", "kvm-%s" % utils_misc.get_cpu_vendor(verbose=False)]
online_docs_url = "https://github.com/autotest/autotest/wiki/KVMAutotest-GetStartedClient"

if __name__ == "__main__":
    try:
        utils_misc.virt_test_assistant(test_name, test_dir, base_dir,
                                       default_userspace_paths, check_modules,
                                       online_docs_url)
    except Exception, details:
        logging.error("Setup error: %s", details)
