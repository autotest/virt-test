#!/usr/bin/python
import unittest

try:
    import autotest.common as common
except ImportError:
    import common

import libvirt_storage, data_dir, virsh

VIRSH_EXEC = virsh.VIRSH_EXEC
if VIRSH_EXEC == "/bin/true":
    VIRSH_EXEC = "/bin/false"


class PoolTestBase(unittest.TestCase):

    def setUp(self):
        # To avoid not installed libvirt packages
        virsh_instance = virsh.Virsh(virsh_exec=virsh.VIRSH_EXEC,
                                     uri='qemu:///system', debug=True,
                                     ignore_status=True)
        self.sp = libvirt_storage.StoragePool(virsh_instance)


class ExistPoolTest(PoolTestBase):

    def test_exist_pool(self):
        pools = self.sp.list_pools()
        self.assertIsInstance(pools, dict)
        for pool_name in pools:
            # Test pool_state
            self.assertIn(self.sp.pool_state(pool_name), ['active', 'inactive'])
            # Test pool_info
            self.assertNotEqual(self.sp.pool_info(pool_name), {})


class NewPoolTest(PoolTestBase):

    def test_dir_pool(self):
        # Used for auto cleanup
        tmp_dir = data_dir.get_tmp_dir()
        self.pool_name = "AUTOTEST_POOLTEST"
        self.assertTrue(self.sp.define_dir_pool(self.pool_name, tmp_dir))
        self.assertTrue(self.sp.build_pool(self.pool_name))
        self.assertTrue(self.sp.start_pool(self.pool_name))
        self.assertTrue(self.sp.set_pool_autostart(self.pool_name))
        self.assertTrue(self.sp.delete_pool(self.pool_name))


    def tearDown(self):
        # Confirm created pool has been cleaned up
        self.sp.delete_pool(self.pool_name)


class NotExpectedPoolTest(PoolTestBase):

    def test_not_exist_pool(self):
        self.assertFalse(self.sp.pool_exists("NOTEXISTPOOL"))
        self.assertIsNone(self.sp.pool_state("NOTEXISTPOOL"))
        self.assertEqual(self.sp.pool_info("NOTEXISTPOOL"), {})


if __name__ == "__main__":
    unittest.main()
