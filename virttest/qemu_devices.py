"""
Library of objects, which could represent qemu devices in order to create
complete representation of VM. There are three parts:
1) Device objects - individual devices representation
2) Bus representation - bus representation
3) Device container - qemu machine representation

@copyright: 2012-2013 Red Hat Inc.
"""
# Python imports
import itertools
import logging
import re
# Autotest imports
from autotest.client.shared import error, utils
import arch
import qemu_monitor


try:
    from collections import OrderedDict
except ImportError:
    class OrderedDict(dict):
        """
        Dictionary which keeps the order of items when using .itervalues()
        @warning: This is not the full OrderedDict implementation!
        """
        def itervalues(self, *args, **kwargs):
            return (_[1] for _ in sorted(dict.iteritems(self, *args, **kwargs)))

        def iteritems(self, *args, **kwargs):
            return sorted(dict.iteritems(self, *args, **kwargs),
                          key=lambda item: item[0])


class DeviceError(Exception):
    """ General device exception """
    pass


class DeviceInsertError(DeviceError):
    """ Fail to insert device """
    def __init__(self, device, reason, vmdev):
        self.device = device
        self.reason = reason
        self.vmdev = vmdev

    def __str__(self):
        return ("Failed to insert device:\n%s\nBecause:\n%s\nList of VM"
                "devices:\n%s\n%s" % (self.device.str_long(), self.reason,
                                      self.vmdev, self.vmdev.str_bus_long()))


def _convert_args(arg_dict):
    """
    Convert monitor command arguments dict into humanmonitor string.

    @param arg_dict: The dict of monitor command arguments.
    @return: A string in humanmonitor's 'key=value' format, or a empty
             '' when the dict is empty.
    """
    return ",".join("%s=%s" % (key, val) for key, val in arg_dict.iteritems())


##############################################################################
# Device objects
##############################################################################
class QBaseDevice(object):
    """ Base class of qemu objects """
    def __init__(self, dev_type="QBaseDevice", params=None, aobject=None,
                 parent_bus=None, child_bus=None):
        """
        @param dev_type: type of this component
        @param params: component's parameters
        @param aobject: Autotest object which is associated with this device
        @param parent_bus: list of dicts specifying the parent bus
        @param child_bus: list of buses, which this device provides
        """
        self.aid = None         # unique per VM id
        self.type = dev_type    # device type
        self.aobject = aobject  # related autotest object
        if parent_bus is None:
            parent_bus = tuple()
        self.parent_bus = parent_bus   # list of buses into which this dev fits
        if child_bus is None:
            child_bus = tuple()
        self.child_bus = child_bus     # list of buses which this dev provides
        self.params = OrderedDict()    # various device params (id, name, ...)
        if params:
            for key, value in params.iteritems():
                self.set_param(key, value)

    def set_param(self, option, value, option_type=None):
        """
        Set device param using qemu notation ("on", "off" instead of bool...)
        @param option: which option's value to set
        @param value: new value
        @param option_type: type of the option (bool)
        """
        if option_type is bool or isinstance(value, bool):
            if value in ['yes', 'on', True]:
                self.params[option] = "on"
            elif value in ['no', 'off', False]:
                self.params[option] = "off"
        elif value or value == 0:
            if value == "EMPTY_STRING":
                self.params[option] = '""'
            else:
                self.params[option] = value
        elif value is None and option in self.params:
            del(self.params[option])

    def get_param(self, option):
        """ @return: object param """
        return self.params.get(option)

    def __getitem__(self, option):
        """ @return: object param """
        return self.params[option]

    def __delitem__(self, option):
        """ deletes self.params[option] """
        del(self.params[option])

    def __len__(self):
        """ length of self.params """
        return len(self.params)

    def __setitem__(self, option, value):
        """ self.set_param(option, value, None) """
        return self.set_param(option, value)

    def __contains__(self, option):
        """ Is the option set? """
        return option in self.params

    def __str__(self):
        """ @return: Short string representation of this object. """
        return self.str_short()

    def __eq__(self, dev2):
        """ @return: True when devs are similar, False when different. """
        try:
            for check_attr in ('cmdline', 'hotplug_hmp',
                               'hotplug_qmp'):
                try:
                    _ = getattr(self, check_attr)()
                except (DeviceError, NotImplementedError, AttributeError):
                    try:
                        getattr(dev2, check_attr)()
                    except (DeviceError, NotImplementedError, AttributeError):
                        pass
                else:
                    if _ != getattr(dev2, check_attr)():
                        return False
        except Exception:
            return False
        return True

    def __ne__(self, dev2):
        """ @return: True when devs are different, False when similar. """
        return not self.__eq__(dev2)

    def str_short(self):
        """ Short representation (aid, qid, alternative, type) """
        if self.get_qid():  # Show aid only when it's based on qid
            if self.get_aid():
                return self.get_aid()
            else:
                return "q'%s'" % self.get_qid()
        elif self._get_alternative_name():
            return "a'%s'" % self._get_alternative_name()
        else:
            return "t'%s'" % self.type

    def str_long(self):
        """ Full representation, multi-line with all params """
        out = """%s
  aid = %s
  aobject = %s
  parent_bus = %s
  child_bus = %s
  params:""" % (self.type, self.aid, self.aobject, self.parent_bus,
                self.child_bus)
        for key, value in self.params.iteritems():
            out += "\n    %s = %s" % (key, value)
        return out + '\n'

    def _get_alternative_name(self):
        """ @return: alternative object name """
        return None

    def get_qid(self):
        """ @return: qemu_id """
        return self.params.get('id', '')

    def get_aid(self):
        """ @return: per VM unique autotest_id """
        return self.aid

    def set_aid(self, aid):
        """@param aid: new autotest id for this device"""
        self.aid = aid

    def cmdline(self):
        """ @return: cmdline command to define this device """
        raise NotImplementedError

    def hotplug(self, monitor):
        """ @return: the output of monitor.cmd() hotplug command """
        if isinstance(monitor, qemu_monitor.QMPMonitor):
            try:
                cmd, args = self.hotplug_qmp()
                return monitor.cmd(cmd, args)
            except DeviceError:     # qmp command not supported
                return monitor.human_monitor_cmd(self.hotplug_hmp())
        elif isinstance(monitor, qemu_monitor.HumanMonitor):
            return monitor.cmd(self.hotplug_hmp())
        else:
            raise TypeError("Invalid monitor object: %s(%s)" % (monitor,
                                                                type(monitor)))

    def hotplug_hmp(self):
        """ @return: the hotplug monitor command """
        raise DeviceError("Hotplug is not supported by this device %s", self)

    def hotplug_qmp(self):
        """ @return: tuple(hotplug qemu command, arguments)"""
        raise DeviceError("Hotplug is not supported by this device %s", self)

    def verify_hotplug(self, out, monitor):
        """
        @param out: Output of the hotplug command
        @param monitor: Monitor used for hotplug
        @return: True when successful, False when unsuccessful, string/None
                 when can't decide.
        """
        return out


