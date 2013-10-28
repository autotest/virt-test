"""
Library of objects, which could represent qemu devices in order to create
complete representation of VM. There are three parts:
1) Device objects - individual devices representation
2) Bus representation - bus representation
3) Device container - qemu machine representation

:copyright: 2012-2013 Red Hat Inc.
"""
# Python imports
import itertools
import logging
import os
import re

# Autotest imports
from autotest.client.shared import error, utils
import arch
import data_dir
import qemu_monitor
import storage
import virt_vm
import utils_misc

try:
    # pylint: disable=E0611
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
        self.issue = "insert"

    def __str__(self):
        return ("Failed to %s device:\n%s\nBecause:\n%s\nList of VM devices:\n"
                "%s\n%s" % (self.issue, self.device.str_long(), self.reason,
                            self.vmdev.str_short(), self.vmdev.str_bus_long()))


class DeviceRemoveError(DeviceInsertError):

    """ Fail to remove device """

    def __init__(self, device, reason, vmdev):
        super(DeviceRemoveError, self).__init__(device, reason, vmdev)
        self.issue = "remove"


class DeviceHotplugError(DeviceInsertError):

    """ Fail to hotplug device """

    def __init__(self, device, reason, vmdev):
        super(DeviceHotplugError, self).__init__(device, reason, vmdev)
        self.issue = "hotplug"


class DeviceUnplugError(DeviceHotplugError):

    """ Fail to unplug device """

    def __init__(self, device, reason, vmdev):
        super(DeviceUnplugError, self).__init__(device, reason, vmdev)
        self.issue = "unplug"


def _convert_args(arg_dict):
    """
    Convert monitor command arguments dict into humanmonitor string.

    :param arg_dict: The dict of monitor command arguments.
    :return: A string in humanmonitor's 'key=value' format, or a empty
             '' when the dict is empty.
    """
    return ",".join("%s=%s" % (key, val) for key, val in arg_dict.iteritems())


def none_or_int(value):
    """ Helper fction which returns None or int() """
    if isinstance(value, int):
        return value
    elif not value:   # "", None, False
        return None
    elif isinstance(value, str) and value.isdigit():
        return int(value)
    else:
        raise TypeError("This parameter has to be int or none")


def _build_cmd(cmd, args=None, q_id=None):
    """
    Format QMP command from cmd and args

    :param cmd: Command ('device_add', ...)
    :param q_id: queue id; True = generate random, None = None, str = use str
    """
    obj = {"execute": cmd}
    if args is not None:
        obj["arguments"] = args
    if q_id is True:
        obj["id"] = utils_misc.generate_random_string(8)
    elif q_id is not None:
        obj["id"] = q_id
    return obj


