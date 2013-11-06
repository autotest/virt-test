#!/usr/bin/python

import unittest, shutil, glob, os, signal
import subprocess, sys, time, datetime, logging
import common
import utils_misc
import aexpect

class AexpectTestBase(unittest.TestCase):
    """
    Common setup/teardown for all tests
    """

    def setUp(self):
        # Remove at start to allow inspection of prior run
        shutil.rmtree(aexpect.BASE_DIR, ignore_errors=True)
        os.makedirs(aexpect.BASE_DIR)


    def tearDown(self):
     (shell_pid_filename,
     status_filename,
     output_filename,
     inpipe_filename,
     # Spawn.__init__ makes 8-digit ID numbers
     lock_server_running_filename,
     log_filename) = aexpect._get_filenames(aexpect.BASE_DIR, '????????')
     # make sure all server-spawned child processes are dead
     for shellpidfile in glob.glob(shell_pid_filename):
        try:
            pid = int(open(shellpidfile, 'rb').readline())
            utils_misc.kill_process_tree(pid, signal.SIGKILL)
        except (TypeError, IOError):
            pass


class TestServer(AexpectTestBase):

    def test_binfalse(self):
        logging.disable(logging.INFO)
        # Always use known id value
        a_id = '12345678'
        (shell_pid_filename,
         status_filename,
         output_filename,
         inpipe_filename,
         lock_server_running_filename,
         log_filename) = aexpect._get_filenames(aexpect.BASE_DIR, a_id)
        sub = subprocess.Popen("%s %s" % (sys.executable, aexpect.__file__),
                                   shell=True,
                                   stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        self.assertFalse(aexpect._locked(lock_server_running_filename))
        sub.stdin.write("%s\n" % a_id)
        self.assertFalse(aexpect._locked(lock_server_running_filename))
        sub.stdin.write("%s\n" % False)
        self.assertFalse(aexpect._locked(lock_server_running_filename))
        sub.stdin.write("%s\n" % ",".join([]))
        self.assertFalse(aexpect._locked(lock_server_running_filename))
        sub.stdin.write("%s\n" % "/bin/false")
        sub.stdin.close()
        start = datetime.datetime.now()
        fivesec = datetime.timedelta(seconds=5)
        while not aexpect._locked(lock_server_running_filename):
            delta = datetime.datetime.now() - start
            self.assertTrue(delta < fivesec)
        aexpect._wait(lock_server_running_filename)
        pid = open(shell_pid_filename, 'rb').readline()
        self.assertRaises(IOError,
                          open, os.path.join('/proc', pid, 'cmdline'), 'rb')
        status = int(open(status_filename, 'rb').readline())
        self.assertEqual(status, 1)
        sub.wait()
        self.assertEqual(sub.returncode, 0)


class TestSpawn(AexpectTestBase):

    def test_binfalse(self):
        tenseconds = datetime.timedelta(seconds=10)
        # Check server handles very short exit times
        start = datetime.datetime.now()
        session = aexpect.Spawn('/bin/false')
        # Wait up to 10 seconds for status to be available
        while session.get_status() is None:
            time.sleep(0.01) # Don't busy wait
            # Double default 5-second time to make sure enough time to Fail
            self.assertTrue(datetime.datetime.now() - start < tenseconds)
        self.assertEqual(session.get_status(), 1)
        self.assertFalse(session.is_alive())
        session.close() # Wait for exit

if __name__ == "__main__":
    unittest.main()