class QStringDevice(QBaseDevice):
    """
    General device which allows to specify methods by fixed or parametrizable
    strings in this format:
      "%(type)s,id=%(id)s,addr=%(addr)s" -- params will be used to subst %()s
    """
    def __init__(self, dev_type, params=None, aobject=None,
                 parent_bus=None, child_bus=None, cmdline=""):
        """
        @param dev_type: type of this component
        @param params: component's parameters
        @param aobject: Autotest object which is associated with this device
        @param parent_bus: bus(es), in which this device is plugged in
        @param child_bus: bus, which this device provides
        @param cmdline: cmdline string
        """
        super(QStringDevice, self).__init__(dev_type, params, aobject,
                                            parent_bus, child_bus)
        self._cmdline = cmdline

    def cmdline(self):
        """ @return: cmdline command to define this device """
        try:
            if self._cmdline:
                return self._cmdline % self.params
        except KeyError, details:
            raise KeyError("Param %s required for cmdline is not present in %s"
                           % (details, self.str_long()))


class QCustomDevice(QBaseDevice):
    """
    Representation of the '-$option $param1=$value1,$param2...' qemu object.
    This representation handles only cmdline.
    """
    def __init__(self, dev_type, params=None, aobject=None,
                 parent_bus=None, child_bus=None):
        """
        @param dev_type: The desired -$option parameter (device, chardev, ..)
        """
        super(QCustomDevice, self).__init__(dev_type, params, aobject,
                                            parent_bus, child_bus)

    def cmdline(self):
        """ @return: cmdline command to define this device """
        out = "-%s " % self.type
        for key, value in self.params.iteritems():
            if value == "NO_EQUAL_STRING":
                out += "%s," % key
        for key, value in self.params.iteritems():
            if value != "NO_EQUAL_STRING":
                out += "%s=%s," % (key, value)
        if out[-1] == ',':
            out = out[:-1]
        return out


class QDevice(QCustomDevice):
    """
    Representation of the '-device' qemu object. It supports all methods.
    @note: Use driver format in full form - 'driver' = '...' (usb-ehci, ide-hd)
    """
    def __init__(self, driver=None, params=None, aobject=None,
                 parent_bus=None, child_bus=None):
        super(QDevice, self).__init__("device", params, aobject, parent_bus,
                                      child_bus)
        if driver:
            self['driver'] = driver

    def _get_alternative_name(self):
        """ @return: alternative object name """
        if self.params.get('driver'):
            return self.params.get('driver')

    def hotplug_hmp(self):
        """ @return: the hotplug monitor command """
        return "device_add %s" % _convert_args(self.params)

    def hotplug_qmp(self):
        """ @return: the hotplug monitor command """
        return "device_add", self.params