#
# Device objects
#
class QBaseDevice(object):

    """ Base class of qemu objects """

    def __init__(self, dev_type="QBaseDevice", params=None, aobject=None,
                 parent_bus=None, child_bus=None):
        """
        :param dev_type: type of this component
        :param params: component's parameters
        :param aobject: Autotest object which is associated with this device
        :param parent_bus: list of dicts specifying the parent bus
        :param child_bus: list of buses, which this device provides
        """
        self.aid = None         # unique per VM id
        self.type = dev_type    # device type
        self.aobject = aobject  # related autotest object
        if parent_bus is None:
            parent_bus = tuple()
        self.parent_bus = parent_bus   # list of buses into which this dev fits
        self.child_bus = []            # list of buses which this dev provides
        if child_bus is None:
            child_bus = []
        elif not isinstance(child_bus, (list, tuple)):
            self.add_child_bus(child_bus)
        else:
            for bus in child_bus:
                self.add_child_bus(bus)
        self.params = OrderedDict()    # various device params (id, name, ...)
        if params:
            for key, value in params.iteritems():
                self.set_param(key, value)

    def add_child_bus(self, bus):
        """
        Add child bus
        :param bus: Bus, which this device contains
        :type bus: QSparseBus-like
        """
        self.child_bus.append(bus)
        bus.set_device(self)

    def rm_child_bus(self, bus):
        """
        removes child bus
        :param bus: Bus, which this device contains
        :type bus: QSparseBus-like
        """
        self.child_bus.remove(bus)
        bus.set_device(None)

    def set_param(self, option, value, option_type=None):
        """
        Set device param using qemu notation ("on", "off" instead of bool...)
        :param option: which option's value to set
        :param value: new value
        :param option_type: type of the option (bool)
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

    def get_param(self, option, default=None):
        """ :return: object param """
        return self.params.get(option, default)

    def __getitem__(self, option):
        """ :return: object param """
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
        """ :return: Short string representation of this object. """
        return self.str_short()

    def __eq__(self, dev2):
        """ :return: True when devs are similar, False when different. """
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
        """ :return: True when devs are different, False when similar. """
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
        """ :return: alternative object name """
        return None

    def get_qid(self):
        """ :return: qemu_id """
        return self.params.get('id', '')

    def get_aid(self):
        """ :return: per VM unique autotest_id """
        return self.aid

    def set_aid(self, aid):
        """:param aid: new autotest id for this device"""
        self.aid = aid

    def get_children(self):
        """ :return: List of all children (recursive) """
        children = []
        for bus in self.child_bus:
            children.extend(bus)
        return children

    def cmdline(self):
        """ :return: cmdline command to define this device """
        raise NotImplementedError

    def hotplug(self, monitor):
        """ :return: the output of monitor.cmd() hotplug command """
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
        """ :return: the hotplug monitor command """
        raise DeviceError("Hotplug is not supported by this device %s", self)

    def hotplug_qmp(self):
        """ :return: tuple(hotplug qemu command, arguments)"""
        raise DeviceError("Hotplug is not supported by this device %s", self)

    def unplug_hook(self):
        """ Modification prior to unplug can be made here """
        pass

    def unplug_unhook(self):
        """ Roll back the modification made before unplug """
        pass

    def unplug(self, monitor):
        """ :return: the output of monitor.cmd() unplug command """
        if isinstance(monitor, qemu_monitor.QMPMonitor):
            try:
                cmd, args = self.unplug_qmp()
                return monitor.cmd(cmd, args)
            except DeviceError:     # qmp command not supported
                return monitor.human_monitor_cmd(self.unplug_hmp())
        elif isinstance(monitor, qemu_monitor.HumanMonitor):
            return monitor.cmd(self.unplug_hmp())
        else:
            raise TypeError("Invalid monitor object: %s(%s)" % (monitor,
                                                                type(monitor)))

    def unplug_hmp(self):
        """ :return: the unplug monitor command """
        raise DeviceError("Unplug is not supported by this device %s", self)

    def unplug_qmp(self):
        """ :return: tuple(unplug qemu command, arguments)"""
        raise DeviceError("Unplug is not supported by this device %s", self)

    def verify_hotplug(self, out, monitor):
        """
        :param out: Output of the hotplug command
        :param monitor: Monitor used for hotplug
        :return: True when successful, False when unsuccessful, string/None
                 when can't decide.
        """
        return out

    def verify_unplug(self, out, monitor):      # pylint: disable=W0613,R0201
        """
        :param out: Output of the unplug command
        :param monitor: Monitor used for unplug
        """
        return out


class QStringDevice(QBaseDevice):

    """
    General device which allows to specify methods by fixed or parametrizable
    strings in this format:
      "%(type)s,id=%(id)s,addr=%(addr)s" -- params will be used to subst %()s
    """

    def __init__(self, dev_type="dummy", params=None, aobject=None,
                 parent_bus=None, child_bus=None, cmdline=""):
        """
        :param dev_type: type of this component
        :param params: component's parameters
        :param aobject: Autotest object which is associated with this device
        :param parent_bus: bus(es), in which this device is plugged in
        :param child_bus: bus, which this device provides
        :param cmdline: cmdline string
        """
        super(QStringDevice, self).__init__(dev_type, params, aobject,
                                            parent_bus, child_bus)
        self._cmdline = cmdline

    def cmdline(self):
        """ :return: cmdline command to define this device """
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
                 parent_bus=None, child_bus=None, backend=None):
        """
        :param dev_type: The desired -$option parameter (device, chardev, ..)
        """
        super(QCustomDevice, self).__init__(dev_type, params, aobject,
                                            parent_bus, child_bus)
        if backend:
            self.__backend = backend
        else:
            self.__backend = None

    def cmdline(self):
        """ :return: cmdline command to define this device """
        if self.__backend and self.params.get(self.__backend):
            out = "-%s %s," % (self.type, self.params.get(self.__backend))
            params = self.params.copy()
            del params[self.__backend]
        else:
            out = "-%s " % self.type
            params = self.params
        for key, value in params.iteritems():
            if value != "NO_EQUAL_STRING":
                out += "%s=%s," % (key, value)
            else:
                out += "%s," % key
        if out[-1] == ',':
            out = out[:-1]
        return out


class QDrive(QCustomDevice):

    """
    Representation of the '-drive' qemu object without hotplug support.
    """

    def __init__(self, aobject, use_device=True):
        child_bus = QDriveBus('drive_%s' % aobject, aobject)
        super(QDrive, self).__init__("drive", {}, aobject, (),
                                     child_bus)
        if use_device:
            self.params['id'] = 'drive_%s' % aobject

    def set_param(self, option, value, option_type=None):
        """
        Set device param using qemu notation ("on", "off" instead of bool...)
        It restricts setting of the 'id' param as it's automatically created.
        :param option: which option's value to set
        :param value: new value
        :param option_type: type of the option (bool)
        """
        if option == 'id':
            raise KeyError("Drive ID is automatically created from aobject. %s"
                           % self)
        elif option == 'bus':
            # Workaround inconsistency between -drive and -device
            value = re.findall(r'(\d+)', value)
            if value is not None:
                value = value[0]
        super(QDrive, self).set_param(option, value, option_type)


class QHPDrive(QDrive):

    """
    Representation of the '-drive' qemu object with hotplug support.
    """

    def __init__(self, aobject):
        super(QHPDrive, self).__init__(aobject)
        self.__hook_drive_bus = None

    def verify_hotplug(self, out, monitor):
        if isinstance(monitor, qemu_monitor.QMPMonitor):
            if out.startswith('OK'):
                return True
        else:
            if out == 'OK':
                return True
        return False

    def verify_unplug(self, out, monitor):
        out = monitor.info("qtree", debug=False)
        if "unknown command" in out:       # Old qemu don't have info qtree
            return True
        dev_id_name = 'id "%s"' % self.aid
        if dev_id_name in out:
            return False
        else:
            return True

    def get_children(self):
        """ Device bus should be removed too """
        for bus in self.child_bus:
            if isinstance(bus, QDriveBus):
                drive_bus = bus
                self.rm_child_bus(bus)
                break
        devices = super(QHPDrive, self).get_children()
        self.add_child_bus(drive_bus)
        return devices

    def unplug_hook(self):
        """
        Devices from this bus are not removed, only 'drive' is set to None.
        """
        for bus in self.child_bus:
            if isinstance(bus, QDriveBus):
                for dev in bus:
                    self.__hook_drive_bus = dev.get_param('drive')
                    dev['drive'] = None
                break

    def unplug_unhook(self):
        """ Set back the previous 'drive' (unsafe, using the last value) """
        if self.__hook_drive_bus is not None:
            for bus in self.child_bus:
                if isinstance(bus, QDriveBus):
                    for dev in bus:
                        dev['drive'] = self.__hook_drive_bus
                    break

    def hotplug_hmp(self):
        """ :return: the hotplug monitor command """
        args = self.params.copy()
        pci_addr = args.pop('addr', 'auto')
        args = _convert_args(args)
        return "drive_add %s %s" % (pci_addr, args)

    def unplug_hmp(self):
        """ :return: the unplug monitor command """
        if self.get_qid() is None:
            raise DeviceError("qid not set; device %s can't be unplugged"
                              % self)
        return "drive_del %s" % self.get_qid()


class QRHDrive(QDrive):

    """
    Representation of the '-drive' qemu object with RedHat hotplug support.
    """

    def __init__(self, aobject):
        super(QRHDrive, self).__init__(aobject)
        self.__hook_drive_bus = None

    def hotplug_hmp(self):
        """ :return: the hotplug monitor command """
        args = self.params.copy()
        args.pop('addr', None)    # not supported by RHDrive
        args.pop('if', None)
        args = _convert_args(args)
        return "__com.redhat_drive_add %s" % args

    def hotplug_qmp(self):
        """ :return: the hotplug monitor command """
        args = self.params.copy()
        args.pop('addr', None)    # not supported by RHDrive
        args.pop('if', None)
        return "__com.redhat_drive_add", args

    def get_children(self):
        """ Device bus should be removed too """
        for bus in self.child_bus:
            if isinstance(bus, QDriveBus):
                drive_bus = bus
                self.rm_child_bus(bus)
                break
        devices = super(QRHDrive, self).get_children()
        self.add_child_bus(drive_bus)
        return devices

    def unplug_hook(self):
        """
        Devices from this bus are not removed, only 'drive' is set to None.
        """
        for bus in self.child_bus:
            if isinstance(bus, QDriveBus):
                for dev in bus:
                    self.__hook_drive_bus = dev.get_param('drive')
                    dev['drive'] = None
                break

    def unplug_unhook(self):
        """ Set back the previous 'drive' (unsafe, using the last value) """
        if self.__hook_drive_bus is not None:
            for bus in self.child_bus:
                if isinstance(bus, QDriveBus):
                    for dev in bus:
                        dev['drive'] = self.__hook_drive_bus
                    break

    def unplug_hmp(self):
        """ :return: the unplug monitor command """
        if self.get_qid() is None:
            raise DeviceError("qid not set; device %s can't be unplugged"
                              % self)
        return "__com.redhat_drive_del %s" % self.get_qid()

    def unplug_qmp(self):
        """ :return: the unplug monitor command """
        if self.get_qid() is None:
            raise DeviceError("qid not set; device %s can't be unplugged"
                              % self)
        return "__com.redhat_drive_del", {'id': self.get_qid()}


# TODO: Add QPCIDrive - using pci_add/pci_del


class QDevice(QCustomDevice):

    """
    Representation of the '-device' qemu object. It supports all methods.
    :note: Use driver format in full form - 'driver' = '...' (usb-ehci, ide-hd)
    """

    def __init__(self, driver=None, params=None, aobject=None,
                 parent_bus=None, child_bus=None):
        super(QDevice, self).__init__("device", params, aobject, parent_bus,
                                      child_bus, 'driver')
        if driver:
            self.set_param('driver', driver)
        self.hook_drive_bus = None

    def _get_alternative_name(self):
        """ :return: alternative object name """
        if self.params.get('driver'):
            return self.params.get('driver')

    def hotplug_hmp(self):
        """ :return: the hotplug monitor command """
        if self.params.get('driver'):
            params = self.params.copy()
            out = "device_add %s" % params.pop('driver')
            params = _convert_args(params)
            if params:
                out += ",%s" % params
        else:
            out = "device_add %s" % _convert_args(self.params)
        return out

    def hotplug_qmp(self):
        """ :return: the hotplug monitor command """
        return "device_add", self.params

    def get_children(self):
        """ Device bus should be removed too """
        devices = super(QDevice, self).get_children()
        if self.hook_drive_bus:
            devices.append(self.hook_drive_bus)
        return devices

    def unplug_hmp(self):
        """ :return: the unplug monitor command """
        if self.get_qid():
            return "device_del %s" % self.get_qid()
        else:
            raise DeviceError("Device has no qemu_id.")

    def unplug_qmp(self):
        """ :return: the unplug monitor command """
        if self.get_qid():
            return "device_del", self.get_qid()
        else:
            raise DeviceError("Device has no qemu_id.")

    def verify_unplug(self, out, monitor):
        out = monitor.info("qtree", debug=False)
        if "unknown command" in out:       # Old qemu don't have info qtree
            return out
        dev_id_name = 'id "%s"' % self.aid
        if dev_id_name in out:
            return False
        else:
            return True

    def verify_hotplug(self, out, monitor):
        out = monitor.info("qtree", debug=False)
        if "unknown command" in out:       # Old qemu don't have info qtree
            return out
        dev_id_name = 'id "%s"' % self.aobject
        if dev_id_name in out:
            return True
        else:
            return False


class QGlobal(QBaseDevice):

    """
    Representation of qemu global setting (-global driver.property=value)
    """

    def __init__(self, driver, prop, value, aobject=None,
                 parent_bus=None, child_bus=None):
        """
        :param driver: Which global driver to set
        :param prop: Which property to set
        :param value: What's the desired value
        :param params: component's parameters
        :param aobject: Autotest object which is associated with this device
        :param parent_bus: bus(es), in which this device is plugged in
        :param child_bus: bus, which this device provides
        """
        params = {'driver': driver, 'property': prop, 'value': value}
        super(QGlobal, self).__init__('global', params, aobject,
                                      parent_bus, child_bus)

    def cmdline(self):
        return "-global %s.%s=%s" % (self['driver'], self['property'],
                                     self['value'])


class QFloppy(QGlobal):

    """
    Imitation of qemu floppy disk defined by -global isa-fdc.drive?=$drive
    """

    def __init__(self, unit=None, drive=None, aobject=None, parent_bus=None,
                 child_bus=None):
        """
        :param unit: Floppy unit (None, 0, 1 or driveA, driveB)
        :param drive: id of drive
        :param aobject: Autotest object which is associated with this device
        :param parent_bus: bus(es), in which this device is plugged in
        :param child_bus: bus(es), which this device provides
        """
        super(QFloppy, self).__init__('isa-fdc', unit, drive, aobject,
                                      parent_bus, child_bus)

    def _get_alternative_name(self):
        return "floppy-%s" % (self.get_param('property'))

    def set_param(self, option, value, option_type=None):
        """
        drive and unit params have to be 'translated' as value and property.
        """
        if option == 'drive':
            option = 'value'
        elif option == 'unit':
            option = 'property'
        super(QFloppy, self).set_param(option, value, option_type)


#
# Bus representations
# HDA, I2C, IDE, ISA, PCI, SCSI, System, uhci, ehci, ohci, xhci, ccid,
# virtio-serial-bus
#
class QSparseBus(object):

    """
    Universal bus representation object.
    It creates an abstraction of the way how buses works in qemu. Additionally
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

    :note: When you insert a device, it's properties might be updated (addr,..)
    """

    def __init__(self, bus_item, addr_spec, busid, bus_type=None, aobject=None,
                 atype=None):
        """
        :param bus_item: Name of the parameter which specifies bus (bus)
        :type bus_item: str
        :param addr_spec: Bus address specification [names][lengths]
        :type addr_spec: list of lists
        :param busid: id of the bus (pci.0)
        :type busid: str
        :param bus_type: type of the bus (pci)
        :type bus_type: dict
        :param aobject: Related autotest object (image1)
        :type aobject: str
        :param atype: Autotest bus type
        :type atype: str
        """
        self.busid = busid
        self.type = bus_type
        self.aobject = aobject
        self.bus = {}                       # Normal bus records
        self.bus_item = bus_item            # bus param name
        self.addr_items = addr_spec[0]      # [names][lengths]
        self.addr_lengths = addr_spec[1]
        self.atype = atype
        self.__device = None
        self.first_port = [0] * len(addr_spec[0])

    def __str__(self):
        """ default string representation """
        return self.str_short()

    def __getitem__(self, item):
        """
        :param item: autotest id or QObject-like object
        :return: First matching object from this bus
        :raise KeyError: In case no match was found
        """
        if isinstance(item, QBaseDevice):
            if item in self.bus.itervalues():
                return item
        else:
            for device in self.bus.itervalues():
                if device.get_aid() == item:
                    return device
        raise KeyError("Device %s is not in %s" % (item, self))

    def get(self, item):
        """
        :param item: autotest id or QObject-like object
        :return: First matching object from this bus or None
        """
        if item in self:
            return self[item]

    def __delitem__(self, item):
        """
        Remove device from bus
        :param item: autotest id or QObject-like object
        :raise KeyError: In case no match was found
        """
        self.remove(self[item])

    def __len__(self):
        """ :return: Number of devices in this bus """
        return len(self.bus)

    def __contains__(self, item):
        """
        Is specified item in this bus?
        :param item: autotest id or QObject-like object
        :return: True - yes, False - no
        """
        if isinstance(item, QBaseDevice):
            if item in self.bus.itervalues():
                return True
        else:
            for device in self:
                if device.get_aid() == item:
                    return True
        return False

    def __iter__(self):
        """ Iterate over all defined devices. """
        return self.bus.itervalues()

    def str_short(self):
        """ short string representation """
        if self.atype:
            bus_type = self.atype
        else:
            bus_type = self.type
        return "%s(%s): %s" % (self.busid, bus_type, self._str_devices())

    def _str_devices(self):
        """ short string representation of the good bus """
        out = '{'
        for addr in sorted(self.bus.keys()):
            out += "%s:%s," % (addr, self.bus[addr])
        if out[-1] == ',':
            out = out[:-1]
        return out + '}'

    def str_long(self):
        """ long string representation """
        if self.atype:
            bus_type = self.atype
        else:
            bus_type = self.type
        return "Bus %s, type=%s\nSlots:\n%s" % (self.busid, bus_type,
                                                self._str_devices_long())

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

    def _increment_addr(self, addr, last_addr=None):
        """
        Increment addr base of addr_pattern and last used addr
        :param addr: addr_pattern
        :param last_addr: previous address
        :return: last_addr + 1
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
        :param addr: internal address [addr1, addr2, ...]
        :return: storable address "addr1-addr2-..."
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
        :param device: QBaseDevice device
        :return: internal address  [addr1, addr2, ...]
        """
        addr = []
        for key in self.addr_items:
            addr.append(none_or_int(device.get_param(key)))
        return addr

    def _set_first_addr(self, addr_pattern):
        """
        :param addr_pattern: Address pattern (full qualified or with Nones)
        :return: first valid address based on addr_pattern
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
                    last_addr[i] = self.first_port[i]
        return last_addr, use_reserved

    def get_free_slot(self, addr_pattern):
        """
        Finds unoccupied address
        :param addr_pattern: Address pattern (full qualified or with Nones)
        :return: First free address when found, (free or reserved for this dev)
                 None when no free address is found, (all occupied)
                 False in case of incorrect address (oor)
        """
        # init
        last_addr, use_reserved = self._set_first_addr(addr_pattern)
        # Check the addr_pattern ranges
        for i in xrange(len(self.addr_lengths)):
            if (last_addr[i] < self.first_port[i] or
                    last_addr[i] >= self.addr_lengths[i]):
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
        :param device: QBaseDevice device
        :return: True in case ids are correct, False when not
        """
        if (device.get_param(self.bus_item) and
           device.get_param(self.bus_item) != self.busid):
            return False
        else:
            return True

    def _set_device_props(self, device, addr):
        """
        Set the full device address
        :param device: QBaseDevice device
        :param addr: internal address  [addr1, addr2, ...]
        """
        if self.bus_item:
            device.set_param(self.bus_item, self.busid)
        for i in xrange(len(self.addr_items)):
            device.set_param(self.addr_items[i], addr[i])

    def _update_device_props(self, device, addr):
        """
        Update values of previously set address items.
        :param device: QBaseDevice device
        :param addr: internal address  [addr1, addr2, ...]
        """
        if device.get_param(self.bus_item) is not None:
            device.set_param(self.bus_item, self.busid)
        for i in xrange(len(self.addr_items)):
            if device.get_param(self.addr_items[i]) is not None:
                device.set_param(self.addr_items[i], addr[i])

    def reserve(self, addr):
        """
        Reserve the slot
        :param addr: Desired address
        :type addr: internal [addr1, addr2, ..] or stor format "addr1-addr2-.."
        """
        if not isinstance(addr, str):
            addr = self._addr2stor(addr)
        self.bus[addr] = "reserved"

    def insert(self, device, strict_mode=False):
        """
        Insert device into this bus representation.
        :param device: QBaseDevice device
        :param strict_mode: Use strict mode (set optional params)
        :return: list of added devices on success,
                 string indicating the failure on failure.
        """
        additional_devices = []
        if not self._check_bus(device):
            return "BusId"
        try:
            addr_pattern = self._dev2addr(device)
        except (ValueError, LookupError):
            return "BasicAddress"
        addr = self.get_free_slot(addr_pattern)
        if addr is None:
            if None in addr_pattern:
                return "NoFreeSlot"
            else:
                return "UsedSlot"
        elif addr is False:
            return "BadAddr(%s)" % addr
        else:
            additional_devices.extend(self._insert(device,
                                                   self._addr2stor(addr)))
        if strict_mode:     # Set full address in strict_mode
            self._set_device_props(device, addr)
        else:
            self._update_device_props(device, addr)
        return additional_devices

    def _insert(self, device, addr):
        """
        Insert device into good bus
        :param device: QBaseDevice device
        :param addr: internal address  [addr1, addr2, ...]
        :return: List of additional devices
        """
        self.bus[addr] = device
        return []

    def remove(self, device):
        """
        Remove device from this bus
        :param device: QBaseDevice device
        :return: True when removed, False when the device wasn't found
        """
        if device in self.bus.itervalues():
            remove = None
            for key, item in self.bus.iteritems():
                if item is device:
                    remove = key
                    break
            if remove is not None:
                del(self.bus[remove])
                return True
        return False

    def set_device(self, device):
        """ Set the device in which this bus belongs """
        self.__device = device

    def get_device(self):
        """ Get device in which this bus is present """
        return self.__device

    def match_bus(self, bus_spec, type_test=True):
        """
        Check if the bus matches the bus_specification.
        :param bus_spec: Bus specification
        :type bus_spec: dict
        :param type_test: Match only type
        :type type_test: bool
        :return: True when the bus matches the specification
        :rtype: bool
        """
        if type_test and bus_spec.get('type'):
            if isinstance(bus_spec['type'], (tuple, list)):
                for bus_type in bus_spec['type']:
                    if bus_type == self.type:
                        return True
                return False
        for key, value in bus_spec.iteritems():
            if isinstance(value, (tuple, list)):
                for val in value:
                    if self.__dict__.get(key, None) == val:
                        break
                else:
                    return False
            elif self.__dict__.get(key, None) != value:
                return False
        return True


class QStrictCustomBus(QSparseBus):
    """
    Similar to QSparseBus. The address starts with 1 and addr is always set
    """
    def __init__(self, bus_item, addr_spec, busid, bus_type=None, aobject=None,
                 atype=None, first_port=None):
        super(QStrictCustomBus, self).__init__(bus_item, addr_spec, busid,
                                               bus_type, aobject, atype)
        if first_port:
            self.first_port = first_port

    def _update_device_props(self, device, addr):
        """ in case this is usb-hub update the child port_prefix """
        self._set_device_props(device, addr)


class QUSBBus(QSparseBus):

    """
    USB bus representation including usb-hub handling.
    """

    def __init__(self, length, busid, bus_type, aobject=None,
                 port_prefix=None):
        """
        Bus type have to be generalized and parsed from original bus type:
        (usb-ehci == ehci, ich9-usb-uhci1 == uhci, ...)
        """
        # There are various usb devices for the same bus type, use only portion
        for bus in ('uhci', 'ehci', 'ohci', 'xhci'):
            if bus in bus_type:
                bus_type = bus
                break
        # Usb ports are counted from 1 so the length have to be +1
        super(QUSBBus, self).__init__('bus', [['port'], [length + 1]], busid,
                                      bus_type, aobject)
        self.__port_prefix = port_prefix
        self.__length = length
        self.first_port = [1]

    def _check_bus(self, device):
        """ Check port prefix in order to match addresses in usb-hubs """
        if not super(QUSBBus, self)._check_bus(device):
            return False
        port = device.get_param('port')   # 2.1.6
        if port or port == 0:   # If port is specified
            idx = str(port).rfind('.')
            if idx != -1:   # Strip last number and compare with port_prefix
                return port[:idx] == self.__port_prefix
            # Port is number, match only root usb bus
            elif self.__port_prefix != "":
                return False
        return True

    def _dev2addr(self, device):
        """
        Parse the internal address out of the device
        :param device: QBaseDevice device
        :return: internal address  [addr1, addr2, ...]
        """
        value = device.get_param('port')
        if value is None:
            addr = [None]
        else:
            addr = [int(value[len(self.__port_prefix) + 1:])]
        return addr

    def __hook_child_bus(self, device, addr):
        """ If this is usb-hub, add child bus """
        # only usb hub needs customization
        if device.get_param('driver') != 'usb-hub':
            return
        _bus = [_ for _ in device.child_bus if not isinstance(_, QUSBBus)]
        _bus.append(QUSBBus(8, self.busid, self.type, device.get_aid(),
                            str(addr[0])))
        device.child_bus = _bus

    def _set_device_props(self, device, addr):
        """ in case this is usb-hub update the child port_prefix """
        if addr[0] or addr[0] is 0:
            if self.__port_prefix:
                addr = ['%s.%s' % (self.__port_prefix, addr[0])]
        self.__hook_child_bus(device, addr)
        super(QUSBBus, self)._set_device_props(device, addr)

    def _update_device_props(self, device, addr):
        """ in case this is usb-hub update the child port_prefix """
        self._set_device_props(device, addr)


class QDriveBus(QSparseBus):

    """
    QDrive bus representation (single slot, drive=...)
    """

    def __init__(self, busid, aobject=None):
        """
        :param busid: id of the bus (pci.0)
        :param aobject: Related autotest object (image1)
        """
        super(QDriveBus, self).__init__('drive', [[], []], busid, 'QDrive',
                                        aobject)

    def get_free_slot(self, addr_pattern):
        """ Use only drive as slot """
        if 'drive' in self.bus:
            return None
        else:
            return True

    @staticmethod
    def _addr2stor(addr):
        """ address is always drive """
        return 'drive'

    def _update_device_props(self, device, addr):
        """
        Always set -drive property, it's mandatory. Also for hotplug purposes
        store this bus device into hook variable of the device.
        """
        self._set_device_props(device, addr)
        if hasattr(device, 'hook_drive_bus'):
            device.hook_drive_bus = self.get_device()


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


class QPCIBus(QSparseBus):

    """
    PCI Bus representation (bus&addr, uses hex digits)
    """

    def __init__(self, busid, bus_type, aobject=None, length=32, first_port=0):
        """ bus&addr, 32 slots """
        super(QPCIBus, self).__init__('bus', [['addr', 'func'], [length, 8]],
                                      busid, bus_type, aobject)
        self.first_port = (first_port, 0)

    @staticmethod
    def _addr2stor(addr):
        """ force all items as hexadecimal values """
        out = ""
        for value in addr:
            if value is None:
                out += '*-'
            else:
                out += '%02x-' % value
        if out:
            return out[:-1]
        else:
            return "*"

    def _dev2addr(self, device):
        """ Read the values in base of 16 (hex) """
        addr = device.get_param('addr')
        if isinstance(addr, int):     # only addr
            return [addr, 0]
        elif not addr:    # not defined
            return [None, 0]
        elif isinstance(addr, str):     # addr or addr.func
            addr = [int(_, 16) for _ in addr.split('.', 1)]
            if len(addr) < 2:   # only addr
                addr.append(0)
        return addr

    def _set_device_props(self, device, addr):
        """ Convert addr to the format used by qtree """
        device.set_param(self.bus_item, self.busid)
        orig_addr = device.get_param('addr')
        if addr[1] or (isinstance(orig_addr, str) and
                       orig_addr.find('.') != -1):
            device.set_param('addr', '%02x.%x' % (addr[0], addr[1]))
        else:
            device.set_param('addr', '%02x' % (addr[0]))

    def _update_device_props(self, device, addr):
        """ Always set properties """
        self._set_device_props(device, addr)

    def _increment_addr(self, addr, last_addr=None):
        """ Don't use multifunction address by default """
        if addr[1] is None:
            addr[1] = 0
        return super(QPCIBus, self)._increment_addr(addr, last_addr=last_addr)


