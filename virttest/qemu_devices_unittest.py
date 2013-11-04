#!/usr/bin/python
"""
This is a unittest for qemu_devices library.

:author: Lukas Doktor <ldoktor@redhat.com>
:copyright: 2012 Red Hat, Inc.
"""
__author__ = """Lukas Doktor (ldoktor@redhat.com)"""

import re
import unittest
import os
import common
from autotest.client.shared.test_utils import mock
import qemu_devices
import data_dir
import qemu_monitor

UNITTEST_DATA_DIR = os.path.join(
    data_dir.get_root_dir(), "virttest", "unittest_data")

# Dummy variables
# qemu-1.5.0 human monitor help output
QEMU_HMP = open(os.path.join(UNITTEST_DATA_DIR, "qemu-1.5.0__hmp_help")).read()
# qemu-1.5.0 QMP monitor commands output
QEMU_QMP = open(os.path.join(UNITTEST_DATA_DIR, "qemu-1.5.0__qmp_help")).read()
# qemu-1.5.0 -help
QEMU_HELP = open(os.path.join(UNITTEST_DATA_DIR, "qemu-1.5.0__help")).read()
# qemu-1.5.0 -devices ?
QEMU_DEVICES = open(
    os.path.join(UNITTEST_DATA_DIR, "qemu-1.5.0__devices_help")).read()
# qemu-1.5.0 -M ?
QEMU_MACHINE = open(
    os.path.join(UNITTEST_DATA_DIR, "qemu-1.5.0__machine_help")).read()


class MockHMPMonitor(qemu_monitor.HumanMonitor):

    """ Dummy class inherited from qemu_monitor.HumanMonitor """

    def __init__(self):     # pylint: disable=W0231
        self.debug_log = False
        pass

    def __del__(self):
        pass


class Devices(unittest.TestCase):

    """ set of qemu devices tests """

    def test_q_base_device(self):
        """ QBaseDevice tests """
        qdevice = qemu_devices.QBaseDevice('MyType',
                                           {'ParamA': 'ValueA',
                                               'AUTOREMOVE': None},
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
  child_bus = []
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

        exp = "device_add ahci,addr=0x7,id=ahci1"
        out = qdevice.hotplug_hmp()
        self.assertEqual(out, exp, "HMP command corrupted:\n%s\n%s"
                         % (out, exp))

        exp = ("('device_add', OrderedDict([('addr', '0x7'), "
               "('driver', 'ahci'), ('id', 'ahci1')]))")
        out = str(qdevice.hotplug_qmp())
        self.assertEqual(out, exp, "QMP command corrupted:\n%s\n%s"
                         % (out, exp))


class Buses(unittest.TestCase):

    """ Set of bus-representation tests """

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
    child_bus = []
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
    child_bus = []
    params:
      bus = my_bus
      addr1 = 1
      driver = dev5
---------------< 1-1-1 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = []
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
    child_bus = []
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
    child_bus = []
    params:
      bus = my_bus
      driver = dev6
---------------< 0-0-0 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = []
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
    child_bus = []
    params:
      bus = my_bus
      driver = devB3
---------------< 0-0-2 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = []
    params:
      driver = dev7

---------------< o0-6-0 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'bus_type'}
    child_bus = []
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
    child_bus = []
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
    child_bus = []
    params:
      driver = dev1
      bus = pci.0
      addr = 0x0
---------------<  0x1 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'pci'}
    child_bus = []
    params:
      driver = dev2
      bus = pci.0
      addr = 0x1
---------------<  0x2 >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'pci'}
    child_bus = []
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
    child_bus = []
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
    child_bus = []
    params:
      addr = 0x1e
      driver = dev1
      bus = pci.0
---------------< 0x1f >---------------
  device
    aid = None
    aobject = None
    parent_bus = {'type': 'pci'}
    child_bus = []
    params:
      addr = 0x1f
      driver = dev1
      bus = pci.0