##############################################################################
# Bus representations
# HDA, I2C, IDE, ISA, PCI, SCSI, System, uhci, ehci, ohci, xhci, ccid,
# virtio-serial-bus
##############################################################################
class QSparseBus(object):
    """
    Universal bus representation object.
    It creates an abstraction of the way how buses works in qemu. Additionaly
    it can store incorrect records (out-of-range addr, multiple devs, ...).
    Everything with bad* prefix means it concerns the bad records (badbus).
    You can insert and remove device to certain address, address ranges or let
    the bus assign first free address. The order of addr_spec does matter since
    the last item is incremented first.
    There are 3 different address representation used:
    stor_addr = stored address representation '$first-$second-...-$ZZZ'
    addr = internal address representation [$first, $second, ..., $ZZZ]
    device_addr = qemu address stored into separate device params (bus, port)
                  device{$param1:$first, $param2:$second, ..., $paramZZZ, $ZZZ}

    @note: When you insert a device, it's properties might be updated (addr,..)
    """
    def __init__(self, bus_item, addr_spec, busid, bus_type, aobject=None):
        """
        @param bus_item: Name of the parameter which specifies bus (bus)
        @param addr_spec: Bus address specification [names][lengths]
        @param busid: id of the bus (pci.0)
        @param bus_type: type of the bus (pci)
        @param aobject: Related autotest object (image1)
        """
        self.busid = busid
        self.type = bus_type
        self.aobject = aobject
        self.bus = {}                       # Normal bus records
        self.badbus = {}                    # Bad bus records
        self.bus_item = bus_item            # bus param name
        self.addr_items = addr_spec[0]      # [names][lengths]
        self.addr_lengths = addr_spec[1]

    def __str__(self):
        """ default string representation """
        return self.str_short()

    def __getitem__(self, item):
        """
        @param item: autotest id or QObject-like object
        @return: First matching object from this bus
        @raise KeyError: In case no match was found
        """
        if isinstance(item, QBaseDevice):
            if item in self.bus.itervalues():
                return item
            elif item in self.badbus.itervalues():
                return item
        elif item:
            for device in self.bus.itervalues():
                if device.get_aid() == item:
                    return device
            for device in self.badbus.itervalues():
                if device.get_aid() == item:
                    return device
        raise KeyError("Device %s is not in %s" % (item, self))

    def get(self, item):
        """
        @param item: autotest id or QObject-like object
        @return: First matching object from this bus or None
        """
        if item in self:
            return self[item]

    def __delitem__(self, item):
        """
        Remove device from bus
        @param item: autotest id or QObject-like object
        @raise KeyError: In case no match was found
        """
        self.remove(self[item])

    def __len__(self):
        """ @return: Number of devices in this bus """
        return len(self.bus) + len(self.badbus)

    def __contains__(self, item):
        """
        Is specified item in this bus?
        @param item: autotest id or QObject-like object
        @return: True - yes, False - no
        """
        if isinstance(item, QBaseDevice):
            if (item in self.bus.itervalues() or
                        item in self.badbus.itervalues()):
                return True
        elif item:
            for device in self:
                if device.get_aid() == item:
                    return True
        return False

    def __iter__(self):
        """ Iterate over all defined devices. """
        return itertools.chain(self.bus.itervalues(),
                               self.badbus.itervalues())

    def str_short(self):
        """ short string representation """
        return "%s(%s): %s  %s" % (self.busid, self.type, self._str_devices(),
                                   self._str_bad_devices())

    def _str_devices(self):
        """ short string representation of the good bus """
        out = '{'
        for addr in sorted(self.bus.keys()):
            out += "%s:" % addr
            out += "%s," % self.bus[addr]
        if out[-1] == ',':
            out = out[:-1]
        return out + '}'

    def _str_bad_devices(self):
        """ short string representation of the bad bus """
        out = '{'
        for addr in sorted(self.badbus.keys()):
            out += "%s:" % addr
            out += "%s," % self.badbus[addr]
        if out[-1] == ',':
            out = out[:-1]
        return out + '}'

    def str_long(self):
        """ long string representation """
        return "Bus %s, type=%s\nSlots:\n%s\n%s" % (self.busid, self.type,
                    self._str_devices_long(), self._str_bad_devices_long())

    def _str_devices_long(self):
        """ long string representation of devices in the good bus """
        out = ""
        for addr, dev in self.bus.iteritems():
            out += '%s< %4s >%s\n  ' % ('-' * 15, addr,
                                        '-' * 15)
            if isinstance(dev, str):
                out += '"%s"\n  ' % dev
            else:
                out += dev.str_long().replace('\n', '\n  ')
                out = out[:-3]
            out += '\n'
        return out

    def _str_bad_devices_long(self):
        """ long string representation of devices in the bad bus """
        out = ""
        for addr, dev in self.badbus.iteritems():
            out += '%s< %4s >%s\n  ' % ('-' * 15, addr,
                                        '-' * 15)
            if isinstance(dev, str):
                out += '"%s"\n  ' % dev
            else:
                out += dev.str_long().replace('\n', '\n  ')
                out = out[:-3]
            out += '\n'
        return out

    def _increment_addr(self, addr, last_addr=None):
        """
        Increment addr base of addr_pattern and last used addr
        @param addr: addr_pattern
        @param last_addr: previous address
        @return: last_addr + 1
        """
        if not last_addr:
            last_addr = [0] * len(self.addr_lengths)
        i = -1
        while True:
            if i < -len(self.addr_lengths):
                return False
            if addr[i] is not None:
                i -= 1
                continue
            last_addr[i] += 1
            if last_addr[i] < self.addr_lengths[i]:
                return last_addr
            last_addr[i] = 0
            i -= 1

    @staticmethod
    def _addr2stor(addr):
        """
        Converts internal addr to storable/hashable address
        @param addr: internal address [addr1, addr2, ...]
        @return: storable address "addr1-addr2-..."
        """
        out = ""
        for value in addr:
            if value is None:
                out += '*-'
            else:
                out += '%s-' % value
        if out:
            return out[:-1]
        else:
            return "*"

    def _dev2addr(self, device):
        """
        Parse the internal address out of the device
        @param device: QBaseDevice device
        @return: internal address  [addr1, addr2, ...]
        """
        addr = []
        for key in self.addr_items:
            value = device.get_param(key)
            if value is None:
                addr.append(None)
            else:
                addr.append(int(value))
        return addr

    def _set_first_addr(self, addr_pattern):
        """
        @param addr_pattern: Address pattern (full qualified or with Nones)
        @return: first valid address based on addr_pattern
        """
        use_reserved = True
        if addr_pattern is None:
            addr_pattern = [None] * len(self.addr_lengths)
        # set first usable addr
        last_addr = addr_pattern[:]
        if None in last_addr:  # Address is not fully specified
            use_reserved = False    # Use only free address
            for i in xrange(len(last_addr)):
                if last_addr[i] is None:
                    last_addr[i] = 0
        return last_addr, use_reserved

    def get_free_slot(self, addr_pattern):
        """
        Finds unoccupied address
        @param addr_pattern: Address pattern (full qualified or with Nones)
        @return: First free address when found, (free or reserved for this dev)
                 None when no free address is found, (all occupied)
                 False in case of incorrect address (oor)
        """
        # init
        last_addr, use_reserved = self._set_first_addr(addr_pattern)
        # Check the addr_pattern ranges
        for i in xrange(len(self.addr_lengths)):
            if last_addr[i] < 0 or last_addr[i] >= self.addr_lengths[i]:
                return False
        # Increment addr until free match is found
        while last_addr is not False:
            if self._addr2stor(last_addr) not in self.bus:
                return last_addr
            if (use_reserved and
                        self.bus[self._addr2stor(last_addr)] == "reserved"):
                return last_addr
            last_addr = self._increment_addr(addr_pattern, last_addr)
        return None     # No free matching address found

    def _check_bus(self, device):
        """
        Check, whether this device can be plugged into this bus.
        @param device: QBaseDevice device
        @return: True in case ids are correct, False when not
        """
        if (device.get_param(self.bus_item) and
                    device.get_param(self.bus_item) != self.busid):
            return False
        else:
            return True

    def _set_device_props(self, device, addr):
        """
        Set the full device address
        @param device: QBaseDevice device
        @param addr: internal address  [addr1, addr2, ...]
        """
        device.set_param(self.bus_item, self.busid)
        for i in xrange(len(self.addr_items)):
            device.set_param(self.addr_items[i], addr[i])

    def _update_device_props(self, device, addr):
        """
        Update values of previously set address items.
        @param device: QBaseDevice device
        @param addr: internal address  [addr1, addr2, ...]
        """
        if device.get_param(self.bus_item) is not None:
            device.set_param(self.bus_item, self.busid)
        for i in xrange(len(self.addr_items)):
            if device.get_param(self.addr_items[i]) is not None:
                device.set_param(self.addr_items[i], addr[i])

    def insert(self, device, strict_mode=False, force=False):
        """
        Insert device into this bus representation.
        @param device: QBaseDevice device
        @param strict_mode: Use strict mode (set optional params)
        @param force: Force insert the device even when errs occurs
        @return: True on success,
                 False when an incorrect addr/busid is set,
                 None when there is no free slot,
                 error string when force added device with errors.
        """
        err = ""
        if not self._check_bus(device):
            if force:
                err += "BusId, "
                device.set_param(self.bus_item, self.busid)
            else:
                return False
        try:
            addr_pattern = self._dev2addr(device)
        except (ValueError, LookupError):
            if force:
                err += "BasicAddress, "
                addr_pattern = [None] * len(self.addr_items)
            else:
                return False
        addr = self.get_free_slot(addr_pattern)
        if addr is None:
            if force:
                if None in addr_pattern:
                    err += "NoFreeSlot, "
                    # Use last valid address for inserting the device
                    addr = [(_ - 1) for _ in self.addr_lengths]
                    self._insert_used(device, self._addr2stor(addr))
                else:   # used slot
                    err += "UsedSlot, "
                    addr = addr_pattern  # It's fully specified addr
                    self._insert_used(device, self._addr2stor(addr))
            else:
                return None
        elif addr is False:
            if force:
                addr = addr_pattern
                err += "BadAddr(%s), " % addr
                self._insert_oor(device, self._addr2stor(addr))
            else:
                return False
        else:
            self._insert_good(device, self._addr2stor(addr))
        if strict_mode:     # Set full address in strict_mode
            self._set_device_props(device, addr)
        else:
            self._update_device_props(device, addr)
        if err:
            # Device was force added with errors
            err = ("Force adding device %s into %s (errors: %s)"
                   % (device, self, err[:-2]))
            return err
        return True

    def _insert_good(self, device, addr):
        """
        Insert device into good bus
        @param device: QBaseDevice device
        @param addr: internal address  [addr1, addr2, ...]
        """
        self.bus[addr] = device

    def _insert_oor(self, device, addr):
        """
        Insert device into bad bus as out-of-range (o)
        @param device: QBaseDevice device
        @param addr: storable address "addr1-addr2-..."
        """
        addr = "o" + addr
        if addr in self.badbus:
            i = 2
            while "%s(%dx)" % (addr, i) in self.badbus:
                i += 1
            addr = "%s(%dx)" % (addr, i)
        self.badbus[addr] = device

    def _insert_used(self, device, addr):
        """
        Insert device into bad bus because address is already used
        @param device: QBaseDevice device
        @param addr: storable address "addr1-addr2-..."
        """
        i = 2
        while "%s(%dx)" % (addr, i) in self.badbus:
            i += 1
        self.badbus["%s(%dx)" % (addr, i)] = device

    def remove(self, device):
        """
        Remove device from this bus
        @param device: QBaseDevice device
        @return: True when removed, False when the device wasn't found
        """
        if not self._remove_good(device):
            return self._remove_bad(device)
        return True

    def _remove_good(self, device):
        """
        Remove device from the good bus
        @param device: QBaseDevice device
        @return: True when removed, False when the device wasn't found
        """
        if device in self.bus.itervalues():
            remove = None
            for key, item in self.bus.iteritems():
                if item is device:
                    remove = key
                    break
            if remove:
                del(self.bus[remove])
                return True
        return False

    def _remove_bad(self, device):
        """
        Remove device from the bad bus
        @param device: QBaseDevice device
        @return: True when removed, False when the device wasn't found
        """
        if device in self.badbus.itervalues():
            remove = None
            for key, item in self.badbus.iteritems():
                if item is device:
                    remove = key
                    break
            if remove:
                del(self.badbus[remove])
                return True
        return False


