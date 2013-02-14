import unittest, logging, os
import gzip
import cartesian_config

class CartesianConfigTest(unittest.TestCase):
    def _checkDictionaries(self, parser, reference):
        result = list(parser.get_dicts())
        # as the dictionary list is very large, test each item individually:
        self.assertEquals(len(result), len(reference))
        for resdict,refdict in zip(result, reference):
            # checking the dict name first should make some errors more visible
            self.assertEquals(resdict.get('name'), refdict.get('name'))
            self.assertEquals(resdict, refdict)

    def _checkStringConfig(self, string, reference):
        p = cartesian_config.Parser()
        p.parse_string(string)
        self._checkDictionaries(p, reference)

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

    def testHugeTest1(self):
        self._testConfigDump('testcfg.huge/test1.cfg', 'testcfg.huge/test1.cfg.repr.gz')

if __name__ == '__main__':
    unittest.main()
