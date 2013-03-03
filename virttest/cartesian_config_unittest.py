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
        for resdict,refdict in zip(result, reference):
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


    def _checkStringDump(self, string, dump):
        p = cartesian_config.Parser()
        p.parse_string(string)

        dumpdata = None
        exec "dumpdata = " + dump
        self._checkDictionaries(p, dumpdata)


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
            """[
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
            """)


    def testHugeTest1(self):
        self._checkConfigDump('testcfg.huge/test1.cfg',
                              'testcfg.huge/test1.cfg.repr.gz')

if __name__ == '__main__':
    unittest.main()