"""
        out = str(bus.str_long())
        self.assertEqual(out, exp, "Long representation corrupted:\n%s\n%s"
                         % (repr(out), exp))

    def test_usb_bus(self):
        """ Tests the specific handlings of QUSBBus """
        usbc1 = qemu_devices.QUSBBus(2, 'usb1.0', 'uhci')

        # Insert device into usb controller, default port
        self.assertTrue(usbc1.insert(qemu_devices.QDevice('usb-kbd',
                                                          parent_bus={'type': 'uhci'})))

        # Insert usb-hub into usb controller, default port
        dev = qemu_devices.QDevice('usb-hub', parent_bus={'type': 'uhci'})
        self.assertTrue(usbc1.insert(dev))
        hub1 = dev.child_bus[-1]

        # Insert usb-hub into usb-hub, exact port
        dev = qemu_devices.QDevice('usb-hub', {'port': '2.4'},
                                   parent_bus={'type': 'uhci'})
        self.assertTrue(hub1.insert(dev))
        hub2 = dev.child_bus[-1]

        # Insert usb-hub into usb-hub in usb-hub, exact port
        dev = qemu_devices.QDevice('usb-hub', {'port': '2.4.3'},
                                   parent_bus={'type': 'uhci'})
        self.assertTrue(hub2.insert(dev))
        hub3 = dev.child_bus[-1]
        # verify that port is updated correctly
        self.assertEqual("2.4.3", dev.get_param("port"))

        # Insert usb-device into usb-hub in usb-hub in usb-hub, exact port
        self.assertTrue(hub3.insert(qemu_devices.QDevice('usb-kbd',
                                                         {'port': '2.4.3.1'},
                                                         parent_bus={'type': 'uhci'})))
        # Insert usb-device into usb-hub in usb-hub in usb-hub, default port
        self.assertTrue(hub3.insert(qemu_devices.QDevice('usb-kbd',
                                                         parent_bus={'type': 'uhci'})))

        # Try to insert device into specific port which belongs to inferior bus
        self.assertFalse(hub2.insert(qemu_devices.QDevice('usb-kbd',
                                                          {'port': '2.4.3.3'},
                                                          parent_bus={'type': 'uhci'})))

        # Try to insert device into specific port which belongs to superior bus
        self.assertFalse(hub2.insert(qemu_devices.QDevice('usb-kbd',
                                                          {'port': '2.4'},
                                                          parent_bus={'type': 'uhci'})))

        # Try to insert device into specific port which belongs to same level
        # but different port
        self.assertFalse(hub2.insert(qemu_devices.QDevice('usb-kbd',
                                                          {'port': '2.3.4'},
                                                          parent_bus={'type': 'uhci'})))

        # Force insert device with port which belongs to other hub
        dev = qemu_devices.QDevice('usb-hub', {'port': '2.4.3.4'},
                                   parent_bus={'type': 'uhci'})
        out = hub2.insert(dev, force=True)
        res = bool("BusId" in out and "BasicAddress" in out)
        self.assertTrue(res, "Incorrect output of force insert:\n%s\nOutput"
                        "have to contain BusId and BasicAddress (err)" % (out))
        # verify that port is updated correctly
        self.assertEqual("2.4.1", dev.get_param("port"))

        # Check the overall buses correctness
        self.assertEqual("usb1.0(uhci): {1:a'usb-kbd',2:a'usb-hub'}  {}",
                         usbc1.str_short())
        self.assertEqual("usb1.0(uhci): {4:a'usb-hub'}  {}",
                         hub1.str_short())
        self.assertEqual("usb1.0(uhci): {1:a'usb-hub',3:a'usb-hub'}  {}",
                         hub2.str_short())
        self.assertEqual("usb1.0(uhci): {1:a'usb-kbd',2:a'usb-kbd'}  {}",
                         hub3.str_short())


class Container(unittest.TestCase):

    """ Tests related to the abstract representation of qemu machine """

    def setUp(self):
        self.god = mock.mock_god(ut=self)
        self.god.stub_function(qemu_devices.utils, "system_output")

    def tearDown(self):
        self.god.unstub_all()

    def create_qdev(self, vm_name='vm1', strict_mode="no",
                    allow_hotplugged_vm="yes"):
        """ :return: Initialized qemu_devices.DevContainer object """
        qemu_cmd = '/usr/bin/qemu_kvm'
        qemu_devices.utils.system_output.expect_call('%s -help' % qemu_cmd,
                                                     timeout=10, ignore_status=True
                                                     ).and_return(QEMU_HELP)
        qemu_devices.utils.system_output.expect_call("%s -device ? 2>&1"
                                                     % qemu_cmd, timeout=10,
                                                     ignore_status=True
                                                     ).and_return(QEMU_DEVICES)
        qemu_devices.utils.system_output.expect_call("%s -M ?" % qemu_cmd,
                                                     timeout=10, ignore_status=True
                                                     ).and_return(QEMU_MACHINE)
        cmd = "echo -e 'help\nquit' | %s -monitor stdio -vnc none" % qemu_cmd
        qemu_devices.utils.system_output.expect_call(cmd, timeout=10,
                                                     ignore_status=True
                                                     ).and_return(QEMU_HMP)
        cmd = ('echo -e \'{ "execute": "qmp_capabilities" }\n'
               '{ "execute": "query-commands", "id": "RAND91" }\n'
               '{ "execute": "quit" }\''
               '| %s -qmp stdio -vnc none | grep return |'
               ' grep RAND91' % qemu_cmd)
        qemu_devices.utils.system_output.expect_call(cmd, timeout=10,
                                                     ignore_status=True
                                                     ).and_return('')

        cmd = ('echo -e \'{ "execute": "qmp_capabilities" }\n'
               '{ "execute": "query-commands", "id": "RAND91" }\n'
               '{ "execute": "quit" }\' | (sleep 1; cat )'
               '| %s -qmp stdio -vnc none | grep return |'
               ' grep RAND91' % qemu_cmd)
        qemu_devices.utils.system_output.expect_call(cmd, timeout=10,
                                                     ignore_status=True
                                                     ).and_return(QEMU_QMP)

        qdev = qemu_devices.DevContainer(qemu_cmd, vm_name, strict_mode, 'no',
                                         allow_hotplugged_vm)

        self.god.check_playback()
        return qdev

    def test_qdev_functional(self):
        """ Test basic qdev workflow """
        qdev = self.create_qdev('vm1')

        # Add basic 'pc' devices
        for dev in qdev.machine_by_params({'machine_type': 'pc'}):
            out = qdev.insert(dev, False)
            self.assertEqual(out, None, "Failed to insert device, ret=%s\n%s"
                             % (out, qdev.str_long()))

        exp = r"""Devices of vm1:
