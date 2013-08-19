import unittest
from qemu_monitor import Monitor

class InfoNumaTests(unittest.TestCase):
    def testZeroNodes(self):
        d = "0 nodes\n"
        r = Monitor.parse_info_numa(d)
        self.assertEquals(r, [])

    def testTwoNodes(self):
        d = "2 nodes\n" + \
            "node 0 cpus: 0 2 4\n" + \
            "node 0 size: 12 MB\n" + \
            "node 1 cpus: 1 3 5\n" + \
            "node 1 size: 34 MB\n"
        r = Monitor.parse_info_numa(d)
        self.assertEquals(r, [(12, set([0, 2, 4])),
                              (34, set([1, 3, 5]))])

if __name__ == "__main__":
    unittest.main()
