import unittest, logging, os
import gzip
import cartesian_config

mydir = os.path.dirname(__file__)
testdatadir = os.path.join(mydir, 'unittest_data')

class CartesianConfigTest(unittest.TestCase):
    def _checkDictionaries(self, parser, reference):
        result = list(parser.get_dicts())
        # as the dictionary list is very large, test each item individually:
        self.assertEquals(len(result), len(reference))
        for resdict, refdict in zip(result, reference):
            # checking the dict name first should make some errors more visible
            self.assertEquals(resdict.get('name'), refdict.get('name'))
            self.assertEquals(resdict, refdict)

    def _checkConfigDump(self, config, dump):
        """Check if the parser output matches a config file dump"""
        configpath = os.path.join(testdatadir, config)
        dumppath = os.path.join(testdatadir, dump)

        if dumppath.endswith('.gz'):
            df = gzip.GzipFile(dumppath, 'r')
        else:
            df = open(dumppath, 'r')
        # we could have used pickle, but repr()-based dumps are easier to
        # enerate, debug, and edit
        dumpdata = eval(df.read())

        p = cartesian_config.Parser(configpath)
        self._checkDictionaries(p, dumpdata)

    def _checkStringConfig(self, string, reference):
        p = cartesian_config.Parser()
        p.parse_string(string)
        self._checkDictionaries(p, reference)


    def _checkStringDump(self, string, dump, defaults=False):
        p = cartesian_config.Parser(defaults=defaults)
        p.parse_string(string)

        self._checkDictionaries(p, dump)


    def testSimpleVariant(self):
        self._checkStringConfig("""
            c = abc
            variants:
                a:
                    x = va
                b:
                    x = vb
            """,
            [dict(name='a', shortname='a', dep=[], x='va', c='abc'),
             dict(name='b', shortname='b', dep=[], x='vb', c='abc')])


    def testFilterMixing(self):
        self._checkStringDump("""
            variants:
                - unknown_qemu:
                - rhel64:
            only unknown_qemu
            variants:
                - kvm:
                - nokvm:
            variants:
                - testA:
                    nokvm:
                        no unknown_qemu
                - testB:
            """,
            [
                {'dep': [],
                 'name': 'testA.kvm.unknown_qemu',
                 'shortname': 'testA.kvm.unknown_qemu'},
                {'dep': [],
                 'name': 'testB.kvm.unknown_qemu',
                 'shortname': 'testB.kvm.unknown_qemu'},
                {'dep': [],
                 'name': 'testB.nokvm.unknown_qemu',
                 'shortname': 'testB.nokvm.unknown_qemu'},
            ]
            )


    def testNameVariant(self):
        self._checkStringDump("""
            variants name=tests: # All tests in configuration
              - wait:
                   run = "wait"
                   variants:
                     - long:
                        time = short_time
                     - short: long
                        time = logn_time
              - test2:
                   run = "test1"

            variants name=virt_system:
              - @linux:
              - windows:

            variants name=host_os:
              - linux:
                   image = linux
              - windows:
                   image = windows

            only host_os>linux
            """,
            [
                {'dep': [],
                 'host_os': 'linux',
                 'image': 'linux',
                 'name': 'host_os>linux.virt_system>linux.tests>wait.long',
                 'run': 'wait',
                 'shortname': 'host_os>linux.tests>wait.long',
                 'tests': 'wait',
                 'time': 'short_time',
                 'virt_system': 'linux'},
                {'dep': ['host_os>linux.virt_system>linux.tests>wait.long'],
                 'host_os': 'linux',
                 'image': 'linux',
                 'name': 'host_os>linux.virt_system>linux.tests>wait.short',
                 'run': 'wait',
                 'shortname': 'host_os>linux.tests>wait.short',
                 'tests': 'wait',
                 'time': 'logn_time',
                 'virt_system': 'linux'},
                {'dep': [],
                 'host_os': 'linux',
                 'image': 'linux',
                 'name': 'host_os>linux.virt_system>linux.tests>test2',
                 'run': 'test1',
                 'shortname': 'host_os>linux.tests>test2',
                 'tests': 'test2',
                 'virt_system': 'linux'},
                {'dep': [],
                 'host_os': 'linux',
                 'image': 'linux',
                 'name': 'host_os>linux.virt_system>windows.tests>wait.long',
                 'run': 'wait',
                 'shortname': 'host_os>linux.virt_system>windows.tests>wait.long',
                 'tests': 'wait',
                 'time': 'short_time',
                 'virt_system': 'windows'},
                {'dep': ['host_os>linux.virt_system>windows.tests>wait.long'],
                 'host_os': 'linux',
                 'image': 'linux',
                 'name': 'host_os>linux.virt_system>windows.tests>wait.short',
                 'run': 'wait',
                 'shortname': 'host_os>linux.virt_system>windows.tests>wait.short',
                 'tests': 'wait',
                 'time': 'logn_time',
                 'virt_system': 'windows'},
                {'dep': [],
                 'host_os': 'linux',
                 'image': 'linux',
                 'name': 'host_os>linux.virt_system>windows.tests>test2',
                 'run': 'test1',
                 'shortname': 'host_os>linux.virt_system>windows.tests>test2',
                 'tests': 'test2',
                 'virt_system': 'windows'},
            ])


    def testDefaults(self):
        self._checkStringDump("""
            variants name=tests:
              - wait:
                   run = "wait"
                   variants:
                     - long:
                        time = short_time
                     - short: long
                        time = logn_time
              - test2:
                   run = "test1"

            variants name=virt_system, with_default:
              - @linux:
              - windows:

            variants name=host_os, with_default:
              - linux:
                   image = linux
              - @windows:
                   image = windows
            """,
            [
                {'dep': [],
                 'host_os': 'windows',
                 'image': 'windows',
                 'name': 'host_os>windows.virt_system>linux.tests>wait.long',
                 'run': 'wait',
                 'shortname': 'tests>wait.long',
                 'tests': 'wait',
                 'time': 'short_time',
                 'virt_system': 'linux'},
                {'dep': ['host_os>windows.virt_system>linux.tests>wait.long'],
                 'host_os': 'windows',
                 'image': 'windows',
                 'name': 'host_os>windows.virt_system>linux.tests>wait.short',
                 'run': 'wait',
                 'shortname': 'tests>wait.short',
                 'tests': 'wait',
                 'time': 'logn_time',
                 'virt_system': 'linux'},
                {'dep': [],
                 'host_os': 'windows',
                 'image': 'windows',
                 'name': 'host_os>windows.virt_system>linux.tests>test2',
                 'run': 'test1',
                 'shortname': 'tests>test2',
                 'tests': 'test2',
                 'virt_system': 'linux'},
                ]
            , True)


    def testDefaultsExactlyOne(self):
        with self.assertRaises(cartesian_config.ParserError):
            self._checkStringDump("""
                variants name=host_os, with_default:
                  - @linux:
                       image = linux
                       variants with_default:
                            - ubuntu:
                            - @fedora:
                  - @windows:
                       image = windows
                       variants:
                            - @XP:
                            - WIN7:

                only host_os>windows
                """,
                []
                , True)

        with self.assertRaises(cartesian_config.ParserError):
            self._checkStringDump("""
                variants name=host_os, with_default:
                  - linux:
                       image = linux
                       variants with_default:
                            - ubuntu:
                            - @fedora:
                  - windows:
                       image = windows
                       variants:
                            - @XP:
                            - WIN7:

                only host_os>windows
                """,
                []
                , True)


    def testHugeTest1(self):
        self._checkConfigDump('testcfg.huge/test1.cfg',
                              'testcfg.huge/test1.cfg.repr.gz')

if __name__ == '__main__':
    unittest.main()
