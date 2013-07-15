#!/usr/bin/python

import unittest, shutil, glob, os, signal, subprocess, sys, time, datetime
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
        start = datetime.datetime.now()
        fivesec = datetime.timedelta(seconds=5)
        session = aexpect.Spawn('/bin/false')
        while not session.is_alive():
            delta = datetime.datetime.now() - start
            self.assertTrue(delta < fivesec)
        self.assertEqual(session.get_status(), 1)
        session.close()


if __name__ == "__main__":
    unittest.main()
