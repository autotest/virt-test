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

    # TODO: These tests should not actually call out to system executables
    #       or rely on system state in any way.  They should mock utils.run
    #       and SELinux status plus returns for utils_selinux module testing.

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
        result = utils_selinux.get_context_from_str(context=output)
        self.assertEqual(result, "system_u:object_r:svirt_t:s0-s1:c250,c280")
        result = utils_selinux.get_context_of_file(filename=__file__)
        utils_selinux.set_context_of_file(filename=__file__, context=result)
        utils_selinux.get_context_of_process(pid=1)

    def test_get_type_from_context(self):
        """
        Test extracting only the type from a context
        """
        context = "system_u:object_r:virt_image_t"
        context_type = utils_selinux.get_type_from_context(context)
        self.assertEqual("virt_image_t",  context_type)
        context = "system_u:object_r:virt_image_t:s0-s1:c250,c280"
        context_type = utils_selinux.get_type_from_context(context)
        self.assertEqual("virt_image_t",  context_type)

class TestDefCon(unittest.TestCase):

    def setUp(self):
        """Mock the utils.run method for unittesting"""

        def utils_run(command, *args, **dargs):
            # _no_semanage checks for exit code and output
            if command.count('semanage'):
                msg = '-bash: %s: command not found' % command
                return utils_selinux.utils.CmdResult(command,
                                                     stdout=msg,
                                                     exit_status=127)
            # verify/set defcon unittest always use same test context
            elif command.count('restorecon'):
                pathname = command.split()[-1] # Always last argument
                if pathname.count('fail'):
                    msg = ('restorecon reset %s context '
                           'foo_u:bar_r:baz_t:s0->baz_u:bar_r:foo_t:s0'
                           % pathname)
                else: # restorecon check passes
                    msg = '' # no output when pass
                return utils_selinux.utils.CmdResult(command, stdout=msg)

        # Need to restore original function after each test
        self.original_utils_run = utils_selinux.utils.run
        utils_selinux.utils.run = utils_run

    def tearDown(self):
        utils_selinux.utils.run = self.original_utils_run

    def test_get_type_from_default(self):
        """
        Test extracting context type by path
        """
        default_contexts = [
            {'type':'all files',
             'context':'system_u:object_r:virt_image_t:s0',
             'fcontext':r'/var/lib/virt_test/images(/.*)?'},
            {'type':'all files',
             'context':'system_u:object_r:virt_content_t:s0',
             'fcontext':r'/var/lib/virt_test/isos(/.*)?'},
            {'type':'all files',
             'context':'system_u:object_r:virt_var_lib_t:s0',
             'fcontext':
                    r'/usr/(local/)?autotest/client/tests/virt/shared/data'}]
        test_paths = ['/var/lib/virt_test/images/foobar/baz',
                      '/var/lib/virt_test/isos/Linux',
                      '/var/lib/virt_test/isos/Windows'
                      '/usr/local/autotest/client/tests/virt/share/data']
        result_types = ['virt_var_lib_t', 'virt_content_t', 'virt_image_t']
        for path in test_paths:
            test_type = utils_selinux.find_defcon(default_contexts,
                                                  path)
            self.assertTrue(test_type in result_types, '%s for %s not in %s'
                            % (test_type, path, result_types))

    def test_no_semanage(self):
        self.assertRaises(utils_selinux.SemanageError,
                          utils_selinux.get_defcon)
        self.assertRaises(utils_selinux.SemanageError,
                          utils_selinux.set_defcon,
                          'foo_u:bar_r:baz_t', 'somefile')
        self.assertRaises(utils_selinux.SemanageError,
                          utils_selinux.del_defcon,
                          'foo_u:bar_r:baz_t', 'somefile')

    def test_verify_defcon(self):
        # fail in path causes mock to return negative result
        self.assertFalse(utils_selinux.verify_defcon('/foo/bar/fail'))
        # No fail in path causes mock to return positive result
        self.assertTrue(utils_selinux.verify_defcon('/foo/bar'))

    def test_diff_defcon(self):
        self.assertEqual([], utils_selinux.diff_defcon('/foo/bar'))
        expected = ('"/foo/bar/fail"',
                    'foo_u:bar_r:baz_t:s0',
                    'baz_u:bar_r:foo_t:s0')
        self.assertEqual([expected], utils_selinux.diff_defcon('/foo/bar/fail'))

    def test_apply_defcon(self):
        self.assertEqual([], utils_selinux.apply_defcon('/foo/bar'))
        expected = ('"/foo/bar/fail"',
                    'foo_u:bar_r:baz_t:s0',
                    'baz_u:bar_r:foo_t:s0')
        self.assertEqual([expected], utils_selinux.apply_defcon('/foo/bar/fail'))

if __name__ == '__main__':
    try:
        os_dep.command("getsebool")
    except ValueError:
        # There is no selinux on host,
        # so this unittest will be skipped.
        pass
    else:
        unittest.main()
