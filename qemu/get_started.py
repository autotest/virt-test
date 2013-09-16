#!/usr/bin/python
"""
Program to help setup kvm test environment

:copyright: Red Hat 2010
"""
import os
import sys
import logging
import common
from virttest import utils_misc, data_dir, bootstrap, arch

test_name = "qemu"
test_dir = os.path.dirname(sys.modules[__name__].__file__)
test_dir = os.path.abspath(test_dir)
base_dir = data_dir.get_data_dir()
default_userspace_paths = ["/usr/bin/qemu-kvm", "/usr/bin/qemu-img"]

check_modules = arch.get_kvm_module_list()
online_docs_url = "https://github.com/autotest/virt-test/wiki/GetStarted"
interactive = True

if __name__ == "__main__":
    import optparse
    option_parser = optparse.OptionParser()
    option_parser.add_option("-v", "--verbose",
                             action="store_true", dest="verbose",
                             help="Exhibit debug messages")
    option_parser.add_option("-r", "--restore-image",
                             action="store_true", dest="restore",
                             help="Restore image from pristine image")
    option_parser.add_option("--data-dir", action="store", dest="datadir",
                             help="Path to a data dir (that locates ISOS and images)")
    options, args = option_parser.parse_args()

    if options.datadir:
        data_dir.set_backing_data_dir(options.datadir)

    try:
        bootstrap.bootstrap(test_name, test_dir, base_dir,
                            default_userspace_paths, check_modules,
                            online_docs_url, interactive=interactive,
                            restore_image=options.restore,
                            verbose=options.verbose)
    except Exception, details:
        logging.error("Setup error: %s", details)