class QDenseBus(QSparseBus):
    """
    Dense bus representation. The only difference from SparseBus is the output
    string format. DenseBus iterates over all addresses and show free slots
    too. SparseBus on the other hand prints always the device address.
    """
    def _str_devices_long(self):
        """ Show all addresses even when they are unused """
        out = ""
        addr_pattern = [None] * len(self.addr_items)
        addr = self._set_first_addr(addr_pattern)[0]
        while addr:
            dev = self.bus.get(self._addr2stor(addr))
            out += '%s< %4s >%s\n  ' % ('-' * 15, self._addr2stor(addr),
                                        '-' * 15)
            if hasattr(dev, 'str_long'):
                out += dev.str_long().replace('\n', '\n  ')
                out = out[:-3]
            elif isinstance(dev, str):
                out += '"%s"' % dev
            else:
                out += "%s" % dev
            out += '\n'
            addr = self._increment_addr(addr_pattern, addr)
        return out

    def _str_bad_devices_long(self):
        """ Show all addresses even when they are unused """
        out = ""
        for addr, dev in self.badbus.iteritems():
            out += '%s< %4s >%s\n  ' % ('-' * 15, addr,
                                        '-' * 15)
            if isinstance(dev, str):
                out += '"%s"\n  ' % dev
            else:
                out += dev.str_long().replace('\n', '\n  ')
                out = out[:-3]
            out += '\n'
        return out

    def _str_devices(self):
        """ Show all addresses even when they are unused, don't print addr """
        out = '['
        addr_pattern = [None] * len(self.addr_items)
        addr = self._set_first_addr(addr_pattern)[0]
        while addr:
            out += "%s," % self.bus.get(self._addr2stor(addr))
            addr = self._increment_addr(addr_pattern, addr)
        if out[-1] == ',':
            out = out[:-1]
        return out + ']'

    def _str_bad_devices(self):
        """ Show all addresses even when they are unused """
        out = '{'
        for addr in sorted(self.badbus.keys()):
            out += "%s:" % addr
            out += "%s," % self.badbus[addr]
        if out[-1] == ',':
            out = out[:-1]
        return out + '}'


