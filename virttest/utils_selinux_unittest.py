#!/usr/bin/python
"""
Unittests for utils_libvirtd module.
"""
import unittest
import common
from virttest import utils_selinux
from autotest.client import os_dep


class TestSelinux(unittest.TestCase):

    """
    Class for unittests of utils_selinux.
    """

    def test_sestatus(self):
        """
        Test the method related with sestatus.
        """
        status = utils_selinux.get_status()
        # b/c there is no assertIn method in re.py in python2.6.
        # use assertTrue.
        self.assertTrue(status in ['enforcing', 'permissive', 'disabled'])

        if utils_selinux.is_disabled():
            self.assertRaises(utils_selinux.SelinuxError,
                              utils_selinux.set_status, "enforcing")
        else:
            self.assertRaises(utils_selinux.SelinuxError,
                              utils_selinux.set_status, "disabled")

    def test_is_or_not_disabled(self):
        """
        Test the method about selinux disabled.
        """
        is_disabled = utils_selinux.is_disabled()
        self.assertTrue(is_disabled in [True, False])
        is_not_disabled = utils_selinux.is_not_disabled()
        self.assertTrue(is_not_disabled in [True, False])
        self.assertEqual(not is_disabled, is_not_disabled)

    def test_context(self):
        """
        Test the context related method.
        """
        output = "output system_u:object_r:svirt_t:s0-s1:c250,c280 test"
        result = utils_selinux.get_context_from_str(string=output)
        self.assertEqual(result, "system_u:object_r:svirt_t:s0-s1:c250,c280")
        result = utils_selinux.get_context_of_file(filename=__file__)
        utils_selinux.set_context_of_file(filename=__file__, context=result)
        utils_selinux.get_context_of_process(pid=1)


if __name__ == '__main__':
    try:
        os_dep.command("getsebool")
    except ValueError:
        # There is no selinux on host,
        # so this unittest will be skipped.
        pass
    else:
        unittest.main()
