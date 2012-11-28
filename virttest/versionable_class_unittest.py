#!/usr/bin/python

import unittest, logging
try:
    import autotest.common as common
except ImportError:
    import common
from autotest.client.shared import base_utils
from autotest.client.shared.test_utils import mock
import versionable_class

class TestVersionableClass(unittest.TestCase):
    def setUp(self):
        self.god = mock.mock_god(ut=self)
        self.god.stub_function(base_utils.logging, 'warn')
        self.god.stub_function(base_utils.logging, 'debug')
        self.version = 1


    def tearDown(self):
        self.god.unstub_all()


    class FooC(object):
        pass

    #Not implemented get_version -> not used for versioning.
    class VCP(FooC, versionable_class.VersionableClass):
        def __new__(cls, *args, **kargs):
            TestVersionableClass.VCP.version = 1       # Only for unittesting.
            TestVersionableClass.VCP.master_class = TestVersionableClass.VCP
            return (super(TestVersionableClass.VCP, cls)
                                                .__new__(cls, *args, **kargs))


        def foo(self):
            pass

    class VC2(VCP, versionable_class.VersionableClass):
        @classmethod
        def get_version(cls):
            return cls.version

        @classmethod
        def is_right_version(cls, version):
            if version is not None:
                if version == 1:
                    return True
            return False

        def func1(self):
            logging.info("func1")

        def func2(self):
            logging.info("func2")

    # get_version could be inherited.
    class VC3(VC2, versionable_class.VersionableClass):
        @classmethod
        def is_right_version(cls, version):
            if version is not None:
                if version == 2:
                    return True
            return False

        def func2(self):
            logging.info("func2_2")

    class PP(versionable_class.VersionableClass):
        def __new__(cls, *args, **kargs):
            TestVersionableClass.PP.version = 1       # Only for unittesting.
            TestVersionableClass.PP.master_class = TestVersionableClass.PP
            return (super(TestVersionableClass.PP, cls)
                                                 .__new__(cls, *args, **kargs))

    class PP2(PP, versionable_class.VersionableClass):
        @classmethod
        def get_version(cls):
            return cls.version

        @classmethod
        def is_right_version(cls, version):
            if version is not None:
                if cls.version == 1:
                    return True
            return False

        def func1(self):
            print "PP func1"


    class WP(versionable_class.VersionableClass):
        def __new__(cls, *args, **kargs):
            TestVersionableClass.WP.version = 1       # Only for unittesting.
            TestVersionableClass.WP.master_class = TestVersionableClass.WP
            return (super(TestVersionableClass.WP, cls)
                                                 .__new__(cls, *args, **kargs))

    class WP2(WP, versionable_class.VersionableClass):
        @classmethod
        def get_version(cls):
            return cls.version

        def func1(self):
            print "WP func1"


    class N(VCP, PP):
        pass

    class NN(N):
        pass

    class M(VCP):
        pass

    class MM(M):
        pass

    class W(WP):
        pass


    def test_simple_versioning(self):
        self.god.stub_function(TestVersionableClass.VCP, "foo")
        self.god.stub_function(TestVersionableClass.VC2, "func1")
        self.god.stub_function(TestVersionableClass.VC2, "func2")
        self.god.stub_function(TestVersionableClass.VC3, "func2")

        TestVersionableClass.VC2.func2.expect_call()
        TestVersionableClass.VC2.func1.expect_call()
        TestVersionableClass.VCP.foo.expect_call()
        TestVersionableClass.VC3.func2.expect_call()

        TestVersionableClass.VC2.func2.expect_call()
        TestVersionableClass.VC2.func1.expect_call()
        TestVersionableClass.VCP.foo.expect_call()
        TestVersionableClass.VC3.func2.expect_call()

        m = TestVersionableClass.M()
        m.func2()   # call VC3.func2(m)
        m.func1()   # call VC2.func1(m)
        m.foo()     # call VC1.foo(m)
        m.version = 2
        m.check_repair_versions()
        m.func2()

        #m.version = 1
        #m.check_repair_versions()

        mm = TestVersionableClass.MM()
        mm.func2()   # call VC3.func2(m)
        mm.func1()   # call VC2.func1(m)
        mm.foo()     # call VC1.foo(m)
        mm.version = 2
        mm.check_repair_versions()
        mm.func2()

        self.god.check_playback()

    def test_set_class_priority(self):
        self.god.stub_function(TestVersionableClass.VC2, "func1")
        self.god.stub_function(TestVersionableClass.VC2, "func2")
        self.god.stub_function(TestVersionableClass.VC3, "func2")
        self.god.stub_function(TestVersionableClass.PP2, "func1")

        TestVersionableClass.VC2.func1.expect_call()
        TestVersionableClass.PP2.func1.expect_call()
        TestVersionableClass.VC3.func2.expect_call()
        TestVersionableClass.PP2.func1.expect_call()
        TestVersionableClass.VC2.func1.expect_call()
        TestVersionableClass.VC2.func2.expect_call()

        m = TestVersionableClass.N()
        m.func1()
        m.set_priority_class(TestVersionableClass.PP,
                             [TestVersionableClass.PP,
                              TestVersionableClass.VCP])
        m.func1()

        m.version = 2
        m.check_repair_versions()
        m.func2()
        m.func1()

        m.set_priority_class(TestVersionableClass.VCP,
                             [TestVersionableClass.PP,
                              TestVersionableClass.VCP])

        m.func1()

        m.version = 1
        m.check_repair_versions()
        m.func2()

        self.god.check_playback()


    def test_set_class_priority_deep(self):
        self.god.stub_function(TestVersionableClass.VC2, "func1")
        self.god.stub_function(TestVersionableClass.VC2, "func2")
        self.god.stub_function(TestVersionableClass.VC3, "func2")
        self.god.stub_function(TestVersionableClass.PP2, "func1")

        TestVersionableClass.VC2.func1.expect_call()
        TestVersionableClass.PP2.func1.expect_call()
        TestVersionableClass.VC3.func2.expect_call()
        TestVersionableClass.PP2.func1.expect_call()
        TestVersionableClass.VC2.func1.expect_call()
        TestVersionableClass.VC2.func2.expect_call()

        m = TestVersionableClass.NN()
        m.func1()
        m.set_priority_class(TestVersionableClass.PP,
                             [TestVersionableClass.PP,
                              TestVersionableClass.VCP])
        m.func1()

        m.version = 2
        m.check_repair_versions()
        m.func2()
        m.func1()

        m.set_priority_class(TestVersionableClass.VCP,
                             [TestVersionableClass.PP,
                              TestVersionableClass.VCP])

        m.func1()

        m.version = 1
        m.check_repair_versions()
        m.func2()

        self.god.check_playback()


    def test_check_not_implemented(self):
        m = TestVersionableClass.W()
        self.assertEqual(m.__class__.__bases__,
                      tuple([TestVersionableClass.WP2]),
                      "Class should be WP2 (last defined class in class"
                      " hierarchy).")

if __name__ == "__main__":
    unittest.main()
