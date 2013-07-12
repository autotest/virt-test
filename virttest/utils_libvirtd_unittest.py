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
        action_list = ["restart", "start", "stop", "status"]

        for action in action_list:
            self.assertRaises(utils_libvirtd.LibvirtdActionError,
                              utils_libvirtd.service_libvirtd_control,
                              action=action, libvirtd="")

class RemoteControlTest(unittest.TestCase):
    def test_status(self):
        service_libvirtd_control = utils_libvirtd.service_libvirtd_control
        status_remote = service_libvirtd_control("status", client="unittest")
        status_local = utils_libvirtd.libvirtd_status()
        self.assertEqual(status_remote, status_local)

    def test_restart_stop_start(self):
        service_libvirtd_control = utils_libvirtd.service_libvirtd_control

        service_libvirtd_control("restart", client="unittest")
        self.assertTrue(utils_libvirtd.libvirtd_status())

        service_libvirtd_control("stop", client="unittest")
        self.assertFalse(utils_libvirtd.libvirtd_status())
        service_libvirtd_control("start", client="unittest")
        self.assertTrue(utils_libvirtd.libvirtd_status())


if __name__ == "__main__":
    unittest.main()
