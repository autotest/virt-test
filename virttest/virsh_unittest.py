#!/usr/bin/python

import unittest
import logging
import common
from autotest.client import utils


class ModuleLoad(unittest.TestCase):
    import virsh


class ConstantsTest(ModuleLoad):

    def test_ModuleLoad(self):
        self.assertTrue(hasattr(self.virsh, 'NOCLOSE'))
        self.assertTrue(hasattr(self.virsh, 'SCREENSHOT_ERROR_COUNT'))
        self.assertTrue(hasattr(self.virsh, 'VIRSH_COMMAND_CACHE'))
        self.assertTrue(hasattr(self.virsh, 'VIRSH_EXEC'))


class TestVirshClosure(ModuleLoad):

    @staticmethod
    def somefunc(*args, **dargs):
        return (args, dargs)

    class SomeClass(dict):

        def somemethod(self):
            return "foobar"

    def test_init(self):
        # save some typing
        VC = self.virsh.VirshClosure
        # self is guaranteed to be not dict-like
        self.assertRaises(ValueError, VC, self.somefunc, self)
        self.assertRaises(ValueError, VC, lambda: None, self)

    def test_args(self):
        # save some typing
        VC = self.virsh.VirshClosure
        tcinst = self.SomeClass()
        vcinst = VC(self.somefunc, tcinst)
        args, dargs = vcinst('foo')
        self.assertEqual(len(args), 1)
        self.assertEqual(args[0], 'foo')
        self.assertEqual(len(dargs), 0)

    def test_dargs(self):
        # save some typing
        VC = self.virsh.VirshClosure
        tcinst = self.SomeClass(foo='bar')
        vcinst = VC(self.somefunc, tcinst)
        args, dargs = vcinst()
        self.assertEqual(len(args), 0)
        self.assertEqual(len(dargs), 1)
        self.assertEqual(dargs.keys(), ['foo'])
        self.assertEqual(dargs.values(), ['bar'])

    def test_args_and_dargs(self):
        # save some typing
        VC = self.virsh.VirshClosure
        tcinst = self.SomeClass(foo='bar')
        vcinst = VC(self.somefunc, tcinst)
        args, dargs = vcinst('foo')
        self.assertEqual(len(args), 1)
        self.assertEqual(args[0], 'foo')
        self.assertEqual(len(dargs), 1)
        self.assertEqual(dargs.keys(), ['foo'])
        self.assertEqual(dargs.values(), ['bar'])

    def test_args_dargs_subclass(self):
        # save some typing
        VC = self.virsh.VirshClosure
        tcinst = self.SomeClass(foo='bar')
        vcinst = VC(self.somefunc, tcinst)
        args, dargs = vcinst('foo')
        self.assertEqual(len(args), 1)
        self.assertEqual(args[0], 'foo')
        self.assertEqual(len(dargs), 1)
        self.assertEqual(dargs.keys(), ['foo'])
        self.assertEqual(dargs.values(), ['bar'])

    def test_update_args_dargs_subclass(self):
        # save some typing
        VC = self.virsh.VirshClosure
        tcinst = self.SomeClass(foo='bar')
        vcinst = VC(self.somefunc, tcinst)
        args, dargs = vcinst('foo')
        self.assertEqual(len(args), 1)
        self.assertEqual(args[0], 'foo')
        self.assertEqual(len(dargs), 1)
        self.assertEqual(dargs.keys(), ['foo'])
        self.assertEqual(dargs.values(), ['bar'])
        # Update dictionary
        tcinst['sna'] = 'fu'
        # Is everything really the same?
        args, dargs = vcinst('foo', 'baz')
        self.assertEqual(len(args), 2)
        self.assertEqual(args[0], 'foo')
        self.assertEqual(args[1], 'baz')
        self.assertEqual(len(dargs), 2)
        self.assertEqual(dargs['foo'], 'bar')
        self.assertEqual(dargs['sna'], 'fu')

    def test_multi_inst(self):
        # save some typing
        VC1 = self.virsh.VirshClosure
        VC2 = self.virsh.VirshClosure
        tcinst1 = self.SomeClass(darg1=1)
        tcinst2 = self.SomeClass(darg1=2)
        vcinst1 = VC1(self.somefunc, tcinst1)
        vcinst2 = VC2(self.somefunc, tcinst2)
        args1, dargs1 = vcinst1(1)
        args2, dargs2 = vcinst2(2)
        self.assertEqual(len(args1), 1)
        self.assertEqual(len(args2), 1)
        self.assertEqual(args1[0], 1)
        self.assertEqual(args2[0], 2)
        self.assertEqual(len(dargs1), 1)
        self.assertEqual(len(dargs2), 1)
        self.assertEqual(dargs1['darg1'], 1)
        self.assertEqual(dargs2['darg1'], 2)


class ConstructorsTest(ModuleLoad):

    def test_VirshBase(self):
        vb = self.virsh.VirshBase()
        del vb  # keep pylint happy

    def test_Virsh(self):
        v = self.virsh.Virsh()
        del v  # keep pylint happy

    def test_VirshPersistent(self):
        test_virsh = self.virsh.Virsh()
        if test_virsh['virsh_exec'] == '/bin/true':
            return
        else:
            logging.disable(logging.INFO)
            vp = self.virsh.VirshPersistent()
            vp.close_session()  # Make sure session gets cleaned up

    def TestVirshClosure(self):
        vc = self.virsh.VirshClosure(None, {})
        del vc  # keep pylint happy