class QPCISwitchBus(QPCIBus):
    """
    PCI Switch bus representation (creates downstream device while inserting
    a device).
    """
    def __init__(self, busid, bus_type, downstream_type, aobject=None):
        super(QPCISwitchBus, self).__init__(busid, bus_type, aobject)
        self.__downstream_ports = {}
        self.__downstream_type = downstream_type

    def add_downstream_port(self, addr):
        """
        Add downstream port of the certain address
        """
        if addr not in self.__downstream_ports:
            bus_id = "%s.%s" % (self.busid, int(addr, 16))
            bus = QPCIBus(bus_id, 'PCIE', bus_id)
            self.__downstream_ports[addr] = bus
            downstream = QDevice(self.__downstream_type,
                                         {'id': bus_id,
                                          'bus': self.busid,
                                          'addr': addr},
                                         aobject=self.aobject,
                                         parent_bus={'busid': '_PCI_CHASSIS'},
                                         child_bus=bus)
            return downstream

    def _insert(self, device, addr):
        """
        Instead of the device inserts the downstream port. The device is
        inserted later during _set_device_props into this downstream port.
        """
        _addr = addr.split('-')[0]
        added_devices = []
        downstream = self.add_downstream_port(_addr)
        if downstream is not None:
            added_devices.append(downstream)
            added_devices.extend(super(QPCISwitchBus, self)._insert(downstream,
                                                                    addr))

        bus_id = "%s.%s" % (self.busid, int(_addr, 16))
        device['bus'] = bus_id

        return added_devices

    def _set_device_props(self, device, addr):
        """
        Instead of setting the addr this insert the device into the
        downstream port.
        """
        self.__downstream_ports['%02x' % addr[0]].insert(device)