machine
  aid = __0
  aobject = None
  parent_bus = \(\)
  child_bus = \[.*QPCIBus.*\]
  params:
i440FX
  aid = __1
  aobject = None
  parent_bus = \({'type': 'pci'},\)
  child_bus = \[\]
  params:
    addr = 0x0
PIIX3
  aid = __2
  aobject = None
  parent_bus = \({'type': 'pci'},\)
  child_bus = \[\]
  params:
    addr = 0x1"""
        out = qdev.str_long()
        self.assertNotEqual(re.match(exp, out), None, 'Long representation is'
                            'corrupted:\n%s\n%s' % (out, exp))

        exp = ("Buses of vm1\n"
               "  floppy(floppy): [None,None]  {}\n"
               "  ide(ide): [None,None,None,None]  {}\n"
               "  pci.0(pci): [t'i440FX',t'PIIX3'%s]  {}"
               % (',None' * 30))
        out = qdev.str_bus_short()
        assert out == exp, "Bus representation is ocrrupted:\n%s\n%s" % (out,
                                                                         exp)

        # Insert some good devices
        qdevice = qemu_devices.QDevice

        # Device with child bus
        bus = qemu_devices.QSparseBus('bus', [['addr'], [6]], 'hba1.0', 'hba',
                                      'a_hba')
        dev = qdevice('HBA', {'id': 'hba1', 'addr': 10},
                      parent_bus={'type': 'pci'}, child_bus=bus)
        out = qdev.insert(dev, False)
        self.assertEqual(out, None, "Failed to insert device, ret=%s\n%s"
                         % (out, qdev.str_long()))

        # Device inside a child bus by type (most common)
        dev = qdevice('dev', {}, parent_bus={'type': 'hba'})
        out = qdev.insert(dev, False)
        self.assertEqual(out, None, "Failed to insert device, ret=%s\n%s"
                         % (out, qdev.str_long()))

        # Device inside a child bus by autotest_id
        dev = qdevice('dev', {}, 'autotest_remove', {'aobject': 'a_hba'})
        out = qdev.insert(dev, False)
        self.assertEqual(out, None, "Failed to insert device, ret=%s\n%s"
                         % (out, qdev.str_long()))

        # Device inside a child bus by busid
        dev = qdevice('dev', {}, 'autoremove', {'busid': 'hba1.0'})
        out = qdev.insert(dev, False)
        self.assertEqual(out, None, "Failed to insert device, ret=%s\n%s"
                         % (out, qdev.str_long()))

        # Check the representation
        exp = ("Devices of vm1: [t'machine',t'i440FX',t'PIIX3',t'ide',t'fdc',"
               "hba1,a'dev',a'dev',a'dev']")
        out = qdev.str_short()
        self.assertEqual(out, exp, "Short representation is corrupted:\n%s\n%s"
                         % (out, exp))
        exp = ("Buses of vm1\n"
               "  hba1.0(hba): {0:a'dev',1:a'dev',2:a'dev'}  {}\n"
               "  floppy(floppy): [None,None]  {}\n"
               "  ide(ide): [None,None,None,None]  {}\n"
               "  pci.0(pci): [t'i440FX',t'PIIX3',None,None,None,None,None,"
               "None,None,None,hba1,None,None,None,None,None,None,None,None,"
               "None,None,None,None,None,None,None,None,None,None,None,None,"
               "None]  {}")
        out = qdev.str_bus_short()
        assert out == exp, 'Bus representation iscorrupted:\n%s\n%s' % (out,
                                                                        exp)

        # Force insert bad devices: No matching bus
        dev = qdevice('baddev', {}, 'badbus', {'type': 'missing_bus'})
        self.assertRaises(qemu_devices.DeviceInsertError, qdev.insert, dev,
                          False)
        out = qdev.insert(dev, True)
        self.assertEqual("No matching bus" in out, True, "Incorrect output of "
                         "force insertion of the bad dev, ret=%s\n%s"
                         % (out, qdev.str_long()))

        # Force insert bad devices: Incorrect addr
        dev = qdevice('baddev', {'addr': 'bad_value'}, 'badaddr',
                      {'type': 'pci'})
        self.assertRaises(qemu_devices.DeviceInsertError, qdev.insert, dev,
                          False)
        out = qdev.insert(dev, True)
        self.assertEqual("errors: BasicAddress" in out, True, "Incorrect "
                         "output of force insertion of the bad dev, ret=%s\n%s"
                         % (out, qdev.str_long()))

        # Force insert bad devices: Duplicite qid
        dev = qdevice('baddev', {'id': 'hba1'}, 'badid')
        self.assertRaises(qemu_devices.DeviceInsertError, qdev.insert, dev,
                          False)
        out = qdev.insert(dev, True)
        self.assertEqual("Devices qid hba1 already used in VM" in out, True,
                         "Incorrect output of force insertion of the bad dev, "
                         "ret=%s\n%s" % (out, qdev.str_long()))

        # Check the representation
        exp = ("Devices of vm1: [t'machine',t'i440FX',t'PIIX3',t'ide',t'fdc',"
               "hba1,a'dev',a'dev',a'dev',a'baddev',a'baddev',hba1__0]")
        out = qdev.str_short()
        assert out == exp, "Short representation is corrupted:\n%s\n%s" % (out,
                                                                           exp)
        exp = ("Buses of vm1\n"
               "  hba1.0(hba): {0:a'dev',1:a'dev',2:a'dev'}  {}\n"
               "  floppy(floppy): [None,None]  {}\n"
               "  ide(ide): [None,None,None,None]  {}\n"
               "  pci.0(pci): [t'i440FX',t'PIIX3',a'baddev',None,None,None,"
               "None,None,None,None,hba1,None,None,None,None,None,None,None,"
               "None,None,None,None,None,None,None,None,None,None,None,None,"
               "None,None]  {}")
        out = qdev.str_bus_short()
        assert out == exp, 'Bus representation is corrupted:\n%s\n%s' % (out,
                                                                         exp)

        # Now representation contains some devices, play with it a bit
        # length
        out = len(qdev)
        assert out == 12, "Length of qdev is incorrect: %s != %s" % (out, 10)

        # compare
        qdev2 = self.create_qdev('vm1')
        self.assertNotEqual(qdev, qdev2, "This qdev matches empty one:"
                            "\n%s\n%s" % (qdev, qdev2))
        self.assertNotEqual(qdev2, qdev, "Empty qdev matches current one:"
                            "\n%s\n%s" % (qdev, qdev2))
        for _ in xrange(10):
            qdev2.insert(qdevice())
        self.assertNotEqual(qdev, qdev2, "This qdev matches different one:"
                            "\n%s\n%s" % (qdev, qdev2))
        self.assertNotEqual(qdev2, qdev, "Other qdev matches this one:\n%s\n%s"
                            % (qdev, qdev2))

        # cmdline
        exp = ("-M pc -device HBA,id=hba1,addr=0xa -device dev -device dev "
               "-device dev -device baddev -device baddev,addr=0x2,bus=pci.0 "
               "-device baddev,id=hba1")
        out = qdev.cmdline()
        self.assertEqual(out, exp, 'Corrupted qdev.cmdline() output:\n%s\n%s'
                         % (out, exp))

        # get_by_qid (currently we have 2 devices of the same qid)
        out = qdev.get_by_qid('hba1')
        self.assertEqual(len(out), 2, 'Incorrect number of devices by qid '
                         '"hba1": %s != 2\n%s' % (len(out), qdev.str_long()))

        # Remove some devices
        # Remove based on aid
        out = qdev.remove('hba1__0')
        self.assertEqual(out, None, 'Failed to remove device:\n%s\nRepr:\n%s'
                         % ('hba1__0', qdev.str_long()))

        # Remove device which contains other devices (without recursive)
        self.assertRaises(qemu_devices.DeviceRemoveError, qdev.remove, 'hba1',
                          False)

        # Remove device which contains other devices (recursive)
        out = qdev.remove('hba1')
        self.assertEqual(out, None, 'Failed to remove device:\n%s\nRepr:\n%s'
                         % ('hba1', qdev.str_long()))

        # Check the representation
        exp = ("Devices of vm1: [t'machine',t'i440FX',t'PIIX3',t'ide',t'fdc',"
               "a'baddev',a'baddev']")
        out = qdev.str_short()
        assert out == exp, "Short representation is corrupted:\n%s\n%s" % (out,
                                                                           exp)
        exp = ("Buses of vm1\n"
               "  floppy(floppy): [None,None]  {}\n"
               "  ide(ide): [None,None,None,None]  {}\n"
               "  pci.0(pci): [t'i440FX',t'PIIX3',a'baddev',None,None,None,"
               "None,None,None,None,None,None,None,None,None,None,None,None,"
               "None,None,None,None,None,None,None,None,None,None,None,None,"
               "None,None]  {}")
        out = qdev.str_bus_short()
        assert out == exp, 'Bus representation is corrupted:\n%s\n%s' % (out,
                                                                         exp)

    def test_qdev_hotplug(self):
        """ Test the hotplug/unplug functionality """
        qdev = self.create_qdev('vm1', False, True)
        devs = qdev.machine_by_params({'machine_type': 'pc'})
        for dev in devs:
            qdev.insert(dev)
        monitor = MockHMPMonitor()

        out = qdev.get_state()
        assert out == -1, ("Status after init is not -1"
                           " (%s)" % out)
        out = len(qdev)
        assert out == 5, "Number of devices of this VM is not 5 (%s)" % out

        dev1, dev2 = qdev.images_define_by_variables('disk', '/tmp/a',
                                                     fmt="virtio")

        out = dev1.hotplug_hmp()
        exp = "drive_add auto id=drive_disk,if=none,file=/tmp/a"
        assert out == exp, ("Hotplug command of drive is incorrect:\n%s\n%s"
                            % (exp, out))

        # hotplug of drive will return "  OK" (pass)
        dev1.hotplug = lambda _monitor: "OK"
        dev1.verify_hotplug = lambda _out, _monitor: True
        out, ver_out = qdev.simple_hotplug(dev1, monitor, True)
        assert out == "OK", "Return value of hotplug is not OK (%s)" % out
        assert ver_out is True, ("Return value of hotplug"
                                 " is not True (%s)" % ver_out)
        out = qdev.get_state()
        assert out == 0, ("Status after verified hotplug is not 0 (%s)" % out)

        # hotplug of virtio-blk-pci will return ""
        out = dev2.hotplug_hmp()
        exp = "device_add virtio-blk-pci,id=disk,drive=drive_disk"
        assert out == exp, ("Hotplug command of device is incorrect:\n%s\n%s"
                            % (exp, out))
        dev2.hotplug = lambda _monitor: ""
        dev2.verify_hotplug = lambda _out, _monitor: ""
        out, ver_out = qdev.simple_hotplug(dev2, monitor, True)
        # automatic verification is not supported, hotplug returns the original
        # monitor message ("")
        assert ver_out == "", ("Return value of hotplug is"
                               " not "" (%s)" % ver_out)
        assert out == "", 'Return value of hotplug is not "" (%s)' % out
        out = qdev.get_state()
        assert out == 1, ("Status after verified hotplug is not 1 (%s)" % out)
        qdev.hotplug_verified()
        out = qdev.get_state()
        assert out == 0, ("Status after verified hotplug is not 0 (%s)" % out)

        out = len(qdev)
        assert out == 7, "Number of devices of this VM is not 7 (%s)" % out

        # Hotplug is expected to pass but monitor reports failure
        dev3 = qemu_devices.QDrive('a_dev1')
        dev3.hotplug = lambda _monitor: ("could not open disk image /tmp/qqq: "
                                         "No such file or directory")

        out, ver_out = qdev.simple_hotplug(dev3, monitor, True)
        exp = "could not open disk image /tmp/qqq: No such file or directory"
        assert out, "Return value of hotplug is incorrect:\n%s\n%s" % (out,
                                                                       exp)
        qdev.remove(dev3, recursive=False)
        out = qdev.get_state()
        assert out == 1, ("Status after verified hotplug is not 1 (%s)" % out)
        qdev.hotplug_verified()

        # Hotplug is expected to fail, qdev should stay unaffected
        self.assertRaises(qemu_devices.DeviceHotplugError, qdev.simple_hotplug,
                          dev2, True)
        out = qdev.get_state()
        assert out == 0, "Status after impossible hotplug is not 0 (%s)" % out

        # Unplug
        # Unplug used drive (automatic verification not supported)
        out = dev1.unplug_hmp()
        exp = "drive_del drive_disk"
        assert out == exp, ("Hotplug command of device is incorrect:\n%s\n%s"
                            % (exp, out))
        dev1.unplug = lambda _monitor: ""
        dev1.verify_unplug = lambda _monitor, _out: ""
        out, ver_out = qdev.simple_unplug(dev1, monitor)
        # I verified, that device was unplugged successfully
        qdev.hotplug_verified()
        out = qdev.get_state()
        assert out == 0, ("Status after verified hotplug is not 0 (%s)" % out)
        out = len(qdev)
        assert out == 6, "Number of devices of this VM is not 6 (%s)" % out
        # Removal of drive shoould also set drive of the disk device to None
        out = dev2.get_param('drive')
        assert out is None, "Drive was not removed from disk device"

    # pylint: disable=W0212
    def test_qdev_low_level(self):
        """ Test low level functions """
        qdev = self.create_qdev('vm1')

        # Representation state (used for hotplug or other nasty things)
        out = qdev.get_state()
        assert out == -1, "qdev state is incorrect %s != %s" % (out, 1)

        qdev.set_dirty()
        out = qdev.get_state()
        self.assertEqual(out, 1, "qdev state is incorrect %s != %s" % (out, 1))

        qdev.set_dirty()
        out = qdev.get_state()
        self.assertEqual(out, 2, "qdev state is incorrect %s != %s" % (out, 1))

        qdev.set_clean()
        out = qdev.get_state()
        self.assertEqual(out, 1, "qdev state is incorrect %s != %s" % (out, 1))

        qdev.set_clean()
        out = qdev.get_state()
        self.assertEqual(out, 0, "qdev state is incorrect %s != %s" % (out, 1))

        qdev.reset_state()
        out = qdev.get_state()
        assert out == -1, "qdev state is incorrect %s != %s" % (out, 1)

        # __create_unique_aid
        dev = qemu_devices.QDevice()
        qdev.insert(dev)
        out = dev.get_aid()
        self.assertEqual(out, '__0', "incorrect aid %s != %s" % (out, '__0'))

        dev = qemu_devices.QDevice(None, {'id': 'qid'})
        qdev.insert(dev)
        out = dev.get_aid()
        self.assertEqual(out, 'qid', "incorrect aid %s != %s" % (out, 'qid'))

        dev = qemu_devices.QDevice(None, {'id': 'qid'})
        qdev.insert(dev, True)
        out = dev.get_aid()
        self.assertEqual(out, 'qid__0', "incorrect aid %s != %s"
                         % (out, 'qid__0'))

        dev = qemu_devices.QDevice(None, {'id': 'qid__1'})
        qdev.insert(dev, True)
        out = dev.get_aid()
        self.assertEqual(out, 'qid__1', "incorrect aid %s != %s"
                         % (out, 'qid__1'))

        dev = qemu_devices.QDevice(None, {'id': 'qid'})
        qdev.insert(dev, True)
        out = dev.get_aid()
        self.assertEqual(out, 'qid__2', "incorrect aid %s != %s"
                         % (out, 'qid__2'))

        # has_option
        out = qdev.has_option('device')
        self.assertEqual(out, True)

        out = qdev.has_option('missing_option')
        self.assertEqual(out, False)

        # has_device
        out = qdev.has_device('ide-drive')
        self.assertEqual(out, True)

        out = qdev.has_device('missing_device')
        self.assertEqual(out, False)

        # get_help_text
        out = qdev.get_help_text()
        self.assertEqual(out, QEMU_HELP)

        # has_hmp_cmd
        self.assertTrue(qdev.has_hmp_cmd('pcie_aer_inject_error'))
        self.assertTrue(qdev.has_hmp_cmd('c'))
        self.assertTrue(qdev.has_hmp_cmd('cont'))
        self.assertFalse(qdev.has_hmp_cmd('off'))
        self.assertFalse(qdev.has_hmp_cmd('\ndump-guest-memory'))
        self.assertFalse(qdev.has_hmp_cmd('The'))

        # has_qmp_cmd
        self.assertTrue(qdev.has_qmp_cmd('device_add'))
        self.assertFalse(qdev.has_qmp_cmd('RAND91'))

        # Add some buses
        bus1 = qemu_devices.QPCIBus('pci.0', 'pci', 'a_pci0')
        qdev.insert(qemu_devices.QDevice(params={'id': 'pci0'},
                                         child_bus=bus1))
        bus2 = qemu_devices.QPCIBus('pci.1', 'pci', 'a_pci1')
        qdev.insert(qemu_devices.QDevice(child_bus=bus2))
        bus3 = qemu_devices.QPCIBus('pci.2', 'pci', 'a_pci2')
        qdev.insert(qemu_devices.QDevice(child_bus=bus3))
        bus4 = qemu_devices.QPCIBus('pcie.0', 'pcie', 'a_pcie0')
        qdev.insert(qemu_devices.QDevice(child_bus=bus4))

        # get_buses (all buses of this type)
        out = qdev.get_buses({'type': 'pci'})
        self.assertEqual(len(out), 3, 'get_buses should return 3 buses but '
                         'returned %s instead:\n%s' % (len(out), out))

        # get_first_free_bus (last added bus of this type)
        out = qdev.get_first_free_bus({'type': 'pci'}, [None])
        self.assertEqual(bus3, out)

        # fill the first pci bus
        for _ in xrange(32):
            qdev.insert(qemu_devices.QDevice(parent_bus={'type': 'pci'}))

        # get_first_free_bus (last one is full, return the previous one)
        out = qdev.get_first_free_bus({'type': 'pci'}, [None])
        self.assertEqual(bus2, out)

        # list_named_buses
        out = qdev.list_missing_named_buses('pci.', 'pci', 5)
        self.assertEqual(len(out), 2, 'Number of missing named buses is '
                         'incorrect: %s != %s\n%s' % (len(out), 2, out))
        out = qdev.list_missing_named_buses('pci.', 'abc', 5)
        self.assertEqual(len(out), 5, 'Number of missing named buses is '
                         'incorrect: %s != %s\n%s' % (len(out), 2, out))

        # idx_of_next_named_bus
        out = qdev.idx_of_next_named_bus('pci.')
        self.assertEqual(out, 3, 'Incorrect idx of next named bus: %s !='
                         ' %s' % (out, 3))

        # get_children
        dev = qemu_devices.QDevice(parent_bus={'aobject': 'a_pci0'})
        bus = qemu_devices.QPCIBus('test1', 'test', 'a_test1')
        dev.add_child_bus(bus)
        bus = qemu_devices.QPCIBus('test2', 'test', 'a_test2')
        dev.add_child_bus(bus)
        qdev.insert(dev)
        qdev.insert(qemu_devices.QDevice(parent_bus={'aobject': 'a_test1'}))
        qdev.insert(qemu_devices.QDevice(parent_bus={'aobject': 'a_test2'}))
        out = dev.get_children()
        assert len(out) == 2, ("Not all children were listed %d != 2:\n%s"
                               % (len(out), out))

        out = bus.get_device()
        assert out == dev, ("bus.get_device() returned different device "
                            "than the one in which it was plugged:\n"
                            "%s\n%s\n%s" % (out.str_long(), dev.str_long(),
                                            qdev.str_long()))
    # pylint: enable=W0212

    def test_qdev_equal(self):
        qdev1 = self.create_qdev('vm1', allow_hotplugged_vm='no')
        qdev2 = self.create_qdev('vm1', allow_hotplugged_vm='no')
        qdev3 = self.create_qdev('vm1', allow_hotplugged_vm='yes')
        monitor = MockHMPMonitor()

        assert qdev1 == qdev2, ("Init qdevs are not alike\n%s\n%s"
                                % (qdev1.str_long(), qdev2.str_long()))

        # Insert a device to qdev1
        dev = qemu_devices.QDevice('dev1', {'id': 'dev1'})
        qdev1.insert(dev)

        assert qdev1 != qdev2, ("Different qdevs match:\n%s\n%s"
                                % (qdev1.str_long(), qdev2.str_long()))

        # Insert similar device to qdev2
        dev = qemu_devices.QDevice('dev1', {'id': 'dev1'})
        qdev2.insert(dev)

        assert qdev1 == qdev2, ("Similar qdevs are not alike\n%s\n%s"
                                % (qdev1.str_long(), qdev2.str_long()))

        # Hotplug similar device to qdev3
        dev = qemu_devices.QDevice('dev1', {'id': 'dev1'})
        dev.hotplug = lambda _monitor: ""   # override the hotplug method
        dev.verify_hotplug = lambda _out, _monitor: True
        qdev3.simple_hotplug(dev, monitor, False)
        assert qdev1 == qdev3, ("Similar hotplugged qdevs are not alike\n%s\n"
                                "%s" % (qdev1.str_long(), qdev3.str_long()))

        # Eq. is not symmetrical, qdev1 doesn't allow hotplugged VMs.
        assert qdev3 != qdev1, ("Similar hotplugged qdevs match even thought "
                                "qdev1 doesn't allow hotplugged VM\n%s\n%s"
                                % (qdev1.str_long(), qdev3.str_long()))

        qdev2.__qemu_help = "I support only this :-)"  # pylint: disable=W0212
        assert qdev1 == qdev2, ("qdevs of different qemu versions match:\n%s\n"
                                "%s" % (qdev1.str_long(), qdev2.str_long()))


if __name__ == "__main__":
    unittest.main()
