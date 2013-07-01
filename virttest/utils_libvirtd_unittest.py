#!/usr/bin/python

import unittest
import common
from virttest import utils_libvirtd

class UtilsLibvirtdTest(unittest.TestCase):
    def test_service_libvirtd_control(self):
        service_libvirtd_control = utils_libvirtd.service_libvirtd_control
        self.assertRaises(utils_libvirtd.LibvirtdActionUnknownError,
                        service_libvirtd_control, 'UnknowAction')
        self.assertTrue(service_libvirtd_control('status') in (True, False))

    def test_libvirtd_error(self):
        method_list = [utils_libvirtd.libvirtd_restart,
                       utils_libvirtd.libvirtd_stop,
                       utils_libvirtd.libvirtd_start]

        for method in method_list:
            self.assertRaises(utils_libvirtd.LibvirtdActionError,
                                            method, service_name='')

if __name__ == "__main__":
    unittest.main()
