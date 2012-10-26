#!/usr/bin/python

import unittest, time
import common


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
        self.assertRaises(ValueError, VC, lambda :None, self)


    def test_args(self):
        # save some typing
        VC = self.virsh.VirshClosure
        tcinst = {}
        vcinst = VC(self.somefunc, tcinst)
        args, dargs = vcinst('foo')
        self.assertEqual(len(args), 1)
        self.assertEqual(args[0], 'foo')
        self.assertEqual(len(dargs), 0)


    def test_dargs(self):
        # save some typing
        VC = self.virsh.VirshClosure
        tcinst = {'foo':'bar'}
        vcinst = VC(self.somefunc, tcinst)
        args, dargs = vcinst()
        self.assertEqual(len(args), 0)
        self.assertEqual(len(dargs), 1)
        self.assertEqual(dargs.keys(), ['foo'])
        self.assertEqual(dargs.values(), ['bar'])


    def test_args_and_dargs(self):
        # save some typing
        VC = self.virsh.VirshClosure
        tcinst = {'foo':'bar'}
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
        del vb # keep pylint happy


    def test_Virsh(self):
        v = self.virsh.Virsh()
        del v # keep pylint happy


    def test_VirshPersistent(self):
        vp = self.virsh.VirshPersistent()
        self.assertEqual(self.virsh.VirshPersistent.SESSION_COUNTER, 1)
        vp.close_session() # Make sure session gets cleaned up
        self.assertEqual(self.virsh.VirshPersistent.SESSION_COUNTER, 0)


    def TestVirshClosure(self):
        vc = self.virsh.VirshClosure(None, {})
        del vc # keep pylint happy


##### Ensure the following tests ONLY run if a valid virsh command exists #####
class ModuleLoadCheckVirsh(unittest.TestCase):

    import virsh

    def run(self, *args, **dargs):
        test_virsh = self.virsh.Virsh()
        if test_virsh['virsh_exec'] == '/bin/true':
            return # Don't run any tests, no virsh executable was found
        else:
            super(ModuleLoadCheckVirsh, self).run(*args, **dargs)


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
        super(VirshClassHasHelpCommandTest, self).setUp()
        self.virsh = self.virsh.Virsh(debug=False)


class VirshPersistentClassHasHelpCommandTest(VirshHasHelpCommandTest):

    def setUp(self):
        super(VirshPersistentClassHasHelpCommandTest, self).setUp()
        self.VirshPersistent = self.virsh.VirshPersistent
        self.assertEqual(self.VirshPersistent.SESSION_COUNTER, 0)
        self.virsh = self.VirshPersistent(debug=False)
        self.assertEqual(self.VirshPersistent.SESSION_COUNTER, 1)


    def tearDown(self):
        self.assertEqual(self.VirshPersistent.SESSION_COUNTER, 1)
        self.virsh.close_session()
        self.assertEqual(self.VirshPersistent.SESSION_COUNTER, 0)


if __name__ == '__main__':
    unittest.main()
