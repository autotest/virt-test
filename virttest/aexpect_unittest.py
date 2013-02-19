#!/usr/bin/python

import os, shutil, unittest, time
import common

# Set true to see server output
DEBUG = False

class AexpectTestBase(unittest.TestCase):

    def setUp(self):
        import logging
        import aexpect
        self.logging = logging
        self.aexpect = aexpect
        # Don't interfear with other uses
        self.aexpect.BASE_DIR += '_unittest'
        # Test with clean-slate
        try:
            shutil.rmtree(self.aexpect.BASE_DIR)
        except OSError:
            pass # assume dir doesn't exist
        self.logging.basicConfig(level=logging.DEBUG)
        if not DEBUG:
            self.logging.disable(logging.INFO)

    def tearDown(self):
        # aexpect must cleanup after itself
        leftover_files = []
        try:
            os.stat(self.aexpect.BASE_DIR)
            base_dir_exists = True
            leftover_files = os.listdir(self.aexpect.BASE_DIR)
        except OSError:
            base_dir_exists = False
        msg = "Leftovers in %s: %s" % (self.aexpect.BASE_DIR, leftover_files)
        # Fail test if aexpect cleanup failed
        self.assertEqual(leftover_files, [], msg)
        # Fail test if base dir exists
        self.assertEqual(base_dir_exists, False)

class TestAexpectSpawn(AexpectTestBase):


    def test_touch_close(self):
        spawn = self.aexpect.Spawn("touch %s" % os.path.join(
                                   self.aexpect.BASE_DIR, 'unittest_file'))
        # Give some small time to write file
        time.sleep(1)
        filename = os.path.join(self.aexpect.BASE_DIR, 'unittest_file')
        self.assertTrue(os.stat(filename))
        os.unlink(filename)
        self.assertRaises(OSError, os.stat, filename)
        spawn.close() # should cleanup all files


    def test_close_touch(self):
        spawn = self.aexpect.Spawn("touch %s" % os.path.join(
                                   self.aexpect.BASE_DIR, 'unittest_file'))
        # Give some small time to write file
        time.sleep(1)
        spawn.close() # should cleanup all files except unittest_file
        filename = os.path.join(self.aexpect.BASE_DIR, 'unittest_file')
        self.assertTrue(os.stat(filename))
        os.unlink(filename)
        self.assertRaises(OSError, os.stat, filename)
        # unittest_file prevented close() from rmdir - this is normal
        os.rmdir(self.aexpect.BASE_DIR)


    def test_short_sleep(self):
        spawn = self.aexpect.Spawn("sleep 0.1s")
        spawn.close()
        # tearDown will handle failure


    def test_long_sleep(self):
        sleeptime = self.aexpect.Spawn.server_start_timeout + 1
        spawn = self.aexpect.Spawn("sleep %s" % str(sleeptime))
        spawn.close()
        # tearDown will handle failure

    def test_fast_fail(self):
        spawn = self.aexpect.Spawn("/bin/false")
        self.assertFalse(spawn.is_alive())
        self.assertEqual(spawn.get_status(), 1)
        spawn.close()

if __name__ == "__main__":
    unittest.main()
