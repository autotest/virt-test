#!/usr/bin/python
import unittest, logging

try:
    import autotest.common as common
except ImportError:
    import common

import utils_libguestfs as lgf


class LibguestfsTest(unittest.TestCase):
    def test_lgf_cmd_check(self):
        cmds = ['virt-ls', 'virt-cat']
        for cmd in cmds:
            self.assertTrue(lgf.lgf_cmd_check(cmd))

    def test_lgf_cmd_check_raises(self):
        cmds = ['virt-test-fail', '']
        for cmd in cmds:
            self.assertRaises(lgf.LibguestfsCmdError,
                              lgf.lgf_cmd_check, cmd)

    def test_lgf_cmd(self):
        cmd = "libguestfs-test-tool"
        self.assertEqual(lgf.lgf_command(cmd).exit_status, 0)


class SlotsCheckTest(unittest.TestCase):
    def test_LibguestfsBase_default_slots(self):
        """Default slots' value check"""
        lfb = lgf.LibguestfsBase()
        self.assertEqual(lfb.ignore_status, True)
        self.assertEqual(lfb.debug, False)
        self.assertEqual(lfb.timeout, 60)
        self.assertEqual(lfb.uri, None)
        self.assertEqual(lfb.lgf_exec, "/bin/true")

    def test_LibguestfsBase_update_slots(self):
        """Update slots"""
        lfb = lgf.LibguestfsBase()
        lfb.set_ignore_status(False)
        self.assertEqual(lfb.ignore_status, False)
        lfb.set_debug(True)
        self.assertEqual(lfb.debug, True)
        lfb.set_timeout(240)
        self.assertEqual(lfb.timeout, 240)

    def test_Guestfish_slots(self):
        """Test Guestfish slots"""
        gf = lgf.Guestfish()
        self.assertEqual(gf.lgf_exec, "guestfish")
        gf = lgf.Guestfish(disk_img="test.img", ro_mode=True, inspector=True)
        self.assertEqual(gf.lgf_exec, "guestfish -a 'test.img' --ro -i")
        gf = lgf.Guestfish(libvirt_domain="test", inspector=True,
                           uri="qemu+ssh://root@EXAMPLE/system")
        gf_cmd = "guestfish -c 'qemu+ssh://root@EXAMPLE/system' -d 'test' -i"
        self.assertEqual(gf.lgf_exec, gf_cmd)


if __name__ == "__main__":
    unittest.main()
