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




class Buses(unittest.TestCase):
    def test_q_sparse_bus(self):
        """ Sparse bus tests (general bus testing) """
        bus = qemu_devices.QSparseBus('bus',
                                      (['addr1', 'addr2', 'addr3'], [2, 6, 4]),
                                      'my_bus',
                                      'bus_type',
                                      'autotest_bus')

        qdevice = qemu_devices.QDevice

        # Correct records
        params = {'addr1': '0', 'addr2': '0', 'addr3': '0', 'bus': 'my_bus'}
        dev = qdevice('dev1', params, parent_bus={'type': 'bus_type'})
        exp = True
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Failed to add device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        params = {'addr1': '1', 'addr2': '0', 'addr3': '0', 'bus': 'my_bus'}
        dev = qdevice('dev2', params, parent_bus={'type': 'bus_type'})
        exp = True
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Failed to add device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        params = {'addr1': '1', 'addr2': '1', 'addr3': '0', 'bus': 'my_bus'}
        dev = qdevice('dev3', params, parent_bus={'type': 'bus_type'})
        exp = True
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Failed to add device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        params = {'addr1': '1', 'addr2': '1', 'addr3': '1', 'bus': 'my_bus'}
        dev = qdevice('dev4', params, parent_bus={'type': 'bus_type'})
        exp = True
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Failed to add device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        params = {'addr1': '1', 'bus': 'my_bus'}
        dev = qdevice('dev5', params, parent_bus={'type': 'bus_type'})
        exp = True
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Failed to add device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        params = {'bus': 'my_bus'}
        dev = qdevice('dev6', params, parent_bus={'type': 'bus_type'})
        exp = True
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Failed to add device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        params = {}
        dev = qdevice('dev7', params, parent_bus={'type': 'bus_type'})
        exp = True
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Failed to add device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        # Compare short repr
        exp = ("my_bus(bus_type): {0-0-0:a'dev1',0-0-1:a'dev6',0-0-2:a'dev7',"
               "1-0-0:a'dev2',1-0-1:a'dev5',1-1-0:a'dev3',1-1-1:a'dev4'}  {}")
        out = str(bus.str_short())
        self.assertEqual(out, exp, "Short representation corrupted:\n%s\n%s"
                         "\n\n%s" % (out, exp, bus.str_long()))

        # Incorrect records
        # Used address
        params = {'addr1': '0', 'addr2': '0', 'addr3': '0', 'bus': 'my_bus'}
        dev = qdevice('devI1', params, parent_bus={'type': 'bus_type'})
        exp = None
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Added bad device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        # Out of range address
        params = {'addr1': '0', 'addr2': '6', 'addr3': '0', 'bus': 'my_bus'}
        dev = qdevice('devI2', params, parent_bus={'type': 'bus_type'})
        exp = False
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Added bad device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        # Incorrect bus name
        params = {'bus': 'other_bus'}
        dev = qdevice('devI3', params, parent_bus={'type': 'bus_type'})
        exp = False
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Added bad device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        # Compare short repr
        exp = ("my_bus(bus_type): {0-0-0:a'dev1',0-0-1:a'dev6',0-0-2:a'dev7',"
               "1-0-0:a'dev2',1-0-1:a'dev5',1-1-0:a'dev3',1-1-1:a'dev4'}  {}")
        out = str(bus.str_short())
        self.assertEqual(out, exp, "Short representation corrupted:\n%s\n%s"
                         "\n\n%s" % (out, exp, bus.str_long()))

        # Forced records
        # Used address
        params = {'addr1': '0', 'addr2': '0', 'addr3': '0', 'bus': 'my_bus'}
        dev = qdevice('devB1', params, parent_bus={'type': 'bus_type'})
        exp = "(errors: UsedSlot)"
        out = bus.insert(dev, False, True)
        self.assertEqual(exp in out, True, "%s not in %s\n%s\n\n%s"
                         % (exp, out, dev.str_long(), bus.str_long()))

        # Out of range address
        params = {'addr1': '0', 'addr2': '6', 'addr3': '0', 'bus': 'my_bus'}
        dev = qdevice('devB2', params, parent_bus={'type': 'bus_type'})
        exp = "(errors: BadAddr([0, 6, 0]))"
        out = bus.insert(dev, False, True)
        self.assertEqual(exp in out, True, "%s not in %s\n%s\n\n%s"
                         % (exp, out, dev.str_long(), bus.str_long()))

        # Incorrect bus name
        params = {'bus': 'other_bus'}
        dev = qdevice('devB3', params, parent_bus={'type': 'bus_type'})
        exp = "(errors: BusId)"
        out = bus.insert(dev, False, True)
        self.assertEqual(exp in out, True, "%s not in %s\n%s\n\n%s"
                         % (exp, out, dev.str_long(), bus.str_long()))

        # Compare short repr
        exp = ("my_bus(bus_type): {0-0-0:a'dev1',0-0-1:a'dev6',0-0-2:a'dev7',"
               "0-0-3:a'devB3',1-0-0:a'dev2',1-0-1:a'dev5',1-1-0:a'dev3',"
               "1-1-1:a'dev4'}  {0-0-0(2x):a'devB1',o0-6-0:a'devB2'}")
        out = str(bus.str_short())
        self.assertEqual(out, exp, "Short representation corrupted:\n%s\n%s"
                         "\n\n%s" % (out, exp, bus.str_long()))

        # Compare long repr
        exp = """Bus my_bus, type=bus_type
Slots:
---------------< 1-0-0 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = ()
    params:
      bus = my_bus
      addr2 = 0
      addr3 = 0
      addr1 = 1
      driver = dev2
---------------< 1-0-1 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = ()
    params:
      bus = my_bus
      addr1 = 1
      driver = dev5
---------------< 1-1-1 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = ()
    params:
      bus = my_bus
      addr2 = 1
      addr3 = 1
      addr1 = 1
      driver = dev4
---------------< 1-1-0 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = ()
    params:
      bus = my_bus
      addr2 = 1
      addr3 = 0
      addr1 = 1
      driver = dev3
---------------< 0-0-1 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = ()
    params:
      bus = my_bus
      driver = dev6
---------------< 0-0-0 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = ()
    params:
      bus = my_bus
      addr2 = 0
      addr3 = 0
      addr1 = 0
      driver = dev1
---------------< 0-0-3 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = ()
    params:
      bus = my_bus
      driver = devB3
---------------< 0-0-2 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = ()
    params:
      driver = dev7

---------------< o0-6-0 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = ()
    params:
      bus = my_bus
      addr2 = 6
      addr3 = 0
      addr1 = 0
      driver = devB2
---------------< 0-0-0(2x) >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = ()
    params:
      bus = my_bus
      addr2 = 0
      addr3 = 0
      addr1 = 0
      driver = devB1
"""
        out = str(bus.str_long())
        self.assertEqual(out, exp, "Long representation corrupted:\n%s\n%s"
                         % (repr(out), exp))

        # Low level functions
        # Get device by object
        exp = dev
        out = bus.get(dev)
        self.assertEqual(out, exp, "Failed to get device from bus:\n%s\n%s"
                         "\n\n%s" % (out, exp, bus.str_long()))

        dev.aid = 'bad_device3'
        exp = dev
        out = bus.get('bad_device3')
        self.assertEqual(out, exp, "Failed to get device from bus:\n%s\n%s"
                         "\n\n%s" % (out, exp, bus.str_long()))

        exp = None
        out = bus.get('missing_bad_device')
        self.assertEqual(out, exp, "Got device while expecting None:\n%s\n%s"
                         "\n\n%s" % (out, exp, bus.str_long()))

        # Remove all devices
        devs = [dev for dev in bus]
        for dev in devs:
            bus.remove(dev)

        exp = 'Bus my_bus, type=bus_type\nSlots:\n\n'
        out = str(bus.str_long())
        self.assertEqual(out, exp, "Long representation corrupted:\n%s\n%s"
                         % (out, exp))

    def test_q_pci_bus(self):
        """ PCI bus tests """
        bus = qemu_devices.QPCIBus('pci.0', 'pci', 'my_pci')
        qdevice = qemu_devices.QDevice

        # Good devices
        params = {'addr': '0'}
        dev = qdevice('dev1', params, parent_bus={'type': 'pci'})
        exp = True
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Failed to add device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        params = {'addr': 10, 'bus': 'pci.0'}
        dev = qdevice('dev2', params, parent_bus={'type': 'pci'})
        exp = True
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Failed to add device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        params = {'addr': '0x1f'}
        dev = qdevice('dev3', params, parent_bus={'type': 'pci'})
        exp = True
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Failed to add device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        # Compare short repr
        exp = ("pci.0(pci): [a'dev1',None,None,None,None,None,None,None,None,"
               "None,a'dev2',None,None,None,None,None,None,None,None,None,"
               "None,None,None,None,None,None,None,None,None,None,None,"
               "a'dev3']  {}")
        out = str(bus.str_short())
        self.assertEqual(out, exp, "Short representation corrupted:\n%s\n%s"
                         "\n\n%s" % (out, exp, bus.str_long()))

        # Incorrect records
        # Used address
        params = {'addr': 0}
        dev = qdevice('devI1', params, parent_bus={'type': 'pci'})
        exp = None
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Added bad device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        # Out of range address
        params = {'addr': '0xffff'}
        dev = qdevice('devI2', params, parent_bus={'type': 'pci'})
        exp = False
        out = bus.insert(dev, False, False)
        self.assertEqual(out, exp, "Added bad device; %s != %s\n%s\n\n%s"
                         % (out, exp, dev.str_long(), bus.str_long()))

        # Compare short repr
        exp = ("pci.0(pci): [a'dev1',None,None,None,None,None,None,None,None,"
               "None,a'dev2',None,None,None,None,None,None,None,None,None,"
               "None,None,None,None,None,None,None,None,None,None,None,"
               "a'dev3']  {}")
        out = str(bus.str_short())
        self.assertEqual(out, exp, "Short representation corrupted:\n%s\n%s"
                         "\n\n%s" % (out, exp, bus.str_long()))

        # Forced records
        # Used address
        params = {'addr': '0x0'}
        dev = qdevice('devB1', params, parent_bus={'type': 'pci'})
        exp = "(errors: UsedSlot)"
        out = bus.insert(dev, False, True)
        self.assertEqual(exp in out, True, "%s not in %s\n%s\n\n%s"
                         % (exp, out, dev.str_long(), bus.str_long()))

        # Out of range address
        params = {'addr': '0xffff'}
        dev = qdevice('devB2', params, parent_bus={'type': 'pci'})
        exp = "(errors: BadAddr([65535]))"
        out = bus.insert(dev, False, True)
        self.assertEqual(exp in out, True, "%s not in %s\n%s\n\n%s"
                         % (exp, out, dev.str_long(), bus.str_long()))

        # Incorrect bus name
        params = {'bus': 'other_bus'}
        dev = qdevice('devB3', params, parent_bus={'type': 'pci'})
        exp = "(errors: BusId)"
        out = bus.insert(dev, False, True)
        self.assertEqual(exp in out, True, "%s not in %s\n%s\n\n%s"
                         % (exp, out, dev.str_long(), bus.str_long()))

        # Compare short repr
        exp = ("pci.0(pci): [a'dev1',a'devB3',None,None,None,None,None,None,"
               "None,None,a'dev2',None,None,None,None,None,None,None,None,"
               "None,None,None,None,None,None,None,None,None,None,None,None,"
               "a'dev3']  {0x0(2x):a'devB1',o0xffff:a'devB2'}")
        out = str(bus.str_short())
        self.assertEqual(out, exp, "Short representation corrupted:\n%s\n%s"
                         "\n\n%s" % (out, exp, bus.str_long()))

    def test_q_pci_bus_strict(self):
        """ PCI bus tests in strict_mode (enforce additional options) """
        bus = qemu_devices.QPCIBus('pci.0', 'pci', 'my_pci')
        qdevice = qemu_devices.QDevice

        params = {}
        bus.insert(qdevice('dev1', params, parent_bus={'type': 'pci'}), True)
        bus.insert(qdevice('dev2', params, parent_bus={'type': 'pci'}), True)
        bus.insert(qdevice('dev3', params, parent_bus={'type': 'pci'}), True)
        params = {'addr': '0x1f'}
        bus.insert(qdevice('dev1', params, parent_bus={'type': 'pci'}), True)
        params = {'addr': 30}
        bus.insert(qdevice('dev1', params, parent_bus={'type': 'pci'}), True)
        params = {'addr': 12}
        bus.insert(qdevice('dev1', params, parent_bus={'type': 'pci'}), True)

        # All devices will have 'addr' set as we are in the strict mode
        exp = """Bus pci.0, type=pci
Slots:
---------------<  0x0 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'pci'}
    child_bus = ()
    params:
      driver = dev1
      bus = pci.0
      addr = 0x0
---------------<  0x1 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'pci'}
    child_bus = ()
    params:
      driver = dev2
      bus = pci.0
      addr = 0x1
---------------<  0x2 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'pci'}
    child_bus = ()
    params:
      driver = dev3
      bus = pci.0
      addr = 0x2
---------------<  0x3 >---------------
  None
---------------<  0x4 >---------------
  None
---------------<  0x5 >---------------
  None
---------------<  0x6 >---------------
  None
---------------<  0x7 >---------------
  None
---------------<  0x8 >---------------
  None
---------------<  0x9 >---------------
  None
---------------<  0xa >---------------
  None
---------------<  0xb >---------------
  None
---------------<  0xc >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'pci'}
    child_bus = ()
    params:
      addr = 0xc
      driver = dev1
      bus = pci.0
---------------<  0xd >---------------
  None
---------------<  0xe >---------------
  None
---------------<  0xf >---------------
  None
---------------< 0x10 >---------------
  None
---------------< 0x11 >---------------
  None
---------------< 0x12 >---------------
  None
---------------< 0x13 >---------------
  None
---------------< 0x14 >---------------
  None
---------------< 0x15 >---------------
  None
---------------< 0x16 >---------------
  None
---------------< 0x17 >---------------
  None
---------------< 0x18 >---------------
  None
---------------< 0x19 >---------------
  None
---------------< 0x1a >---------------
  None
---------------< 0x1b >---------------
  None
---------------< 0x1c >---------------
  None
---------------< 0x1d >---------------
  None
---------------< 0x1e >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'pci'}
    child_bus = ()
    params:
      addr = 0x1e
      driver = dev1
      bus = pci.0
---------------< 0x1f >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'pci'}
    child_bus = ()
    params:
      addr = 0x1f
      driver = dev1
      bus = pci.0

"""
        out = str(bus.str_long())
        self.assertEqual(out, exp, "Long representation corrupted:\n%s\n%s"
                         % (repr(out), exp))


if __name__ == "__main__":
    unittest.main()
