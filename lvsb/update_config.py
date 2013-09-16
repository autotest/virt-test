#!/usr/bin/python
"""
Populate/update config files for virt-test

:copyright: Red Hat 2013
"""
import os
import sys
import common
from autotest.client.shared import logging_manager
from virttest import data_dir, bootstrap, utils_misc

test_name = "lvsb"
test_dir = os.path.dirname(sys.modules[__name__].__file__)
test_dir = os.path.abspath(test_dir)
t_type = os.path.basename(test_dir)
shared_dir = os.path.join(data_dir.get_root_dir(), "shared")

if __name__ == "__main__":
    import optparse
    option_parser = optparse.OptionParser()
    option_parser.add_option("-v", "--verbose",
                             action="store_true", dest="verbose",
                             help="Exhibit debug messages")
    options, args = option_parser.parse_args()
    if options.verbose:
        logging_manager.configure_logging(utils_misc.VirtLoggingConfig(),
                                          verbose=options.verbose)

    bootstrap.create_subtests_cfg(t_type)