class QPCIBus(QDenseBus):
    """
    PCI Bus representation (bus&addr, uses hex digits)
    """
    def __init__(self, busid, bus_type, aobject=None):
        """ bus&addr, 32 slots """
        super(QPCIBus, self).__init__('bus', [['addr'], [32]], busid, bus_type,
                                      aobject)

    @staticmethod
    def _addr2stor(addr):
        """ force all items as hexadecimal values """
        out = ""
        for value in addr:
            if value is None:
                out += '*-'
            else:
                out += '%s-' % hex(value)
        if out:
            return out[:-1]
        else:
            return "*"

    def _dev2addr(self, device):
        """ Read the values in base of 16 (hex) """
        addr = []
        for key in self.addr_items:
            value = device.get_param(key)
            if value is None:
                addr.append(None)
            elif isinstance(value, int):
                addr.append(value)
            else:
                addr.append(int(value, 16))
        return addr

    def _set_device_props(self, device, addr):
        """ Convert addr to hex """
        addr = [hex(_) for _ in addr]
        super(QPCIBus, self)._set_device_props(device, addr)

    def _update_device_props(self, device, addr):
        """ Convert addr to hex """
        addr = [hex(_) for _ in addr]
        super(QPCIBus, self)._update_device_props(device, addr)


###############################################################################
# Device container (device representation of VM)
# This class represents VM by storing all devices and their connections (buses)
###############################################################################
class DevContainer(object):
    """
    Device container class
    """
    # General methods
    def __init__(self, qemu_binary, vmname, strict_mode=False,
                 workaround_qemu_qmp_crash=False):
        """
        @param qemu_binary: qemu binary
        @param vm: related VM
        @param strict_mode: Use strict mode (set optional params)
        """
        def get_hmp_cmds(qemu_binary):
            """ @return: list of human monitor commands """
            _ = utils.system_output("echo -e 'help\nquit' | %s -monitor "
                                    "stdio -vnc none" % qemu_binary,
                                    timeout=10, ignore_status=True)
            _ = re.findall(r'^([^\| \[\n]+\|?\w+)', _, re.M)
            hmp_cmds = []
            for cmd in _:
                if '|' not in cmd:
                    if cmd != 'The':
                        hmp_cmds.append(cmd)
                else:
                    hmp_cmds.extend(cmd.split('|'))
            return hmp_cmds

        def get_qmp_cmds(qemu_binary, workaround_qemu_qmp_crash=False):
            """ @return: list of qmp commands """
            cmds = None
            if not workaround_qemu_qmp_crash:
                cmds = utils.system_output('echo -e \''
                            '{ "execute": "qmp_capabilities" }\n'
                            '{ "execute": "query-commands", "id": "RAND91" }\n'
                            '{ "execute": "quit" }\''
                            '| %s -qmp stdio -vnc none | grep return |'
                            ' grep RAND91' % qemu_binary, timeout=10,
                            ignore_status=True).splitlines()
            if not cmds:
                # Some qemu versions crashes when qmp used too early; add sleep
                cmds = utils.system_output('echo -e \''
                            '{ "execute": "qmp_capabilities" }\n'
                            '{ "execute": "query-commands", "id": "RAND91" }\n'
                            '{ "execute": "quit" }\' | (sleep 1; cat )'
                            '| %s -qmp stdio -vnc none | grep return |'
                            ' grep RAND91' % qemu_binary, timeout=10,
                            ignore_status=True).splitlines()
            if cmds:
                cmds = re.findall(r'{\s*"name"\s*:\s*"([^"]+)"\s*}', cmds[0])
            if cmds:    # If no mathes, return None
                return cmds

        self.__state = 0    # is representation sync with VM (0 = synchronized)
        self.__qemu_help = utils.system_output("%s -help" % qemu_binary,
                                timeout=10, ignore_status=True)
        self.__device_help = utils.system_output("%s -device ? 2>&1"
                                            % qemu_binary, timeout=10,
                                            ignore_status=True)
        self.__machine_types = utils.system_output("%s -M ?" % qemu_binary,
                                timeout=10, ignore_status=True)
        self.__hmp_cmds = get_hmp_cmds(qemu_binary)
        self.__qmp_cmds = get_qmp_cmds(qemu_binary, workaround_qemu_qmp_crash)
        self.vmname = vmname
        self.strict_mode = strict_mode == 'yes'
        self.__devices = []
        self.__buses = []

    def __getitem__(self, item):
        """
        @param item: autotest id or QObject-like object
        @return: First matching object defined in this QDevContainer
        @raise KeyError: In case no match was found
        """
        if isinstance(item, QBaseDevice):
            if item in self.__devices:
                return item
        elif item:
            for device in self.__devices:
                if device.get_aid() == item:
                    return device
        raise KeyError("Device %s is not in %s" % (item, self))

    def get(self, item):
        """
        @param item: autotest id or QObject-like object
        @return: First matching object defined in this QDevContainer or None
        """
        if item in self:
            return self[item]

    def __delitem__(self, item):
        """
        Delete specified item from devices list
        @param item: autotest id or QObject-like object
        @raise KeyError: In case no match was found
        """
        # Remove child_buses including devices
        if self.remove(item):
            raise KeyError(item)

    def remove(self, item):
        """
        Remove device from this representation
        @param item: autotest id or QObject-like object
        @return: None on success, -1 when the device is not present
        """
        # Remove child_buses including devices
        item = self.get(item)
        if item is None:
            return -1
        for bus in item.child_bus:
            remove = [dev for dev in bus]
            for dev in remove:
                del(self[dev])
            self.__buses.remove(bus)
        # Remove from parent_buses
        for bus in self.__buses:
            if item in bus:
                del(bus[item])
        # Remove from list of devices
        self.__devices.remove(self[item])

    def __len__(self):
        """ @return: Number of inserted devices """
        return len(self.__devices)

    def __contains__(self, item):
        """
        Is specified item defined in current devices list?
        @param item: autotest id or QObject-like object
        @return: True - yes, False - no
        """
        if isinstance(item, QBaseDevice):
            if item in self.__devices:
                return True
        elif item:
            for device in self.__devices:
                if device.get_aid() == item:
                    return True
        return False

    def __iter__(self):
        """ Iterate over all defined devices. """
        return self.__devices.__iter__()

    def __eq__(self, qdev2):
        """ Are the VM representation alike? """
        if len(qdev2) != len(self):
            return False
        for dev in self:
            if dev not in qdev2:
                return False
        return True

    def __ne__(self, qdev2):
        """ Are the VM representation different? """
        return not self.__eq__(qdev2)

    def _set_dirty(self):
        """ Mark representation as dirty (not synchronized with VM) """
        self.__state += 1

    def _set_clean(self):
        """ Mark representation as clean (synchronized with VM) """
        self.__state -= 1

    def get_state(self):
        """ Get the current state (0 = synchronized with VM) """
        return self.__state

    def get_by_qid(self, qid):
        """
        @param qid: qemu id
        @return: List of items with matching qemu id
        """
        ret = []
        if qid:
            for device in self:
                if device.get_qid() == qid:
                    ret.append(device)
        return ret

    def str_short(self):
        """ Short string representation of all devices """
        out = "Devices of %s" % self.vmname
        dirty = self.get_state()
        if dirty:
            out += "(DIRTY%s)" % dirty
        out += ": ["
        for device in self:
            out += "%s," % device
        if out[-1] == ',':
            out = out[:-1]
        return out + "]"

    def str_long(self):
        """ Long string representation of all devices """
        out = "Devices of %s" % self.vmname
        dirty = self.get_state()
        if dirty:
            out += " (DIRTY%s)" % dirty
        out += ":\n"
        for device in self:
            out += device.str_long()
        if out[-1] == '\n':
            out = out[:-1]
        return out

    def str_bus_short(self):
        """ Short representation of all buses """
        out = "Buses of %s\n  " % self.vmname
        for bus in self.__buses:
            out += str(bus)
            out += "\n  "
        return out[:-3]

    def str_bus_long(self):
        """ Long representation of all buses """
        out = "Devices of %s:\n  " % self.vmname
        for bus in self.__buses:
            out += bus.str_long().replace('\n', '\n  ')
        return out[:-3]

    def __create_unique_aid(self, qid):
        """
        Creates unique autotest id name from given qid
        @param qid: Original qemu id
        @return: aid (the format is "$qid__%d")
        """
        if qid and qid not in self:
            return qid
        i = 0
        while "%s__%d" % (qid, i) in self:
            i += 1
        return "%s__%d" % (qid, i)

    def has_option(self, option):
        """
        @param option: Desired option
        @return: Is the desired option supported by current qemu?
        """
        return bool(re.search(r"^-%s(\s|$)" % option, self.__qemu_help,
                              re.MULTILINE))

    def has_device(self, device):
        """
        @param device: Desired device
        @return: Is the desired device supported by current qemu?
        """
        return bool(re.search(r'name "%s"' % device, self.__device_help,
                              re.MULTILINE))

    def get_help_text(self):
        """
        @return: Full output of "qemu -help"
        """
        return self.__qemu_help

    def has_hmp_cmd(self, cmd):
        """
        @param cmd: Desired command
        @return: Is the desired command supported by this qemu's human monitor?
        """
        return cmd in self.__hmp_cmds

    def has_qmp_cmd(self, cmd):
        """
        @param cmd: Desired command
        @return: Is the desired command supported by this qemu's QMP monitor?
        """
        return cmd in self.__qmp_cmds

    def get_buses(self, bus_spec):
        """
        @param bus_spec: Bus specification (dictionary)
        @return: All matching buses
        """
        buses = []
        for bus in self.__buses:
            for key, value in bus_spec.iteritems():
                if not bus.__getattribute__(key) == value:
                    break
            else:
                buses.append(bus)
        return buses

    def get_first_free_bus(self, bus_spec, addr):
        """
        @param bus_spec: Bus specification (dictionary)
        @param addr: Desired address
        @return: First matching bus with free desired address (the latest
                 added matching bus)
        """
        buses = self.get_buses(bus_spec)
        for bus in buses:
            _ = bus.get_free_slot(addr)
            if _ is not None and _ is not False:
                return bus

    def insert(self, device, force=False):
        """
        Inserts device into this VM representation
        @param device: QBaseDevice device
        @param force: Force insert the device even when errs occurs
        @return: None on success,
                 error string when force added device with errors.
        @raise DeviceInsertError: On failure in case force is not set

        1) get list of matching parent buses
        2) try to find matching bus+address gently
        3) if it fails and force is specified, try to insert it into full
           buses. If none is found use non-matching bus.
        4) insert(0, child bus) (this way we always start with the latest bus)
        5) append into self.devices
        """
        def clean():
            """ Remove all inserted devices on failure """
            for bus in _used_buses:
                bus.remove(device)
            for bus in _added_buses:
                self.__buses.remove(bus)
        err = ""
        _used_buses = []
        _added_buses = []
        # 1
        if device.parent_bus is not None and not isinstance(device.parent_bus,
                                                            (list, tuple)):
            # it have to be list of parent buses
            device.parent_bus = (device.parent_bus,)
        for parent_bus in device.parent_bus:
            # type, aobject, busid
            if parent_bus is None:
                continue
            buses = self.get_buses(parent_bus)
            if not buses:
                if force:
                    err += "ParentBus(%s): No matching bus\n" % parent_bus
                    continue
                else:
                    clean()
                    raise DeviceInsertError(device, err, self)
            bus_returns = []
            for bus in buses:   # 2
                bus_returns.append(bus.insert(device, self.strict_mode, False))
                if bus_returns[-1] is True:     # we are done
                    _used_buses.append(bus)
                    break
            if bus_returns[-1] is True:
                continue
            elif not force:
                clean()
                raise DeviceInsertError(device, err, self)
            if None in bus_returns:  # 3a
                _err = buses[bus_returns.index(None)].insert(device,
                                                    self.strict_mode, True)
                if _err:
                    err += "ParentBus(%s): %s\n" % (parent_bus, _err)
                    continue
            _err = buses[0].insert(device, self.strict_mode, True)
            _used_buses.append(buses[0])
            if _err:
                err += "ParentBus(%s): %s\n" % (parent_bus, _err)
                continue
        # 4
        if device.child_bus is not None and not isinstance(device.child_bus,
                                                           (list, tuple)):
            # it have to be list of parent buses
            device.child_bus = (device.child_bus,)
        for bus in device.child_bus:
            self.__buses.insert(0, bus)
            _added_buses.append(bus)
        # 5
        if device.get_qid() and self.get_by_qid(device.get_qid()):
            if not force:
                clean()
                raise DeviceInsertError(device, err, self)
            else:
                err += "Devices qid %s already used in VM\n" % device.get_qid()
        device.set_aid(self.__create_unique_aid(device.get_qid()))
        self.__devices.append(device)
        if err:
            return ("Errors occured while adding device %s into %s:\n%s"
                    % (device, self, err))

    def list_missing_named_buses(self, bus_pattern, bus_type, bus_count):
        """
        @param bus_pattern: Bus name pattern with 1x%s for idx or %s is
                            appended in the end. ('mybuses' or 'my%sbus').
        @param bus_type: Type of the bus.
        @param bus_count: Desired number of buses.
        @return: List of buses, which are missing in range(bus_count)
        """
        if not "%s" in bus_pattern:
            bus_pattern = bus_pattern + "%s"
        missing_buses = [bus_pattern % i for i in xrange(bus_count)]
        for bus in self.__buses:
            if bus.type == bus_type and re.match(bus_pattern % '\d+',
                                                 bus.busid):
                if bus.busid in missing_buses:
                    missing_buses.remove(bus.busid)
        return missing_buses

    def idx_of_next_named_bus(self, bus_pattern):
        """
        @param bus_pattern: Bus name prefix without %s and tailing digit
        @return: Name of the next bus (integer is appended and incremented
                 until there is no existing bus).
        """
        if not "%s" in bus_pattern:
            bus_pattern = bus_pattern + "%s"
        buses = []
        for bus in self.__buses:
            if bus.busid and re.match(bus_pattern % '\d+', bus.busid):
                buses.append(bus.busid)
        i = 0
        while True:
            if bus_pattern % i not in buses:
                return i
            i += 1

    def cmdline(self):
        """
        Creates cmdline arguments for creating all defined devices
        @return: cmdline of all devices (without qemu-cmd itself)
        """
        out = ""
        for device in self.__devices:
            _out = device.cmdline()
            if _out:
                out += " %s" % _out
        if out:
            return out[1:]

    # Machine related methods
    def machine_by_params(self, params=None):
        """
        Choose the used machine and set the default devices accordingly
        @param params: VM params
        @return: List of added devices (including default buses)
        """
        def machine_q35(cmd=False):
            """
            Q35 + ICH9
            @param cmd: If set uses "-M $cmd" to force this machine type
            @return: List of added devices (including default buses)
            """
            # TODO: Add all supported devices (AHCI, ...) and
            # verify that PCIE works as pci bus (ranges, etc...)
            logging.warn('Using Q35 machine which is not yet fullytested on '
                         'virt-test. False errors might occur.')
            devices = []
            devices.append(QStringDevice('machine', cmdline=cmd,
                                         child_bus=QPCIBus('pcie.0', 'pci')))
            devices.append(QStringDevice('Q35', {'addr': 0},
                                         parent_bus={'type': 'pci'}))
            devices.append(QStringDevice('ICH9', {'addr': '0x1f'},
                                         parent_bus={'type': 'pci'}))
            return devices

        def machine_i440FX(cmd=False):
            """
            i440FX + PIIX
            @param cmd: If set uses "-M $cmd" to force this machine type
            @return: List of added devices (including default buses)
            """
            devices = []
            if arch.ARCH == 'ppc64':
                pci_bus = "pci"
            else:
                pci_bus = "pci.0"
            devices.append(QStringDevice('machine', cmdline=cmd,
                                         child_bus=QPCIBus(pci_bus, 'pci')))
            devices.append(QStringDevice('i440FX', {'addr': 0},
                                         parent_bus={'type': 'pci'}))
            devices.append(QStringDevice('PIIX3', {'addr': 1},
                                         parent_bus={'type': 'pci'}))
            return devices

        def machine_other(cmd=False):
            """
            isapc or unknown machine type. This type doesn't add any default
            buses or devices, only sets the cmdline.
            @param cmd: If set uses "-M $cmd" to force this machine type
            @return: List of added devices (including default buses)
            """
            logging.warn('isa/unknown machine type is not supported by '
                         'autotest, false errors might occur.')
            devices = []
            devices.append(QStringDevice('machine', cmdline=cmd))
            return devices

        machine_type = params.get('machine_type')
        if machine_type:
            m_types = []
            for _ in self.__machine_types.splitlines()[1:]:
                m_types.append(_.split()[0])

            if machine_type in m_types:
                if (self.has_option('M') or self.has_option('machine')):
                    cmd = "-M %s" % machine_type
                else:
                    cmd = ""
                if 'q35' in machine_type:   # Q35 + ICH9
                    devices = machine_q35(cmd)
                elif 'isapc' not in machine_type:   # i440FX
                    devices = machine_i440FX(cmd)
                else:   # isapc (or other)
                    devices = machine_other(cmd)
            elif params.get("invalid_machine_type", "no") == "yes":
                # For negative testing pretend the unsupported machine is
                # similar to i440fx one (1 PCI bus, ..)
                devices = machine_i440FX("-M %s" % machine_type)
            else:
                raise error.TestNAError("Unsupported machine type %s." %
                                        (machine_type))
        else:
            for _ in self.__machine_types.splitlines()[1:]:
                if 'default' in _:
                    if 'q35' in machine_type:   # Q35 + ICH9
                        devices = machine_q35(False)
                    elif 'isapc' not in machine_type:   # i440FX
                        devices = machine_i440FX(False)
                    else:   # isapc (or other)
                        logging.warn('isa/unknown machine type is not '
                                     'supported byautotest, false errors '
                                     'might occur.')
                        devices = machine_other(False)
            else:
                logging.warn("Unable to find the default machine type, using"
                             "i440FX.")
                devices = machine_i440FX(False)
        return devices