class QSCSIBus(QSparseBus):

    """
    SCSI bus representation (bus + 2 leves, don't iterate over lun by default)
    """

    def __init__(self, busid, bus_type, addr_spec, aobject=None, atype=None):
        """
        :param busid: id of the bus (mybus.0)
        :param bus_type: type of the bus (virtio-scsi-pci, lsi53c895a, ...)
        :param addr_spec: Ranges of addr_spec [scsiid_range, lun_range]
        :param aobject: Related autotest object (image1)
        :param atype: Autotest bus type
        :type atype: str
        """
        super(QSCSIBus, self).__init__('bus', [['scsiid', 'lun'], addr_spec],
                                       busid, bus_type, aobject, atype)

    def _increment_addr(self, addr, last_addr=None):
        """
        Qemu doesn't increment lun automatically so don't use it when
        it's not explicitelly specified.
        """
        if addr[1] is None:
            addr[1] = 0
        return super(QSCSIBus, self)._increment_addr(addr, last_addr=last_addr)


class QBusUnitBus(QDenseBus):

    """ Implementation of bus-unit bus (ahci, ide) """

    def __init__(self, busid, bus_type, lengths, aobject=None, atype=None):
        """
        :param busid: id of the bus (mybus.0)
        :type busid: str
        :param bus_type: type of the bus (ahci)
        :type bus_type: str
        :param lenghts: lenghts of [buses, units]
        :type lenghts: list of lists
        :param aobject: Related autotest object (image1)
        :type aobject: str
        :param atype: Autotest bus type
        :type atype: str
        """
        if len(lengths) != 2:
            raise ValueError("len(lenghts) have to be 2 (%s)" % self)
        super(QBusUnitBus, self).__init__('bus', [['bus', 'unit'], lengths],
                                          busid, bus_type, aobject, atype)

    def _update_device_props(self, device, addr):
        """ This bus is compound of m-buses + n-units, update properties """
        if device.get_param('bus'):
            device.set_param('bus', "%s.%s" % (self.busid, addr[0]))
        if device.get_param('unit'):
            device.set_param('unit', addr[1])

    def _set_device_props(self, device, addr):
        """This bus is compound of m-buses + n-units, set properties """
        device.set_param('bus', "%s.%s" % (self.busid, addr[0]))
        device.set_param('unit', addr[1])

    def _check_bus(self, device):
        """ This bus is compound of m-buses + n-units, check correct busid """
        bus = device.get_param('bus')
        if isinstance(bus, str):
            bus = bus.rsplit('.', 1)
            if len(bus) == 2 and bus[0] != self.busid:  # aaa.3
                return False
            elif not bus[0].isdigit() and bus[0] != self.busid:     # aaa
                return False
        return True  # None, 5, '3'

    def _dev2addr(self, device):
        """ This bus is compound of m-buses + n-units, parse addr from dev """
        bus = None
        unit = None
        busid = device.get_param('bus')
        if isinstance(busid, str):
            if busid.isdigit():
                bus = int(busid)
            else:
                busid = busid.rsplit('.', 1)
                if len(busid) == 2 and busid[1].isdigit():
                    bus = int(busid[1])
        if isinstance(busid, int):
            bus = busid
        if device.get_param('unit'):
            unit = int(device.get_param('unit'))
        return [bus, unit]


class QAHCIBus(QBusUnitBus):

    """ AHCI bus (ich9-ahci, ahci) """
    # TODO: Search for 'ide' and 'ahci' buses when strict_mode not specified
    # since qemu doesn't differentiate between those buses.

    def __init__(self, busid, aobject=None):
        """ 6xbus, 2xunit """
        super(QAHCIBus, self).__init__(busid, 'IDE', [6, 1], aobject, 'ahci')

    def _update_device_props(self, device, addr):
        """
        Qemu has problems assigning the ahci disks to ahci bus. We have to
        specify the full address to avoid errors.
        :todo: REMOVE THIS WHEN QEMU STARTS WORKING PROPERLY WITH AHCI
        """
        super(QAHCIBus, self)._set_device_props(device, addr)


class QIDEBus(QBusUnitBus):

    """ IDE bus (piix3-ide) """

    def __init__(self, busid, aobject=None):
        """ 2xbus, 2xunit """
        super(QIDEBus, self).__init__(busid, 'IDE', [2, 2], aobject, 'ide')


class QFloppyBus(QDenseBus):

    """
    Floppy bus (-global isa-fdc.drive?=$drive)
    """

    def __init__(self, busid, aobject=None):
        """ property <= [driveA, driveB] """
        super(QFloppyBus, self).__init__(None, [['property'], [2]], busid,
                                         'floppy', aobject)

    @staticmethod
    def _addr2stor(addr):
        """ translate as drive$CHAR """
        return "drive%s" % chr(65 + addr[0])  # 'A' + addr

    def _dev2addr(self, device):
        """ Read None, number or drive$CHAR and convert to int() """
        addr = device.get_param('property')
        if isinstance(addr, str):
            if addr.startswith('drive') and len(addr) > 5:
                addr = ord(addr[5])
            elif addr.isdigit():
                addr = int(addr)
        return [addr]

    def _update_device_props(self, device, addr):
        """ Always set props """
        self._set_device_props(device, addr)

    def _set_device_props(self, device, addr):
        """ Change value to drive{A,B,...} """
        device.set_param('property', self._addr2stor(addr))


class QOldFloppyBus(QDenseBus):

    """
    Floppy bus (-drive index=n)
    """

    def __init__(self, busid, aobject=None):
        """ property <= [driveA, driveB] """
        super(QOldFloppyBus, self).__init__(None, [['index'], [2]], busid,
                                            'floppy', aobject)

    def _update_device_props(self, device, addr):
        """ Always set props """
        self._set_device_props(device, addr)

    def _set_device_props(self, device, addr):
        """ Change value to drive{A,B,...} """
        device.set_param('index', self._addr2stor(addr))


