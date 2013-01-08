#!/usr/bin/python
"""
Populate/update config files for virt-test

@copyright: Red Hat 2013
"""
import os, sys
import common
from virttest import data_dir, bootstrap

test_dir = os.path.dirname(sys.modules[__name__].__file__)
test_dir = os.path.abspath(test_dir)
t_type = os.path.basename(test_dir)
shared_dir = os.path.join(data_dir.get_root_dir(), "shared")

if __name__ == "__main__":
    bootstrap.create_config_files(test_dir, shared_dir, interactive=False,
                                  force_update=True)
    bootstrap.create_subtests_cfg(t_type)
    bootstrap.create_guest_os_cfg(t_type)
