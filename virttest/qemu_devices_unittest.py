#!/usr/bin/python
"""
This is a unittest for qemu_qtree library.

@author: Lukas Doktor <ldoktor@redhat.com>
@copyright: 2012 Red Hat, Inc.
"""
__author__ = """Lukas Doktor (ldoktor@redhat.com)"""

import unittest
import qemu_devices


class Devices(unittest.TestCase):
    """ set of qemu devices tests """
    def test_q_base_device(self):
        """ QBaseDevice tests """
        qdevice = qemu_devices.QBaseDevice('MyType',
                                      {'ParamA': 'ValueA', 'AUTOREMOVE': None},
                                      'Object1',
                                      {'type': 'pci'})
        self.assertEqual(qdevice['ParamA'], 'ValueA', 'Param added during '
                         '__init__ is corrupted %s != %s' % (qdevice['ParamA'],
                                                             'ValueA'))
        qdevice['ParamA'] = 'ValueB'
        qdevice.set_param('BoolTrue', True)
        qdevice.set_param('BoolFalse', 'off', bool)
        qdevice['Empty'] = 'EMPTY_STRING'

        out = """MyType
  aid = None
  aobject = Object1
  parent_bus = {'type': 'pci'}
  child_bus = ()
  params:
    ParamA = ValueB
    BoolTrue = on
    BoolFalse = off
    Empty = ""
"""
        self.assertEqual(qdevice.str_long(), out, "Device output doesn't match"
                         "\n%s\n\n%s" % (qdevice.str_long(), out))

    def test_q_string_device(self):
        """ QStringDevice tests """
        qdevice = qemu_devices.QStringDevice('MyType', {'addr': '0x7'},
                                    cmdline='-qdevice ahci,addr=%(addr)s')
        self.assertEqual(qdevice.cmdline(), '-qdevice ahci,addr=0x7', "Cmdline"
                         " doesn't match expected one:\n%s\n%s"
                         % (qdevice.cmdline(), '-qdevice ahci,addr=0x7'))

    def test_q_device(self):
        """ QDevice tests """
        qdevice = qemu_devices.QDevice('ahci', {'addr': '0x7'})

        self.assertEqual(str(qdevice), "a'ahci'", "Alternative name error %s "
                         "!= %s" % (str(qdevice), "a'ahci'"))

        qdevice['id'] = 'ahci1'
        self.assertEqual(str(qdevice), "q'ahci1'", "Id name error %s "
                         "!= %s" % (str(qdevice), "q'ahci1'"))

        exp = "device_add addr=0x7,driver=ahci,id=ahci1"
        out = qdevice.hotplug_hmp()
        self.assertEqual(out, exp, "HMP command corrupted:\n%s\n%s"
                         % (out, exp))

        exp = ("('device_add', OrderedDict([('addr', '0x7'), "
               "('driver', 'ahci'), ('id', 'ahci1')]))")
        out = str(qdevice.hotplug_qmp())
        self.assertEqual(out, exp, "QMP command corrupted:\n%s\n%s"
                         % (out, exp))


if __name__ == "__main__":
    unittest.main()