# Ensure the following tests ONLY run if a valid virsh command exists #####
class ModuleLoadCheckVirsh(unittest.TestCase):
    import virsh

    def run(self, *args, **dargs):
        test_virsh = self.virsh.Virsh()
        if test_virsh['virsh_exec'] == '/bin/true':
            return  # Don't run any tests, no virsh executable was found
        else:
            super(ModuleLoadCheckVirsh, self).run(*args, **dargs)


class SessionManagerTest(ModuleLoadCheckVirsh):

    def test_del_VirshPersistent(self):
        """
        Unittest for __del__ of VirshPersistent.

        This test makes sure the __del__ method of VirshPersistent works
        well in `del vp_instance`.
        """
        vp = self.virsh.VirshPersistent()
        virsh_exec = vp.virsh_exec
        self.assertTrue(utils.process_is_alive(virsh_exec))
        del vp
        self.assertFalse(utils.process_is_alive(virsh_exec))

    def test_VirshSession(self):
        """
        Unittest for VirshSession.

        This test use VirshSession over VirshPersistent with auto_close=True.
        """
        virsh_exec = self.virsh.Virsh()['virsh_exec']
        # Build a VirshSession object.
        session_1 = self.virsh.VirshSession(virsh_exec, auto_close=True)
        self.assertTrue(utils.process_is_alive(virsh_exec))
        del session_1
        self.assertFalse(utils.process_is_alive(virsh_exec))

    def test_VirshPersistent(self):
        """
        Unittest for session manager of VirshPersistent.
        """
        virsh_exec = self.virsh.Virsh()['virsh_exec']
        vp_1 = self.virsh.VirshPersistent()
        self.assertTrue(utils.process_is_alive(virsh_exec))
        # Init the vp_2 with same params of vp_1.
        vp_2 = self.virsh.VirshPersistent(**vp_1)
        # Make sure vp_1 and vp_2 are refer to the same session.
        self.assertEqual(vp_1.session_id, vp_2.session_id)

        del vp_1
        # Make sure the session is not closed when vp_2 still refer to it.
        self.assertTrue(utils.process_is_alive(virsh_exec))
        del vp_2
        # Session was closed since no other VirshPersistent refer to it.
        self.assertFalse(utils.process_is_alive(virsh_exec))


class VirshHasHelpCommandTest(ModuleLoadCheckVirsh):

    def setUp(self):
        # subclasses override self.virsh
        self.VIRSH_COMMAND_CACHE = self.virsh.VIRSH_COMMAND_CACHE

    def test_false_command(self):
        self.assertFalse(self.virsh.has_help_command('print'))
        self.assertFalse(self.virsh.has_help_command('Commands:'))
        self.assertFalse(self.virsh.has_help_command('dom'))
        self.assertFalse(self.virsh.has_help_command('pool'))

    def test_true_command(self):
        self.assertTrue(self.virsh.has_help_command('uri'))
        self.assertTrue(self.virsh.has_help_command('help'))
        self.assertTrue(self.virsh.has_help_command('list'))

    def test_no_cache(self):
        self.VIRSH_COMMAND_CACHE = None
        self.assertTrue(self.virsh.has_help_command('uri'))
        self.VIRSH_COMMAND_CACHE = []
        self.assertTrue(self.virsh.has_help_command('uri'))

    def test_subcommand_help(self):
        regex = r'\s+\[--command\]\s+\<string\>\s+'
        self.assertTrue(self.virsh.has_command_help_match('help', regex))
        self.assertFalse(self.virsh.has_command_help_match('uri', regex))

    def test_groups_in_commands(self):
        # groups will be empty in older libvirt, but test will still work
        groups = self.virsh.help_command_group(cache=True)
        groups_set = set(groups)
        commands = self.virsh.help_command_only(cache=True)
        commands_set = set(commands)
        grp_cmd = self.virsh.help_command(cache=True)
        grp_cmd_set = set(grp_cmd)
        # No duplicates check
        self.assertEqual(len(commands_set), len(commands))
        self.assertEqual(len(groups_set), len(groups))
        self.assertEqual(len(grp_cmd_set), len(grp_cmd))
        # No groups in commands or commands in groups
        self.assertEqual(len(groups_set & commands_set), 0)
        # Groups and Commands in help_command
        self.assertTrue(len(grp_cmd_set), len(commands_set) + len(groups_set))


class VirshHelpCommandTest(ModuleLoadCheckVirsh):

    def test_cache_command(self):
        l1 = self.virsh.help_command(cache=True)
        l2 = self.virsh.help_command()
        l3 = self.virsh.help_command()
        self.assertEqual(l1, l2)
        self.assertEqual(l2, l3)
        self.assertEqual(l3, l1)


class VirshClassHasHelpCommandTest(VirshHasHelpCommandTest):

    def setUp(self):
        logging.disable(logging.INFO)
        super(VirshClassHasHelpCommandTest, self).setUp()
        self.virsh = self.virsh.Virsh(debug=False)


class VirshPersistentClassHasHelpCommandTest(VirshHasHelpCommandTest):

    def setUp(self):
        logging.disable(logging.INFO)
        super(VirshPersistentClassHasHelpCommandTest, self).setUp()
        self.VirshPersistent = self.virsh.VirshPersistent
        self.virsh = self.VirshPersistent(debug=False)
        self.assertTrue(utils.process_is_alive(self.virsh.virsh_exec))

    def test_recycle_session(self):
        # virsh can be used as a dict of it's properties
        another = self.VirshPersistent(**self.virsh)
        self.assertEqual(self.virsh.session_id, another.session_id)

    def tearDown(self):
        self.assertTrue(utils.process_is_alive(self.virsh.virsh_exec))
        self.virsh.close_session()
        self.assertFalse(utils.process_is_alive(self.virsh.virsh_exec))


if __name__ == '__main__':
    unittest.main()