#
# Device container (device representation of VM)
# This class represents VM by storing all devices and their connections (buses)
#
class DevContainer(object):

    """
    Device container class
    """
    # General methods

    def __init__(self, qemu_binary, vmname, strict_mode="no",
                 workaround_qemu_qmp_crash="no", allow_hotplugged_vm="yes"):
        """
        :param qemu_binary: qemu binary
        :param vm: related VM
        :param strict_mode: Use strict mode (set optional params)
        """
        def get_hmp_cmds(qemu_binary):
            """ :return: list of human monitor commands """
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
            """ :return: list of qmp commands """
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

        self.__state = -1    # -1 synchronized, 0 synchronized after hotplug
        self.__qemu_help = utils.system_output("%s -help" % qemu_binary,
                                               timeout=10, ignore_status=True)
        self.__device_help = utils.system_output("%s -device ? 2>&1"
                                                 % qemu_binary, timeout=10,
                                                 ignore_status=True)
        self.__machine_types = utils.system_output("%s -M ?" % qemu_binary,
                                                   timeout=10, ignore_status=True)
        self.__hmp_cmds = get_hmp_cmds(qemu_binary)
        self.__qmp_cmds = get_qmp_cmds(qemu_binary,
                                       workaround_qemu_qmp_crash == 'always')
        self.vmname = vmname
        self.strict_mode = strict_mode == 'yes'
        self.__devices = []
        self.__buses = []
        self.__qemu_binary = qemu_binary
        self.__execute_qemu_last = None
        self.__execute_qemu_out = ""
        self.allow_hotplugged_vm = allow_hotplugged_vm == 'yes'

    def __getitem__(self, item):
        """
        :param item: autotest id or QObject-like object
        :return: First matching object defined in this QDevContainer
        :raise KeyError: In case no match was found
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
        :param item: autotest id or QObject-like object
        :return: First matching object defined in this QDevContainer or None
        """
        if item in self:
            return self[item]

    def get_by_properties(self, filt):
        """
        Return list of matching devices
        :param filt: filter {'property': 'value', ...}
        :type filt: dict
        """
        out = []
        for device in self.__devices:
            for key, value in filt.iteritems():
                if not hasattr(device, key):
                    break
                if getattr(device, key) != value:
                    break
            else:
                out.append(device)
        return out

    def __delitem__(self, item):
        """
        Delete specified item from devices list
        :param item: autotest id or QObject-like object
        :raise KeyError: In case no match was found
        """
        # Remove child_buses including devices
        if self.remove(item):
            raise KeyError(item)

    def remove(self, device, recursive=True):
        """
        Remove device from this representation
        :param device: autotest id or QObject-like object
        :param recursive: remove children recursively
        :return: None on success, -1 when the device is not present
        """
        device = self[device]
        if not recursive:   # Check if there are no children
            for bus in device.child_bus:
                if len(bus) != 0:
                    raise DeviceRemoveError(device, "Child bus contains "
                                            "devices", self)
        else:               # Recursively remove all devices
            for dev in device.get_children():
                # One child might be already removed from other child's bus
                if dev in self:
                    self.remove(dev, True)
        if device in self.__devices:    # It might be removed from child bus
            for bus in self.__buses:        # Remove from parent_buses
                bus.remove(device)
            for bus in device.child_bus:    # Remove child buses from vm buses
                self.__buses.remove(bus)
            self.__devices.remove(device)   # Remove from list of devices

    def wash_the_device_out(self, device):
        """
        Removes any traces of the device from representation.
        :param device: QBaseDevice device
        """
        # remove device from parent buses
        for bus in self.__buses:
            if device in bus:
                bus.remove(device)
        # remove child devices
        for bus in device.child_bus:
            for dev in device.get_children():
                if dev in self:
                    self.remove(dev, True)
            # remove child_buses from self.__buses
            if bus in self.__buses:
                self.__buses.remove(bus)
        # remove device from self.__devices
        if device in self.__devices:
            self.__devices.remove(device)

    def __len__(self):
        """ :return: Number of inserted devices """
        return len(self.__devices)

    def __contains__(self, item):
        """
        Is specified item defined in current devices list?
        :param item: autotest id or QObject-like object
        :return: True - yes, False - no
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
        if qdev2.get_state() != self.get_state():
            if qdev2.allow_hotplugged_vm:
                if qdev2.get_state() > 0 or self.get_state() > 0:
                    return False
            else:
                return False
        for dev in self:
            if dev not in qdev2:
                return False

        # state, buses and devices are handled earlier
        qdev2 = qdev2.__dict__
        for key, value in self.__dict__.iteritems():
            if key in ("_DevContainer__devices", "_DevContainer__buses",
                       "_DevContainer__state",
                       "allow_hotplugged_vm"):
                continue
            if key not in qdev2 or qdev2[key] != value:
                return False
        return True

    def __ne__(self, qdev2):
        """ Are the VM representation different? """
        return not self.__eq__(qdev2)

    def set_dirty(self):
        """ Increase VM dirtiness (not synchronized with VM) """
        if self.__state >= 0:
            self.__state += 1
        else:
            self.__state = 1

    def set_clean(self):
        """ Decrease VM dirtiness (synchronized with VM) """
        if self.__state > 0:
            self.__state -= 1
        else:
            raise DeviceError("Trying to clean clear VM (probably calling "
                              "hotplug_clean() twice).\n%s" % self.str_long())

    def reset_state(self):
        """
        Mark representation as completely clean, without hotplugged devices.
        """
        self.__state = -1

    def get_state(self):
        """ Get the current state (0 = synchronized with VM) """
        return self.__state

    def get_by_qid(self, qid):
        """
        :param qid: qemu id
        :return: List of items with matching qemu id
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
        if dirty == -1:
            pass
        elif dirty == 0:
            out += "(H)"
        else:
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
        if dirty == -1:
            pass
        elif dirty == 0:
            out += "(H)"
        else:
            out += "(DIRTY%s)" % dirty
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
        :param qid: Original qemu id
        :return: aid (the format is "$qid__%d")
        """
        if qid and qid not in self:
            return qid
        i = 0
        while "%s__%d" % (qid, i) in self:
            i += 1
        return "%s__%d" % (qid, i)

    def has_option(self, option):
        """
        :param option: Desired option
        :return: Is the desired option supported by current qemu?
        """
        return bool(re.search(r"^-%s(\s|$)" % option, self.__qemu_help,
                              re.MULTILINE))

    def has_device(self, device):
        """
        :param device: Desired device
        :return: Is the desired device supported by current qemu?
        """
        return bool(re.search(r'name "%s"' % device, self.__device_help,
                              re.MULTILINE))

    def get_help_text(self):
        """
        :return: Full output of "qemu -help"
        """
        return self.__qemu_help

    def has_hmp_cmd(self, cmd):
        """
        :param cmd: Desired command
        :return: Is the desired command supported by this qemu's human monitor?
        """
        return cmd in self.__hmp_cmds

    def has_qmp_cmd(self, cmd):
        """
        :param cmd: Desired command
        :return: Is the desired command supported by this qemu's QMP monitor?
        """
        return cmd in self.__qmp_cmds

    def execute_qemu(self, options, timeout=5):
        """
        Execute this qemu and return the stdout+stderr output.
        :param options: additional qemu options
        :type options: string
        :param timeout: execution timeout
        :type timeout: int
        :return: Output of the qemu
        :rtype: string
        """
        if self.__execute_qemu_last != options:
            cmd = "%s %s 2>&1" % (self.__qemu_binary, options)
            self.__execute_qemu_out = str(utils.run(cmd, timeout=timeout,
                                                    ignore_status=True,
                                                    verbose=False).stdout)
        return self.__execute_qemu_out

    def get_buses(self, bus_spec, type_test=False):
        """
        :param bus_spec: Bus specification (dictionary)
        :type bus_spec: dict
        :param atype: Match qemu and atype params
        :type atype: bool
        :return: All matching buses
        :rtype: List of QSparseBus
        """
        buses = []
        for bus in self.__buses:
            if bus.match_bus(bus_spec, type_test):
                buses.append(bus)
        return buses

    def get_first_free_bus(self, bus_spec, addr):
        """
        :param bus_spec: Bus specification (dictionary)
        :param addr: Desired address
        :return: First matching bus with free desired address (the latest
                 added matching bus)
        """
        buses = self.get_buses(bus_spec)
        for bus in buses:
            _ = bus.get_free_slot(addr)
            if _ is not None and _ is not False:
                return bus

    def insert(self, devices):
        """
        Inserts devices into this VM representation
        :param devices: List of QBaseDevice devices
        :raise DeviceError: On failure. The representation remains unchanged.
        """
        def cleanup():
            """ Remove all added devices (on failure) """
            for device in added:
                self.wash_the_device_out(device)

        if not isinstance(devices, list):
            devices = [devices]

        added = []
        for device in devices:
            try:
                added.extend(self._insert(device))
            except DeviceError, details:
                cleanup()
                raise DeviceError("%s\nError occured while inserting device %s"
                                  " (%s). Please check the log for details."
                                  % (details, device, devices))
        return added

    def _insert(self, device):
        """
        Inserts device into this VM representation
        :param device: QBaseDevice device
        :raise DeviceError: On failure. The representation remains unchanged.

        1)  get list of matching parent buses
        2)  try to find matching bus+address
        2b) add bus required additional devices prior to adding this device
        3)  add child buses
        4)  append into self.devices
        """
        def clean(device, added_devices):
            """ Remove all inserted devices (on failure) """
            self.wash_the_device_out(device)
            for device in added_devices:
                self.wash_the_device_out(device)

        added_devices = []
        if device.parent_bus is not None and not isinstance(device.parent_bus,
                                                            (list, tuple)):
            # it have to be list of parent buses
            device.parent_bus = (device.parent_bus,)
        for parent_bus in device.parent_bus:
            # type, aobject, busid
            if parent_bus is None:
                continue
            # 1
            buses = self.get_buses(parent_bus, True)
            if not buses:
                err = "ParentBus(%s): No matching bus\n" % parent_bus
                clean(device, added_devices)
                raise DeviceInsertError(device, err, self)
            bus_returns = []
            strict_mode = self.strict_mode
            for bus in buses:   # 2
                if not bus.match_bus(parent_bus, False):
                    # First available bus in qemu is not of the same type as
                    # we in autotest require. Force strict mode to get this
                    # device into the correct bus (ide-hd could go into ahci
                    # and ide hba, qemu doesn't care, autotest does).
                    strict_mode = True
                    bus_returns.append(-1)  # Don't use this bus
                    continue
                bus_returns.append(bus.insert(device, strict_mode))
                if isinstance(bus_returns[-1], list):   # we are done
                    # The bus might require additional devices plugged first
                    try:
                        added_devices.extend(self.insert(bus_returns[-1]))
                    except DeviceError, details:
                        err = ("Can't insert device %s because additional "
                               "device required by bus %s failed to be "
                               "inserted with:\n%s" % (device, bus, details))
                        clean(device, added_devices)
                        raise DeviceError(err)
                    break
            if isinstance(bus_returns[-1], list):   # we are done
                continue
            err = "ParentBus(%s): No free matching bus\n" % parent_bus
            clean(device, added_devices)
            raise DeviceInsertError(device, err, self)
        # 3
        for bus in device.child_bus:
            self.__buses.insert(0, bus)
        # 4
        if device.get_qid() and self.get_by_qid(device.get_qid()):
            err = "Devices qid %s already used in VM\n" % device.get_qid()
            clean(device, added_devices)
            raise DeviceInsertError(device, err, self)
        device.set_aid(self.__create_unique_aid(device.get_qid()))
        self.__devices.append(device)
        added_devices.append(device)
        return added_devices

    def simple_hotplug(self, device, monitor):
        """
        Function hotplug device to devices representation. If verification is
        supported by hodplugged device and result of verification is True
        then it calls set_clean. Otherwise it don't call set_clean because
        devices representatio don't know if device is added correctly.

        :param device: Device which should be unplugged.
        :type device: string, QDevice.
        :param monitor: Monitor from vm.
        :type monitor: qemu_monitor.Monitor
        :return: tuple(monitor.cmd(), verify_hotplug output)
        """
        self.set_dirty()

        out = device.hotplug(monitor)
        ver_out = device.verify_hotplug(out, monitor)

        if ver_out is False:
            self.set_clean()
            return out, ver_out

        qdev_out = None
        try:
            qdev_out = self.insert(device)
            if not isinstance(qdev_out, list) or len(qdev_out) != 1:
                raise NotImplementedError("This device %s require to hotplug "
                                          "multiple devices %s, which is not "
                                          "supported." % (device, out))
            if ver_out is True:
                self.set_clean()
        except DeviceError, exc:
            self.set_clean()  # qdev remains consistent
            raise DeviceHotplugError(device, 'According to qemu_device: %s'
                                     % exc, self)
        out = device.hotplug(monitor)

        return out, ver_out

    def simple_unplug(self, device, monitor):
        """
        Function unplug device to devices representation. If verification is
        supported by unplugged device and result of verification is True
        then it calls set_clean. Otherwise it don't call set_clean because
        devices representatio don't know if device is added correctly.

        :param device: Device which should be unplugged.
        :type device: string, QDevice.
        :param monitor: Monitor from vm.
        :type monitor: qemu_monitor.Monitor
        :return: tuple(monitor.cmd(), verify_unplug output)
        """
        device = self[device]
        self.set_dirty()
        # Remove all devices, which are removed together with this dev
        out = device.unplug(monitor)

        ver_out = device.verify_unplug(out, monitor)

        if ver_out is False:
            self.set_clean()
            return out, ver_out

        try:
            device.unplug_hook()
            self.remove(device, True)
            if ver_out is True:
                self.set_clean()
            elif out is False:
                raise DeviceUnplugError(device, "Device wasn't unplugged in "
                                        "qemu, but it was unplugged in device "
                                        "representation.", self)
        except (DeviceError, KeyError), exc:
            device.unplug_unhook()
            raise DeviceUnplugError(device, exc, self)

        return out, ver_out

    def hotplug_verified(self):
        """
        This function should be used after you verify, that hotplug was
        successful. For each hotplug call, hotplug_verified have to be
        executed in order to mark VM as clear.
        @warning: If you can't verify, that hotplug was successful, don't
                  use this function! You could screw-up following tests.
        """
        self.set_clean()

    def list_missing_named_buses(self, bus_pattern, bus_type, bus_count):
        """
        :param bus_pattern: Bus name pattern with 1x%s for idx or %s is
                            appended in the end. ('mybuses' or 'my%sbus').
        :param bus_type: Type of the bus.
        :param bus_count: Desired number of buses.
        :return: List of buses, which are missing in range(bus_count)
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
        :param bus_pattern: Bus name prefix without %s and tailing digit
        :return: Name of the next bus (integer is appended and incremented
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
        :return: cmdline of all devices (without qemu-cmd itself)
        """
        out = ""
        for device in self.__devices:
            _out = device.cmdline()
            if _out:
                out += " %s" % _out
        if out:
            return out[1:]

    def hook_fill_scsi_hbas(self, params):
        """
        This hook creates dummy scsi hba per 7 -drive 'scsi' devices.
        """
        i = 6   # We are going to divide it by 7 so 6 will result in 0
        for image_name in params.objects("images"):
            _is_oldscsi = (params.object_params(image_name).get('drive_format')
                           == 'scsi')
            _scsi_without_device = (not self.has_option('device') and
                                    params.object_params(image_name)
                                    .get('drive_format', 'virtio_blk')
                                    .startswith('scsi'))
            if _is_oldscsi or _scsi_without_device:
                i += 1

        for image_name in params.objects("cdroms"):
            _is_oldscsi = (params.object_params(image_name).get('cd_format')
                           == 'scsi')
            _scsi_without_device = (not self.has_option('device') and
                                    params.object_params(image_name)
                                    .get('cd_format', 'virtio_blk')
                                    .startswith('scsi'))
            if _is_oldscsi or _scsi_without_device:
                i += 1

        for i in xrange(i / 7):     # Autocreated lsi hba
            if arch.ARCH == 'ppc64':
                _name = 'spapr-vscsi%s' % i
                bus = QSCSIBus("scsi.0", 'SCSI', [8, 16384],
                               atype='spapr-vscsi')
                self.insert(QStringDevice(_name,
                                          parent_bus={'aobject':
                                                      params.get('pci_bus',
                                                                 'pci.0')},
                            child_bus=bus))
            else:
                _name = 'lsi53c895a%s' % i
                bus = QSCSIBus("scsi.0", 'SCSI', [8, 16384], atype='lsi53c895a')
                self.insert(QStringDevice(_name,
                                          parent_bus={'aobject':
                                                      params.get('pci_bus',
                                                                 'pci.0')},
                                          child_bus=bus))

    # Machine related methods
    def machine_by_params(self, params=None):
        """
        Choose the used machine and set the default devices accordingly
        :param params: VM params
        :return: List of added devices (including default buses)
        """
        def machine_q35(cmd=False):
            """
            Q35 + ICH9
            :param cmd: If set uses "-M $cmd" to force this machine type
            :return: List of added devices (including default buses)
            """
            # TODO: Add all supported devices (AHCI, ...) and
            # verify that PCIE works as pci bus (ranges, etc...)
            logging.warn('Using Q35 machine which is not yet fullytested on '
                         'virt-test. False errors might occur.')
            devices = []
            bus = (QPCIBus('pcie.0', 'PCIE', 'pci.0'),
                   QStrictCustomBus(None, [['chassis'], [256]], '_PCI_CHASSIS',
                                    first_port=1),
                   QStrictCustomBus(None, [['chassis_nr'], [256]],
                                    '_PCI_CHASSIS_NR', first_port=1))
            devices.append(QStringDevice('machine', cmdline=cmd,
                                         child_bus=bus,
                                         aobject="pci.0"))
            devices.append(QStringDevice('mch', {'addr': 0},
                                         parent_bus={'aobject': 'pci.0'}))
            devices.append(QStringDevice('ICH9-ahci', {'addr': '0x1f'},
                                         parent_bus={'aobject': 'pci.0'},
                                         child_bus=QAHCIBus('ide')))
            if self.has_option('device') and self.has_option("global"):
                devices.append(QStringDevice('fdc',
                                             child_bus=QFloppyBus('floppy')))
            else:
                devices.append(QStringDevice('fdc',
                                             child_bus=QOldFloppyBus('floppy'))
                               )
            return devices

        def machine_i440FX(cmd=False):
            """
            i440FX + PIIX
            :param cmd: If set uses "-M $cmd" to force this machine type
            :return: List of added devices (including default buses)
            """
            devices = []
            if arch.ARCH == 'ppc64':
                pci_bus = "pci"
            else:
                pci_bus = "pci.0"
            bus = (QPCIBus(pci_bus, 'PCI', 'pci.0'),
                   QStrictCustomBus(None, [['chassis'], [256]], '_PCI_CHASSIS',
                                    first_port=1),
                   QStrictCustomBus(None, [['chassis_nr'], [256]],
                                    '_PCI_CHASSIS_NR', first_port=1))
            devices.append(QStringDevice('machine', cmdline=cmd,
                                         child_bus=bus,
                                         aobject="pci.0"))
            devices.append(QStringDevice('i440FX', {'addr': 0},
                                         parent_bus={'aobject': 'pci.0'}))
            devices.append(QStringDevice('PIIX3', {'addr': 1},
                                         parent_bus={'aobject': 'pci.0'}))
            devices.append(QStringDevice('ide', child_bus=QIDEBus('ide')))
            if self.has_option('device') and self.has_option("global"):
                devices.append(QStringDevice('fdc',
                                             child_bus=QFloppyBus('floppy')))
            else:
                devices.append(QStringDevice('fdc',
                                             child_bus=QOldFloppyBus('floppy'))
                               )
            return devices

        def machine_other(cmd=False):
            """
            isapc or unknown machine type. This type doesn't add any default
            buses or devices, only sets the cmdline.
            :param cmd: If set uses "-M $cmd" to force this machine type
            :return: List of added devices (including default buses)
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
            devices = None
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
            if not devices:
                logging.warn("Unable to find the default machine type, using"
                             "i440FX.")
                devices = machine_i440FX(False)

        # reserve pci.0 addresses
        pci_params = params.object_params('pci.0')
        reserved = pci_params.get('reserved_slots', '').split()
        if reserved:
            for bus in self.__buses:
                if bus.aobject == "pci.0":
                    for addr in reserved:
                        bus.reserve(hex(int(addr)))
                    break
        return devices

    # USB Controller related methods
    def usbc_by_variables(self, usb_id, usb_type, multifunction=False,
                          masterbus=None, firstport=None, freq=None,
                          max_ports=6, pci_addr=None, pci_bus='pci.0'):
        """
        Creates usb-controller devices by variables
        :param usb_id: Usb bus name
        :param usb_type: Usb bus type
        :param multifunction: Is the bus multifunction
        :param masterbus: Is this bus master?
        :param firstport: Offset of the first port
        :param freq: Bus frequency
        :param max_ports: How many ports this bus have [6]
        :param pci_addr: Desired PCI address
        :return: List of QDev devices
        """
        if not self.has_option("device"):
            # Okay, for the archaic qemu which has not device parameter,
            # just return a usb uhci controller.
            # If choose this kind of usb controller, it has no name/id,
            # and only can be created once, so give it a special name.
            usb = QStringDevice("oldusb", cmdline="-usb",
                                child_bus=QUSBBus(2, 'usb.0', 'uhci', usb_id))
            return [usb]

        if not self.has_device(usb_type):
            raise error.TestNAError("usb controller %s not available"
                                    % usb_type)

        usb = QDevice(usb_type, {}, usb_id, {'aobject': pci_bus},
                      QUSBBus(max_ports, '%s.0' % usb_id, usb_type, usb_id))
        new_usbs = [usb]    # each usb dev might compound of multiple devs
        # TODO: Add 'bus' property (it was not in the original version)
        usb.set_param('id', usb_id)
        usb.set_param('masterbus', masterbus)
        usb.set_param('multifunction', multifunction)
        usb.set_param('firstport', firstport)
        usb.set_param('freq', freq)
        usb.set_param('addr', pci_addr)

        if usb_type == "ich9-usb-ehci1":
            usb.set_param('addr', '1d.7')
            usb.set_param('multifunction', 'on')
            for i in xrange(3):
                new_usbs.append(QDevice('ich9-usb-uhci%d' % (i + 1), {},
                                        usb_id))
                new_usbs[-1].parent_bus = {'aobject': pci_bus}
                new_usbs[-1].set_param('id', '%s.%d' % (usb_id, i))
                new_usbs[-1].set_param('multifunction', 'on')
                new_usbs[-1].set_param('masterbus', '%s.0' % usb_id)
                # current qemu_devices doesn't support x.y addr. Plug only
                # the 0th one into this representation.
                new_usbs[-1].set_param('addr', '1d.%d' % (2 * i))
                new_usbs[-1].set_param('firstport', 2 * i)
        return new_usbs

    def usbc_by_params(self, usb_name, params):
        """
        Wrapper for creating usb bus from autotest usb params.
        :param usb_name: Name of the usb bus
        :param params: USB params (params.object_params(usb_name))
        :return: List of QDev devices
        """
        return self.usbc_by_variables(usb_name,
                                      params.get('usb_type'),
                                      params.get('multifunction'),
                                      params.get('masterbus'),
                                      params.get('firstport'),
                                      params.get('freq'),
                                      params.get('max_ports', 6),
                                      params.get('pci_addr'),
                                      params.get('pci_bus', 'pci.0'))

    # USB Device related methods
    def usb_by_variables(self, usb_name, usb_type, controller_type, bus=None,
                         port=None):
        """
        Creates usb-devices by variables.
        :param usb_name: usb name
        :param usb_type: usb type (usb-tablet, usb-serial, ...)
        :param controller_type: type of the controller (uhci, ehci, xhci, ...)
        :param bus: the bus name (my_bus.0, ...)
        :param port: port specifiacation (4, 4.1.2, ...)
        :return: QDev device
        """
        if not self.has_device(usb_type):
            raise error.TestNAError("usb device %s not available"
                                    % usb_type)
        if self.has_option('device'):
            device = QDevice(usb_type, aobject=usb_name)
            device.set_param('id', 'usb-%s' % usb_name)
            device.set_param('bus', bus)
            device.set_param('port', port)
            device.parent_bus += ({'type': controller_type},)
        else:
            if "tablet" in usb_type:
                device = QStringDevice('usb-%s' % usb_name,
                                       cmdline='-usbdevice %s' % usb_name)
            else:
                device = QStringDevice('missing-usb-%s' % usb_name)
                logging.error("This qemu supports only tablet device; ignoring"
                              " %s", usb_name)
        return device

    def usb_by_params(self, usb_name, params):
        """
        Wrapper for creating usb devices from autotest params.
        :param usb_name: Name of the usb
        :param params: USB device's params
        :return: QDev device
        """
        return self.usb_by_variables(usb_name,
                                     params.get("usb_type"),
                                     params.get("usb_controller"),
                                     params.get("bus"),
                                     params.get("port"))

    # Images (disk, cdrom, floppy) device related methods
    def images_define_by_variables(self, name, filename, index=None, fmt=None,
                                   cache=None, werror=None, rerror=None, serial=None,
                                   snapshot=None, boot=None, blkdebug=None, bus=None,
                                   unit=None, port=None, bootindex=None, removable=None,
                                   min_io_size=None, opt_io_size=None,
                                   physical_block_size=None, logical_block_size=None,
                                   readonly=None, scsiid=None, lun=None, aio=None,
                                   strict_mode=None, media=None, imgfmt=None,
                                   pci_addr=None, scsi_hba=None, x_data_plane=None,
                                   blk_extra_params=None, scsi=None,
                                   pci_bus='pci.0'):
        """
        Creates related devices by variables
        :note: To skip the argument use None, to disable it use False
        :note: Strictly bool options accept "yes", "on" and True ("no"...)
        :param name: Autotest name of this disk
        :param filename: Path to the disk file
        :param index: drive index (used for generating names)
        :param fmt: drive subsystem type (ide, scsi, virtio, usb2, ...)
        :param cache: disk cache (none, writethrough, writeback)
        :param werror: What to do when write error occurs (stop, ...)
        :param rerror: What to do when read error occurs (stop, ...)
        :param serial: drive serial number ($string)
        :param snapshot: use snapshot? ($bool)
        :param boot: is bootable? ($bool)
        :param blkdebug: use blkdebug (None, blkdebug_filename)
        :param bus: 1st level of disk location (index of bus) ($int)
        :param unit: 2nd level of disk location (unit/scsiid/...) ($int)
        :param port: 3rd level of disk location (port/lun/...) ($int)
        :param bootindex: device boot priority ($int)
        :param removable: can the drive be removed? ($bool)
        :param min_io_size: Min allowed io size
        :param opt_io_size: Optimal io size
        :param physical_block_size: set physical_block_size ($int)
        :param logical_block_size: set logical_block_size ($int)
        :param readonly: set the drive readonly ($bool)
        :param scsiid: Deprecated 2nd level of disk location (&unit)
        :param lun: Deprecated 3rd level of disk location (&port)
        :param aio: set the type of async IO (native, threads, ..)
        :param strict_mode: enforce optional parameters (address, ...) ($bool)
        :param media: type of the media (disk, cdrom, ...)
        :param imgfmt: image format (qcow2, raw, ...)
        :param pci_addr: drive pci address ($int)
        :param scsi_hba: Custom scsi HBA
        """
        def define_hbas(qtype, atype, bus, unit, port, qbus, addr_spec=None,
                        pci_bus='pci.0'):
            """
            Helper for creating HBAs of certain type.
            """
            devices = []
            if qbus == QAHCIBus:    # AHCI uses multiple ports, id is different
                _hba = 'ahci%s'
            else:
                _hba = atype.replace('-', '_') + '%s.0'  # HBA id
            _bus = bus
            if bus is None:
                bus = self.get_first_free_bus({'type': qtype, 'atype': atype},
                                              [unit, port])
                if bus is None:
                    bus = self.idx_of_next_named_bus(_hba)
                else:
                    bus = bus.busid
            if isinstance(bus, int):
                for bus_name in self.list_missing_named_buses(
                        _hba, qtype, bus + 1):
                    _bus_name = bus_name.rsplit('.')[0]
                    if addr_spec:
                        dev = QDevice(params={'id': _bus_name,
                                              'driver': atype},
                                      parent_bus={'aobject': pci_bus},
                                      child_bus=qbus(busid=bus_name,
                                                     bus_type=qtype,
                                                     addr_spec=addr_spec,
                                                     atype=atype))
                    else:
                        dev = QDevice(params={'id': _bus_name,
                                              'driver': atype},
                                      parent_bus={'aobject': pci_bus},
                                      child_bus=qbus(busid=bus_name))
                    devices.append(dev)
                bus = _hba % bus
            if qbus == QAHCIBus and unit is not None:
                bus += ".%d" % unit
            elif _bus is None:    # If bus was not set, don't set it
                bus = None
            return devices, bus, {'type': qtype, 'atype': atype}

        #
        # Parse params
        #
        devices = []    # All related devices

        use_device = self.has_option("device")
        if fmt == "scsi":   # fmt=scsi force the old version of devices
            logging.warn("'scsi' drive_format is deprecated, please use the "
                         "new lsi_scsi type for disk %s", name)
            use_device = False
        if not fmt:
            use_device = False
        if fmt == 'floppy' and not self.has_option("global"):
            use_device = False

        if strict_mode is None:
            strict_mode = self.strict_mode
        if strict_mode:     # Force default variables
            if cache is None:
                cache = "none"
            if removable is None:
                removable = "yes"
            if aio is None:
                aio = "native"
            if media is None:
                media = "disk"
        else:       # Skip default variables
            imgfmt = None
            if media != 'cdrom':    # ignore only 'disk'
                media = None

        if not ("[,boot=on|off]" in self.get_help_text()):
            if boot in ('yes', 'on', True):
                bootindex = "1"
            boot = None

        bus = none_or_int(bus)     # First level
        unit = none_or_int(unit)   # Second level
        port = none_or_int(port)   # Third level
        # Compatibility with old params - scsiid, lun
        if scsiid is not None:
            logging.warn("drive_scsiid param is obsolete, use drive_unit "
                         "instead (disk %s)", name)
            unit = none_or_int(scsiid)
        if lun is not None:
            logging.warn("drive_lun param is obsolete, use drive_port instead "
                         "(disk %s)", name)
            port = none_or_int(lun)
        if pci_addr is not None and fmt == 'virtio':
            logging.warn("drive_pci_addr is obsolete, use drive_bus instead "
                         "(disk %s)", name)
            bus = none_or_int(pci_addr)

        #
        # HBA
        # fmt: ide, scsi, virtio, scsi-hd, ahci, usb1,2,3 + hba
        # device: ide-drive, usb-storage, scsi-hd, scsi-cd, virtio-blk-pci
        # bus: ahci, virtio-scsi-pci, USB
        #
        if not use_device:
            if fmt and (fmt == "scsi" or (fmt.startswith('scsi') and
                                         (scsi_hba == 'lsi53c895a' or
                                          scsi_hba == 'spapr-vscsi'))):
                if not (bus is None and unit is None and port is None):
                    logging.warn("Using scsi interface without -device "
                                 "support; ignoring bus/unit/port. (%s)", name)
                    bus, unit, port = None, None, None
                # In case we hotplug, lsi wasn't added during the startup hook
                if arch.ARCH == 'ppc64':
                    _ = define_hbas('SCSI', 'spapr-vscsi', None, None, None,
                                    QSCSIBus, [8, 16384])
                else:
                    _ = define_hbas('SCSI', 'lsi53c895a', None, None, None,
                                    QSCSIBus, [8, 16384])
                devices.extend(_[0])
        elif fmt == "ide":
            if bus:
                logging.warn('ide supports only 1 hba, use drive_unit to set'
                             'ide.* for disk %s', name)
            bus = unit
            dev_parent = {'type': 'IDE', 'atype': 'ide'}
        elif fmt == "ahci":
            devs, bus, dev_parent = define_hbas('IDE', 'ahci', bus, unit, port,
                                                QAHCIBus)
            devices.extend(devs)
        elif fmt.startswith('scsi-'):
            if not scsi_hba:
                scsi_hba = "virtio-scsi-pci"
            addr_spec = None
            if scsi_hba == 'lsi53c895a' or scsi_hba == 'spapr-vscsi':
                addr_spec = [8, 16384]
            elif scsi_hba == 'virtio-scsi-pci':
                addr_spec = [256, 16384]
            _, bus, dev_parent = define_hbas('SCSI', scsi_hba, bus, unit, port,
                                             QSCSIBus, addr_spec)
            devices.extend(_)
        elif fmt in ('usb1', 'usb2', 'usb3'):
            if bus:
                logging.warn('Manual setting of drive_bus is not yet supported'
                             ' for usb disk %s', name)
                bus = None
            if fmt == 'usb1':
                dev_parent = {'type': 'uhci'}
            elif fmt == 'usb2':
                dev_parent = {'type': 'ehci'}
            elif fmt == 'usb3':
                dev_parent = {'type': 'xhci'}
        elif fmt == 'virtio':
            dev_parent = {'aobject': pci_bus}
        else:
            dev_parent = {'type': fmt}

        #
        # Drive
        # -drive fmt or -drive fmt=none -device ...
        #
        # TODO: Add QRHDrive and PCIDrive for hotplug purposes
        # TODO: Add special parameter to override the drive method
        if self.has_hmp_cmd('__com.redhat_drive_add') and use_device:
            devices.append(QRHDrive(name))
        elif self.has_hmp_cmd('drive_add') and use_device:
            devices.append(QHPDrive(name))
        else:
            devices.append(QDrive(name, use_device))
        devices[-1].set_param('if', 'none')
        devices[-1].set_param('cache', cache)
        devices[-1].set_param('rerror', rerror)
        devices[-1].set_param('werror', werror)
        devices[-1].set_param('serial', serial)
        devices[-1].set_param('boot', boot, bool)
        devices[-1].set_param('snapshot', snapshot, bool)
        devices[-1].set_param('readonly', readonly, bool)
        if 'aio' in self.get_help_text():
            devices[-1].set_param('aio', aio)
        devices[-1].set_param('media', media)
        devices[-1].set_param('format', imgfmt)
        if blkdebug is not None:
            devices[-1].set_param('file', 'blkdebug:%s:%s' % (blkdebug,
                                                              filename))
        else:
            devices[-1].set_param('file', filename)
        if not use_device:
            if fmt and fmt.startswith('scsi-'):
                if scsi_hba == 'lsi53c895a' or scsi_hba == 'spapr-vscsi':
                    fmt = 'scsi'  # Compatibility with the new scsi
            if fmt and fmt not in ('ide', 'scsi', 'sd', 'mtd', 'floppy',
                                   'pflash', 'virtio'):
                raise virt_vm.VMDeviceNotSupportedError(self.vmname,
                                                        fmt)
            devices[-1].set_param('if', fmt)    # overwrite previously set None
            if not fmt:     # When fmt unspecified qemu uses ide
                fmt = 'ide'
            devices[-1].set_param('index', index)
            if fmt == 'ide':
                devices[-1].parent_bus = ({'type': fmt.upper(), 'atype': fmt},)
            elif fmt == 'scsi':
                if arch.ARCH == 'ppc64':
                    devices[-1].parent_bus = ({'atype': 'spapr-vscsi',
                                               'type': 'SCSI'},)
                else:
                    devices[-1].parent_bus = ({'atype': 'lsi53c895a',
                                               'type': 'SCSI'},)
            elif fmt == 'floppy':
                devices[-1].parent_bus = ({'type': fmt},)
            elif fmt == 'virtio':
                devices[-1].set_param('addr', pci_addr)
                devices[-1].parent_bus = ({'aobject': pci_bus},)
            if not media == 'cdrom':
                logging.warn("Using -drive fmt=xxx for %s is unsupported "
                             "method, false errors might occur.", name)
            return devices

        #
        # Device
        #
        devices.append(QDevice(params={}, aobject=name))
        devices[-1].parent_bus += ({'busid': 'drive_%s' % name}, dev_parent)
        if fmt in ("ide", "ahci"):
            if not self.has_device('ide-hd'):
                devices[-1].set_param('driver', 'ide-drive')
            elif media == 'cdrom':
                devices[-1].set_param('driver', 'ide-cd')
            else:
                devices[-1].set_param('driver', 'ide-hd')
            devices[-1].set_param('unit', port)
        elif fmt and fmt.startswith('scsi-'):
            devices[-1].set_param('driver', fmt)
            devices[-1].set_param('scsi-id', unit)
            devices[-1].set_param('lun', port)
            devices[-1].set_param('removable', removable, bool)
            if strict_mode:
                devices[-1].set_param('channel', 0)
        elif fmt == 'virtio':
            devices[-1].set_param('driver', 'virtio-blk-pci')
            devices[-1].set_param("scsi", scsi, bool)
            if bus is not None:
                devices[-1].set_param('addr', hex(bus))
        elif fmt in ('usb1', 'usb2', 'usb3'):
            devices[-1].set_param('driver', 'usb-storage')
            devices[-1].set_param('port', unit)
            devices[-1].set_param('removable', removable, bool)
        elif fmt == 'floppy':
            # Overwrite QDevice with QFloppy
            devices[-1] = QFloppy(unit, 'drive_%s' % name, name,
                                  ({'busid': 'drive_%s' % name}, {'type': fmt}))
        else:
            logging.warn('Using default device handling (disk %s)', name)
            devices[-1].set_param('driver', fmt)
        # Get the supported options
        options = self.execute_qemu("-device %s,?" % devices[-1]['driver'])
        devices[-1].set_param('id', name)
        devices[-1].set_param('bus', bus)
        devices[-1].set_param('drive', 'drive_%s' % name)
        devices[-1].set_param('logical_block_size', logical_block_size)
        devices[-1].set_param('physical_block_size', physical_block_size)
        devices[-1].set_param('min_io_size', min_io_size)
        devices[-1].set_param('opt_io_size', opt_io_size)
        devices[-1].set_param('bootindex', bootindex)
        devices[-1].set_param('x-data-plane', x_data_plane, bool)
        if 'serial' in options:
            devices[-1].set_param('serial', serial)
            devices[-2].set_param('serial', None)   # remove serial from drive
        if blk_extra_params:
            blk_extra_params = (_.split('=', 1) for _ in
                                blk_extra_params.split(',') if _)
            for key, value in blk_extra_params:
                devices[-1].set_param(key, value)

        return devices

    def images_define_by_params(self, name, image_params, media=None,
                                index=None, image_boot=None,
                                image_bootindex=None):
        """
        Wrapper for creating disks and related hbas from autotest image params.
        :note: To skip the argument use None, to disable it use False
        :note: Strictly bool options accept "yes", "on" and True ("no"...)
        :note: Options starting with '_' are optional and used only when
               strict_mode is True
        :param name: Name of the new disk
        :param params: Disk params (params.object_params(name))
        """
        shared_dir = os.path.join(data_dir.get_data_dir(), "shared")
        return self.images_define_by_variables(name,
                                               storage.get_image_filename(
                                                   image_params,
                                                   data_dir.get_data_dir()),
                                               index,
                                               image_params.get(
                                                   "drive_format"),
                                               image_params.get("drive_cache"),
                                               image_params.get(
                                                   "drive_werror"),
                                               image_params.get(
                                                   "drive_rerror"),
                                               image_params.get(
                                                   "drive_serial"),
                                               image_params.get(
                                                   "image_snapshot"),
                                               image_boot,
                                               storage.get_image_blkdebug_filename(
                                                   image_params,
                                                   shared_dir),
                                               image_params.get("drive_bus"),
                                               image_params.get("drive_unit"),
                                               image_params.get("drive_port"),
                                               image_bootindex,
                                               image_params.get("removable"),
                                               image_params.get("min_io_size"),
                                               image_params.get("opt_io_size"),
                                               image_params.get(
                                                   "physical_block_size"),
                                               image_params.get(
                                                   "logical_block_size"),
                                               image_params.get(
                                                   "image_readonly"),
                                               image_params.get(
                                                   "drive_scsiid"),
                                               image_params.get("drive_lun"),
                                               image_params.get("image_aio"),
                                               image_params.get(
                                                   "strict_mode") == "yes",
                                               media,
                                               image_params.get(
                                                   "image_format"),
                                               image_params.get(
                                                   "drive_pci_addr"),
                                               image_params.get("scsi_hba"),
                                               image_params.get(
                                                   "x-data-plane"),
                                               image_params.get(
                                                   "blk_extra_params"),
                                               image_params.get("virtio-blk-pci_scsi"),
                                               image_params.get('pci_bus', 'pci.0'))

    def cdroms_define_by_params(self, name, image_params, media=None,
                                index=None, image_boot=None,
                                image_bootindex=None):
        """
        Wrapper for creating cdrom and related hbas from autotest image params.
        :note: To skip the argument use None, to disable it use False
        :note: Strictly bool options accept "yes", "on" and True ("no"...)
        :note: Options starting with '_' are optional and used only when
               strict_mode is True
        :param name: Name of the new disk
        :param params: Disk params (params.object_params(name))
        """
        iso = image_params.get('cdrom')
        if iso:
            image_params['image_name'] = os.path.join(data_dir.get_data_dir(),
                                                      image_params.get('cdrom'))
        image_params['image_format'] = None
        shared_dir = os.path.join(data_dir.get_data_dir(), "shared")
        return self.images_define_by_variables(name,
                                               storage.get_image_filename(
                                                   image_params,
                                                   data_dir.get_data_dir()),
                                               index,
                                               image_params.get('cd_format'),
                                               '',     # skip drive_cache
                                               image_params.get(
                                                   "drive_werror"),
                                               image_params.get(
                                                   "drive_rerror"),
                                               image_params.get(
                                                   "drive_serial"),
                                               image_params.get(
                                                   "image_snapshot"),
                                               image_boot,
                                               storage.get_image_blkdebug_filename(
                                                   image_params,
                                                   shared_dir),
                                               image_params.get("drive_bus"),
                                               image_params.get("drive_unit"),
                                               image_params.get("drive_port"),
                                               image_bootindex,
                                               image_params.get("removable"),
                                               image_params.get("min_io_size"),
                                               image_params.get("opt_io_size"),
                                               image_params.get(
                                                   "physical_block_size"),
                                               image_params.get(
                                                   "logical_block_size"),
                                               image_params.get(
                                                   "image_readonly"),
                                               image_params.get(
                                                   "drive_scsiid"),
                                               image_params.get("drive_lun"),
                                               image_params.get("image_aio"),
                                               image_params.get(
                                                   "strict_mode") == "yes",
                                               media,
                                               None,     # skip img_fmt
                                               image_params.get(
                                                   "drive_pci_addr"),
                                               image_params.get("scsi_hba"),
                                               image_params.get(
                                                   "x-data-plane"),
                                               image_params.get(
                                                   "blk_extra_params"),
                                               image_params.get("virtio-blk-pci_scsi"),
                                               image_params.get('pci_bus', 'pci.0'))

    def pcic_by_params(self, name, params):
        """
        Creates pci controller/switch/... based on params
        :param name: Autotest name
        :param params: PCI controller params
        :note: x3130 creates x3130-upstream bus + xio3130-downstream port for
               each inserted device.
        :warning: x3130-upstream device creates only x3130-upstream device
                  and you are responsible for creating the downstream ports.
        """
        driver = params.get('type', 'ioh3420')
        if driver in ('ioh3420', 'x3130-upstream', 'x3130'):
            bus_type = 'PCIE'
        else:
            bus_type = 'PCI'
        parent_bus = [{'aobject': params.get('pci_bus', 'pci.0')}]
        if driver == 'x3130':
            bus = QPCISwitchBus(name, bus_type, 'xio3130-downstream', name)
            driver = 'x3130-upstream'
        else:
            if driver == 'pci-bridge':  # addr 1-19, chasis_nr
                parent_bus.append({'busid': '_PCI_CHASSIS_NR'})
                bus_length = 20
                bus_first_port = 1
            elif driver == 'i82801b11-bridge':  # addr 1-19
                bus_length = 20
                bus_first_port = 1
            else:   # addr = 0-31
                bus_length = 32
                bus_first_port = 0
            bus = QPCIBus(name, bus_type, name, bus_length, bus_first_port)
        for addr in params.get('reserved_slots', '').split():
            bus.reserve(addr)
        return QDevice(driver, {'id': name}, aobject=name,
                       parent_bus=parent_bus,
                       child_bus=bus)
