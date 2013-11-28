#!/usr/bin/python
"""
Program to help setup libvirt test environment

:copyright: Red Hat 2011
"""
import os
import sys
import logging
import common
from virttest import data_dir, bootstrap

test_name = "libvirt"
test_dir = os.path.dirname(sys.modules[__name__].__file__)
test_dir = os.path.abspath(test_dir)
base_dir = data_dir.get_data_dir()
default_userspace_paths = ["/usr/bin/virt-install"]
check_modules = None
online_docs_url = None

if __name__ == "__main__":
    import optparse
    option_parser = optparse.OptionParser()
    option_parser.add_option("-v", "--verbose",
                             action="store_true", dest="verbose",
                             help="Exhibit debug messages")
    option_parser.add_option("-r", "--restore-image",
                             action="store_true", dest="restore",
                             help="Restore image from pristine image")
    option_parser.add_option("-d", "--data-dir",
                             action="store", dest="datadir",
                             help="Path to a data dir (that "
                             "locates ISOS and images)")
    option_parser.add_option("-s", "--setup-selinux",
                             action="store_true", dest="selinux",
                             help="Setup SELinux contexts for "
                             "shared/data and set them to default")
    option_parser.add_option("-n", "--non-interactive",
                             action="store_true", dest="no_interactive",
                             help="Disable interactive prompt")
    options, args = option_parser.parse_args()

    if options.datadir:
        data_dir.set_backing_data_dir(options.datadir)

    try:
        bootstrap.bootstrap(test_name, test_dir, base_dir,
                            default_userspace_paths, check_modules,
                            online_docs_url,
                            interactive=not options.no_interactive,
                            restore_image=options.restore,
                            selinux=options.selinux,
                            verbose=options.verbose)
    except Exception, details:
        logging.error("Setup error: %s", details)
