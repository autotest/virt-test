"""
Virtualization test utility functions.

@copyright: 2008-2009 Red Hat Inc.
"""

import time, string, random, socket, os, signal, re, logging, commands, cPickle
import fcntl, shelve, ConfigParser, sys, UserDict, inspect, tarfile
import struct, shutil, glob, HTMLParser, urllib, traceback, platform
from autotest.client import utils, os_dep
from autotest.client.shared import error, logging_config
from autotest.client.shared import logging_manager, git, cartesian_config

try:
    import koji
    KOJI_INSTALLED = True
except ImportError:
    KOJI_INSTALLED = False

ARCH = platform.machine()
if ARCH == "ppc64":
    # From include/linux/sockios.h
    SIOCSIFHWADDR  = 0x8924
    SIOCGIFHWADDR  = 0x8927
    SIOCSIFFLAGS   = 0x8914
    SIOCGIFINDEX   = 0x8933
    SIOCBRADDIF    = 0x89a2
    SIOCBRDELIF    = 0x89a3
    # From linux/include/linux/if_tun.h
    TUNSETIFF      = 0x800454ca
    TUNGETIFF      = 0x400454d2
    TUNGETFEATURES = 0x400454cf
    IFF_TAP        = 0x2
    IFF_NO_PI      = 0x1000
    IFF_VNET_HDR   = 0x4000
    # From linux/include/linux/if.h
    IFF_UP = 0x1
else:
    # From include/linux/sockios.h
    SIOCSIFHWADDR = 0x8924
    SIOCGIFHWADDR = 0x8927
    SIOCSIFFLAGS  = 0x8914
    SIOCGIFINDEX  = 0x8933
    SIOCBRADDIF   = 0x89a2
    SIOCBRDELIF   = 0x89a3
    # From linux/include/linux/if_tun.h
    TUNSETIFF = 0x400454ca
    TUNGETIFF = 0x800454d2
    TUNGETFEATURES = 0x800454cf
    IFF_TAP = 0x0002
    IFF_NO_PI = 0x1000
    IFF_VNET_HDR = 0x4000
    # From linux/include/linux/if.h
    IFF_UP = 0x1


class Bridge(object):
    def get_structure(self):
        """
        Get bridge list.
        """
        ebr_i = re.compile("^(\S+).*?\s+$", re.MULTILINE)
        br_i = re.compile("^(\S+).*?(\S+)$", re.MULTILINE)
        nbr_i = re.compile("^\s+(\S+)$", re.MULTILINE)
        out_line = (utils.run("brctl show", verbose=False).stdout.splitlines())
        result = dict()
        bridge = None
        iface = None

        for line in out_line[1:]:
            br_line = ebr_i.findall(line)
            if br_line:
                (tmpbr) = br_line[0]
                bridge = tmpbr
                result[bridge] = []
            else:
                br_line = br_i.findall(line)
                if br_line:
                    (tmpbr, iface) = br_i.findall(line)[0]
                    bridge = tmpbr
                    result[bridge] = []
                else:
                    if_line = nbr_i.findall(line)
                    if if_line:
                        iface = if_line[0]

            if iface and iface not in ['yes', 'no']:  # add interface to bridge
                result[bridge].append(iface)

        return result


    def list_br(self):
        return self.get_structure().keys()


    def port_to_br(self, port_name):
        """
        Return bridge which contain port.

        @param port_name: Name of port.
        @return: Bridge name or None if there is no bridge which contain port.
        """
        bridge = None
        for (br, ifaces) in self.get_structure().iteritems():
            if port_name in ifaces:
                bridge = br
        return bridge


    def _br_ioctl(self, io_cmd, brname, ifname):
        ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
        index = if_nametoindex(ifname)
        if index == 0:
            raise TAPNotExistError(ifname)
        ifr = struct.pack("16si", brname, index)
        _ = fcntl.ioctl(ctrl_sock, io_cmd, ifr)
        ctrl_sock.close()


    def add_port(self, brname, ifname):
        """
        Add a device to bridge

        @param ifname: Name of TAP device
        @param brname: Name of the bridge
        """
        try:
            self._br_ioctl(SIOCBRADDIF, brname, ifname)
        except IOError, details:
            raise BRAddIfError(ifname, brname, details)


    def del_port(self, brname, ifname):
        """
        Remove a TAP device from bridge

        @param ifname: Name of TAP device
        @param brname: Name of the bridge
        """
        try:
            self._br_ioctl(SIOCBRDELIF, brname, ifname)
        except IOError, details:
            raise BRDelIfError(ifname, brname, details)


def __init_openvswitch(func):
    """
    Decorator used for late init of __ovs variable.
    """
    def wrap_init(*args, **kargs):
        global __ovs
        if __ovs is None:
            try:
                __ovs = openvswitch.OpenVSwitchSystem()
                __ovs.init_system()
                if (not __ovs.check()):
                    raise Exception("Check of OpenVSwitch failed.")
            except Exception, e:
                logging.debug("System not support OpenVSwitch:")
                logging.debug(e)

        return func(*args, **kargs)
    return wrap_init


#Global variable for OpenVSwitch
__ovs = None
__bridge = Bridge()


def lock_file(filename, mode=fcntl.LOCK_EX):
    f = open(filename, "w")
    fcntl.lockf(f, mode)
    return f


def unlock_file(f):
    fcntl.lockf(f, fcntl.LOCK_UN)
    f.close()


class NetError(Exception):
    pass


class TAPModuleError(NetError):
    def __init__(self, devname, action="open", details=None):
        NetError.__init__(self, devname)
        self.devname = devname
        self.details = details

    def __str__(self):
        e_msg = "Can't %s %s" % (self.action, self.devname)
        if self.details is not None:
            e_msg += " : %s" % self.details
        return e_msg


class TAPNotExistError(NetError):
    def __init__(self, ifname):
        NetError.__init__(self, ifname)
        self.ifname = ifname

    def __str__(self):
        return "Interface %s does not exist" % self.ifname


class TAPCreationError(NetError):
    def __init__(self, ifname, details=None):
        NetError.__init__(self, ifname, details)
        self.ifname = ifname
        self.details = details

    def __str__(self):
        e_msg = "Cannot create TAP device %s" % self.ifname
        if self.details is not None:
            e_msg += ": %s" % self.details
        return e_msg


class TAPBringUpError(NetError):
    def __init__(self, ifname):
        NetError.__init__(self, ifname)
        self.ifname = ifname

    def __str__(self):
        return "Cannot bring up TAP %s" % self.ifname


class BRAddIfError(NetError):
    def __init__(self, ifname, brname, details):
        NetError.__init__(self, ifname, brname, details)
        self.ifname = ifname
        self.brname = brname
        self.details = details

    def __str__(self):
        return ("Can't add interface %s to bridge %s: %s" %
                (self.ifname, self.brname, self.details))


class BRDelIfError(NetError):
    def __init__(self, ifname, brname, details):
        NetError.__init__(self, ifname, brname, details)
        self.ifname = ifname
        self.brname = brname
        self.details = details

    def __str__(self):
        return ("Can't remove interface %s from bridge %s: %s" %
                (self.ifname, self.brname, self.details))


class IfNotInBridgeError(NetError):
    def __init__(self, ifname, details):
        NetError.__init__(self, ifname, details)
        self.ifname = ifname
        self.details = details

    def __str__(self):
        return ("Interface %s is not present on any bridge: %s" %
                (self.ifname, self.details))


class BRNotExistError(NetError):
    def __init__(self, brname, details):
        NetError.__init__(self, brname, details)
        self.brname = brname
        self.details = details

    def __str__(self):
        return ("Bridge %s does not exist: %s" % (self.brname, self.details))


class IfChangeBrError(NetError):
    def __init__(self, ifname, old_brname, new_brname, details):
        NetError.__init__(self, ifname, old_brname, new_brname, details)
        self.ifname = ifname
        self.new_brname = new_brname
        self.old_brname = old_brname
        self.details = details

    def __str__(self):
        return ("Can't move interface %s from bridge %s to bridge %s: %s" %
                (self.ifname, self.new_brname, self.oldbrname, self.details))


class IfChangeAddrError(NetError):
    def __init__(self, ifname, ipaddr, details):
        NetError.__init__(self, ifname, ipaddr, details)
        self.ifname = ifname
        self.ipaddr = ipaddr
        self.details = details

    def __str__(self):
        return ("Can't change interface IP address %s from interface %s: %s" %
                (self.ifname, self.ipaddr, self.details))


class BRIpError(NetError):
    def __init__(self, brname):
        NetError.__init__(self, brname)
        self.brname = brname

    def __str__(self):
        return ("Bridge %s doesn't have an IP address assigned. It's"
                " impossible to start dnsmasq for this bridge." %
                   (self.brname))


class HwAddrSetError(NetError):
    def __init__(self, ifname, mac):
        NetError.__init__(self, ifname, mac)
        self.ifname = ifname
        self.mac = mac

    def __str__(self):
        return "Can not set mac %s to interface %s" % (self.mac, self.ifname)


class HwAddrGetError(NetError):
    def __init__(self, ifname):
        NetError.__init__(self, ifname)
        self.ifname = ifname

    def __str__(self):
        return "Can not get mac of interface %s" % self.ifname


class VlanError(NetError):
    def __init__(self, ifname, details):
        NetError.__init__(self, ifname, details)
        self.ifname = ifname
        self.details = details

    def __str__(self):
        return ("Vlan error on interface %s: %s" %
                (self.ifname, self.details))


class VMNetError(NetError):
    def __str__(self):
        return ("VMNet instance items must be dict-like and contain "
                "a 'nic_name' mapping")


class DbNoLockError(NetError):
    def __str__(self):
        return "Attempt made to access database with improper locking"


class EnvSaveError(Exception):
    pass


class Env(UserDict.IterableUserDict):
    """
    A dict-like object containing global objects used by tests.
    """
    def __init__(self, filename=None, version=0):
        """
        Create an empty Env object or load an existing one from a file.

        If the version recorded in the file is lower than version, or if some
        error occurs during unpickling, or if filename is not supplied,
        create an empty Env object.

        @param filename: Path to an env file.
        @param version: Required env version (int).
        """
        UserDict.IterableUserDict.__init__(self)
        empty = {"version": version}
        self._filename = filename
        if filename:
            try:
                if os.path.isfile(filename):
                    f = open(filename, "r")
                    env = cPickle.load(f)
                    f.close()
                    if env.get("version", 0) >= version:
                        self.data = env
                    else:
                        logging.warn("Incompatible env file found. Not using it.")
                        self.data = empty
                else:
                    # No previous env file found, proceed...
                    logging.warn("Creating new, empty env file")
                    self.data = empty
            # Almost any exception can be raised during unpickling, so let's
            # catch them all
            except Exception, e:
                logging.warn("Exception thrown while loading env: %s" % e)
                traceback.print_last()
                logging.warn("Creating new, empty env file")
                self.data = empty
        else:
            logging.warn("Creating new, empty env file")
            self.data = empty


    def save(self, filename=None):
        """
        Pickle the contents of the Env object into a file.

        @param filename: Filename to pickle the dict into.  If not supplied,
                use the filename from which the dict was loaded.
        """
        filename = filename or self._filename
        if filename is None:
            raise EnvSaveError("No filename specified for this env file")
        f = open(filename, "w")
        cPickle.dump(self.data, f)
        f.close()


    def get_all_vms(self):
        """
        Return a list of all VM objects in this Env object.
        """
        vm_list = []
        for key in self.data.keys():
            if key.startswith("vm__"):
                vm_list.append(self[key])
        return vm_list


    def clean_objects(self):
        """
        Destroy all objects registered in this Env object.
        """
        for key in self.data:
            try:
                if key.startswith("vm__"):
                    self.data[key].destroy()
                elif key == "tcpdump":
                    self.data[key].close()
            except Exception:
                pass
        self.data = {}


    def destroy(self):
        """
        Destroy all objects stored in Env and remove the backing file.
        """
        self.clean_objects()
        if self._filename is not None:
            if os.path.isfile(self._filename):
                os.unlink(self._filename)


    def get_vm(self, name):
        """
        Return a VM object by its name.

        @param name: VM name.
        """
        return self.data.get("vm__%s" % name)


    def register_vm(self, name, vm):
        """
        Register a VM in this Env object.

        @param name: VM name.
        @param vm: VM object.
        """
        self.data["vm__%s" % name] = vm


    def unregister_vm(self, name):
        """
        Remove a given VM.

        @param name: VM name.
        """
        del self.data["vm__%s" % name]


    def register_syncserver(self, port, server):
        """
        Register a Sync Server in this Env object.

        @param port: Sync Server port.
        @param server: Sync Server object.
        """
        self.data["sync__%s" % port] = server


    def unregister_syncserver(self, port):
        """
        Remove a given Sync Server.

        @param port: Sync Server port.
        """
        del self.data["sync__%s" % port]


    def get_syncserver(self, port):
        """
        Return a Sync Server object by its port.

        @param port: Sync Server port.
        """
        return self.data.get("sync__%s" % port)


    def register_installer(self, installer):
        """
        Register a installer that was just run

        The installer will be available for other tests, so that
        information about the installed KVM modules and qemu-kvm can be used by
        them.
        """
        self.data['last_installer'] = installer


    def previous_installer(self):
        """
        Return the last installer that was registered
        """
        return self.data.get('last_installer')


class Params(UserDict.IterableUserDict):
    """
    A dict-like object passed to every test.
    """
    def objects(self, key):
        """
        Return the names of objects defined using a given key.

        @param key: The name of the key whose value lists the objects
                (e.g. 'nics').
        """
        return self.get(key, "").split()


    def object_params(self, obj_name):
        """
        Return a dict-like object containing the parameters of an individual
        object.

        This method behaves as follows: the suffix '_' + obj_name is removed
        from all key names that have it.  Other key names are left unchanged.
        The values of keys with the suffix overwrite the values of their
        suffixless versions.

        @param obj_name: The name of the object (objects are listed by the
                objects() method).
        """
        suffix = "_" + obj_name
        new_dict = self.copy()
        for key in self:
            if key.endswith(suffix):
                new_key = key.split(suffix)[0]
                new_dict[new_key] = self[key]
        return new_dict


# Can't reliably combine use of properties and __slots__ (both set descriptors)
class PropCanBase(dict):
    """
    Objects with optional accessor methods and dict-like access to fixed set of keys
    """

    def __new__(cls, *args, **dargs):
        if not hasattr(cls, '__slots__'):
            raise NotImplementedError("Class '%s' must define __slots__ "
                                      "property" % str(cls))
        newone = dict.__new__(cls, *args, **dargs)
        # Let accessor methods know initialization is running
        newone.super_set('INITIALIZED', False)
        return newone


    def __init__(self, *args, **dargs):
        """
        Initialize contents directly or by way of accessors

        @param: *args: Initial values for __slots__ keys, same as dict.
        @param: **dargs: Initial values for __slots__ keys, same as dict.
        """
        # Params are initialized here, not in super
        super(PropCanBase, self).__init__()
        # No need to re-invent dict argument processing
        values = dict(*args, **dargs)
        for key in self.__slots__:
            value = values.get(key, "@!@!@!@!@!SENTENEL!@!@!@!@!@")
            if value is not "@!@!@!@!@!SENTENEL!@!@!@!@!@":
                # Call accessor methods if present
                self[key] = value
        # Let accessor methods know initialization is complete
        self.super_set('INITIALIZED', True)


    def __getitem__(self, key):
        try:
            accessor = super(PropCanBase,
                             self).__getattribute__('get_%s' % key)
            return accessor()
        except AttributeError:
            return super(PropCanBase, self).__getitem__(key)


    def __setitem__(self, key, value):
        try:
            accessor = super(PropCanBase,
                             self).__getattribute__('set_%s' % key)
            return accessor(value)
        except AttributeError:
            self.__canhaz__(key, KeyError)
            return super(PropCanBase, self).__setitem__(key, value)


    def __delitem__(self, key):
        try:
            accessor = super(PropCanBase,
                             self).__getattribute__('del_%s' % key)
            return accessor()
        except AttributeError:
            return super(PropCanBase, self).__delitem__(key)


    def __getattr__(self, key):
        try:
            # Attempt to call accessor methods first whenever possible
            self.__canhaz__(key, KeyError)
            return self.__getitem__(key)
        except KeyError:
            # Allow subclasses to define attributes if required
            return super(PropCanBase, self).__getattribute__(key)


    def __setattr__(self, key, value):
        self.__canhaz__(key)
        try:
            return self.__setitem__(key, value)
        except KeyError, detail:
            # Prevent subclass instances from defining normal attributes
            raise AttributeError(str(detail))


    def __delattr__(self, key):
        self.__canhaz__(key)
        try:
            return self.__delitem__(key)
        except KeyError, detail:
            # Prevent subclass instances from deleting normal attributes
            raise AttributeError(str(detail))


    def __canhaz__(self, key, excpt=AttributeError):
        slots = tuple(super(PropCanBase, self).__getattribute__('__slots__'))
        keys = slots + ('get_%s' % key, 'set_%s' % key, 'del_%s' % key)
        if key not in keys:
            raise excpt("Key '%s' not found in super class attributes or in %s"
                        % (str(key), str(keys)))


    def copy(self):
        return self.__class__(dict(self))


    # The following methods are intended for use by accessor-methods
    # where they may need to bypass the special attribute/key handling
    # that's setup above.

    def dict_get(self, key):
        """
        Get a key unconditionally, w/o checking for accessor method or __slots__
        """
        return dict.__getitem__(self, key)


    def dict_set(self, key, value):
        """
        Set a key unconditionally, w/o checking for accessor method or __slots__
        """
        dict.__setitem__(self, key, value)


    def dict_del(self, key):
        """
        Del key unconditionally, w/o checking for accessor method or __slots__
        """
        return dict.__delitem__(self, key)


    def super_get(self, key):
        """
        Get attribute unconditionally, w/o checking accessor method or __slots__
        """
        return object.__getattribute__(self, key)


    def super_set(self, key, value):
        """
        Set attribute unconditionally, w/o checking accessor method or __slots__
        """
        object.__setattr__(self, key, value)


    def super_del(self, key):
        """
        Del attribute unconditionally, w/o checking accessor method or __slots__
        """
        object.__delattr__(self, key)


class PropCan(PropCanBase):
    """
    Special value handling on retrieval of None/False values
    """

    def __len__(self):
        length = 0
        for key in self.__slots__:
            # special None/False value handling
            if self.__contains__(key):
                length += 1
        return length


    def __contains__(self, key):
        try:
            value = self.dict_get(key)
        except (KeyError, AttributeError):
            return False
        # Avoid inf. recursion if value == self
        if issubclass(type(value), type(self)) or value:
            return True
        return False


    def __eq__(self, other):
        # special None/False value handling
        return dict([(key, value) for key, value in self.items()]) == other


    def __ne__(self, other):
        return not self.__eq__(other)


    def keys(self):
        # special None/False value handling
        return [key for key in self.__slots__ if self.__contains__(key)]


    def values(self):
        # special None/False value handling
        return [self[key] for key in self.keys()]


    def items(self):
        return tuple( [(key, self[key]) for key in self.keys()] )


    has_key = __contains__


    def set_if_none(self, key, value):
        """
        Set the value of key, only if it's not set or None
        """
        if not self.has_key(key):
            self[key] = value


    def set_if_value_not_none(self, key, value):
        """
        Set the value of key, only if value is not None
        """
        if value:
            self[key] = value


    def __str__(self):
        """
        Guarantee return of string format dictionary representation
        """
        acceptable_types = (str, unicode, int, float, long)
        return str( dict([(key, value) for key, value in self.items()
                                if issubclass(type(value), acceptable_types)]) )


    __repr__ = __str__


class VirtIface(PropCan):
    """
    Networking information for single guest interface and host connection.
    """

    __slots__ = ['nic_name', 'g_nic_name', 'mac', 'nic_model', 'ip',
                 'nettype', 'netdst']
    # Make sure first byte generated is always zero and it follows
    # the class definition.  This helps provide more predictable
    # addressing while avoiding clashes between multiple NICs.
    LASTBYTE = random.SystemRandom().randint(0x00, 0xff)

    def __getstate__(self):
        state = {}
        for key in self.__class__.__slots__:
            if self.has_key(key):
                state[key] = self[key]
        return state


    def __setstate__(self, state):
        self.__init__(state)


    @classmethod
    def name_is_valid(cls, nic_name):
        """
        Corner-case prevention where nic_name is not a sane string value
        """
        try:
            return isinstance(nic_name, str) and len(nic_name) > 1
        except (TypeError, KeyError, AttributeError):
            return False


    @classmethod
    def mac_is_valid(cls, mac):
        try:
            mac = cls.mac_str_to_int_list(mac)
        except TypeError:
            return False
        return True # Though may be less than 6 bytes


    @classmethod
    def mac_str_to_int_list(cls, mac):
        """
        Convert list of string bytes to int list
        """
        if isinstance(mac, (str, unicode)):
            mac = mac.split(':')
        # strip off any trailing empties
        for rindex in xrange(len(mac), 0, -1):
            if not mac[rindex-1].strip():
                del mac[rindex-1]
            else:
                break
        try:
            assert len(mac) < 7
            for byte_str_index in xrange(0, len(mac)):
                byte_str = mac[byte_str_index]
                assert isinstance(byte_str, (str, unicode))
                assert len(byte_str) > 0
                try:
                    value = eval("0x%s" % byte_str, {}, {})
                except SyntaxError:
                    raise AssertionError
                assert value >= 0x00
                assert value <= 0xFF
                mac[byte_str_index] = value
        except AssertionError:
            raise TypeError("%s %s is not a valid MAC format "
                            "string or list" % (str(mac.__class__),
                             str(mac)))
        return mac


    @classmethod
    def int_list_to_mac_str(cls, mac_bytes):
        """
        Return string formatting of int mac_bytes
        """
        for byte_index in xrange(0, len(mac_bytes)):
            mac = mac_bytes[byte_index]
            # Project standardized on lower-case hex
            if mac < 16:
                mac_bytes[byte_index] = "0%x" % mac
            else:
                mac_bytes[byte_index] = "%x" % mac
        return mac_bytes


    @classmethod
    def generate_bytes(cls):
        """
        Return next byte from ring
        """
        cls.LASTBYTE += 1
        if cls.LASTBYTE > 0xff:
            cls.LASTBYTE = 0
        yield cls.LASTBYTE


    @classmethod
    def complete_mac_address(cls, mac):
        """
        Append randomly generated byte strings to make mac complete

        @param: mac: String or list of mac bytes (possibly incomplete)
        @raise: TypeError if mac is not a string or a list
        """
        mac = cls.mac_str_to_int_list(mac)
        if len(mac) == 6:
            return ":".join(cls.int_list_to_mac_str(mac))
        for rand_byte in cls.generate_bytes():
            mac.append(rand_byte)
            return cls.complete_mac_address(cls.int_list_to_mac_str(mac))


class LibvirtIface(VirtIface):
    """
    Networking information specific to libvirt
    """
    __slots__ = VirtIface.__slots__ + []


class KVMIface(VirtIface):
    """
    Networking information specific to KVM
    """
    __slots__ = VirtIface.__slots__ + ['vlan', 'device_id', 'ifname', 'tapfd',
                                       'tapfd_id', 'netdev_id', 'tftp',
                                       'romfile', 'nic_extra_params',
                                       'netdev_extra_params']


class VMNet(list):
    """
    Collection of networking information.
    """

    # don't flood discard warnings
    DISCARD_WARNINGS = 10

    # __init__ must not presume clean state, it should behave
    # assuming there is existing properties/data on the instance
    # and take steps to preserve or update it as appropriate.
    def __init__(self, container_class=VirtIface, virtiface_list=[]):
        """
        Initialize from list-like virtiface_list using container_class
        """
        if container_class != VirtIface and (
                        not issubclass(container_class, VirtIface)):
            raise TypeError("Container class must be Base_VirtIface "
                            "or subclass not a %s" % str(container_class))
        self.container_class = container_class
        super(VMNet, self).__init__([])
        if isinstance(virtiface_list, list):
            for virtiface in virtiface_list:
                self.append(virtiface)
        else:
            raise VMNetError


    def __getstate__(self):
        return [nic for nic in self]


    def __setstate__(self, state):
        VMNet.__init__(self, self.container_class, state)


    def __getitem__(self, index_or_name):
        if isinstance(index_or_name, str):
            index_or_name = self.nic_name_index(index_or_name)
        return super(VMNet, self).__getitem__(index_or_name)


    def __setitem__(self, index_or_name, value):
        if not isinstance(value, dict):
            raise VMNetError
        if self.container_class.name_is_valid(value['nic_name']):
            if isinstance(index_or_name, str):
                index_or_name = self.nic_name_index(index_or_name)
            self.process_mac(value)
            super(VMNet, self).__setitem__(index_or_name,
                                           self.container_class(value))
        else:
            raise VMNetError


    def subclass_pre_init(self, params, vm_name):
        """
        Subclasses must establish style before calling VMNet. __init__()
        """
        #TODO: Get rid of this function.  it's main purpose is to provide
        # a shared way to setup style (container_class) from params+vm_name
        # so that unittests can run independently for each subclass.
        self.vm_name = vm_name
        self.params = params.object_params(self.vm_name)
        self.vm_type = self.params.get('vm_type', 'default')
        self.driver_type = self.params.get('driver_type', 'default')
        for key, value in VMNetStyle(self.vm_type,
                                    self.driver_type).items():
            setattr(self, key, value)


    def process_mac(self, value):
        """
        Strips 'mac' key from value if it's not valid
        """
        original_mac = mac = value.get('mac')
        if mac:
            mac = value['mac'] = value['mac'].lower()
            if len(mac.split(':')
                            ) == 6 and self.container_class.mac_is_valid(mac):
                return
            else:
                del value['mac'] # don't store invalid macs
                # Notify user about these, but don't go crazy
                if self.__class__.DISCARD_WARNINGS >= 0:
                    logging.warning('Discarded invalid mac "%s" for nic "%s" '
                                    'from input, %d warnings remaining.'
                                    % (original_mac,
                                       value.get('nic_name'),
                                       self.__class__.DISCARD_WARNINGS))
                    self.__class__.DISCARD_WARNINGS -= 1


    def mac_list(self):
        """
        Return a list of all mac addresses used by defined interfaces
        """
        return [nic.mac for nic in self if hasattr(nic, 'mac')]


    def append(self, value):
        newone = self.container_class(value)
        newone_name = newone['nic_name']
        if newone.name_is_valid(newone_name) and (
                          newone_name not in self.nic_name_list()):
            self.process_mac(newone)
            super(VMNet, self).append(newone)
        else:
            raise VMNetError


    def nic_name_index(self, name):
        """
        Return the index number for name, or raise KeyError
        """
        if not isinstance(name, str):
            raise TypeError("nic_name_index()'s nic_name must be a string")
        nic_name_list = self.nic_name_list()
        try:
            return nic_name_list.index(name)
        except ValueError:
            raise IndexError("Can't find nic named '%s' among '%s'" %
                             (name, nic_name_list))


    def nic_name_list(self):
        """
        Obtain list of nic names from lookup of contents 'nic_name' key.
        """
        namelist = []
        for item in self:
            # Rely on others to throw exceptions on 'None' names
            namelist.append(item['nic_name'])
        return namelist


    def nic_lookup(self, prop_name, prop_value):
        """
        Return the first index with prop_name key matching prop_value or None
        """
        for nic_index in xrange(0, len(self)):
            if self[nic_index].has_key(prop_name):
                if self[nic_index][prop_name] == prop_value:
                    return nic_index
        return None


# TODO: Subclass VMNet into KVM/Libvirt variants and
# pull them, along with ParmasNet and maybe DbNet based on
# Style definitions.  i.e. libvirt doesn't need DbNet at all,
# but could use some custom handling at the VMNet layer
# for xen networking.  This will also enable further extensions
# to network information handing in the future.
class VMNetStyle(dict):
    """
    Make decisions about needed info from vm_type and driver_type params.
    """

    # Keyd first by vm_type, then by driver_type.
    VMNet_Style_Map = {
        'default':{
            'default':{
                'mac_prefix':'9a',
                'container_class': KVMIface,
            }
        },
        'libvirt':{
            'default':{
                'mac_prefix':'9a',
                'container_class': LibvirtIface,
            },
            'qemu':{
                'mac_prefix':'52:54:00',
                'container_class': LibvirtIface,
            },
            'xen':{
                'mac_prefix':'00:16:3e',
                'container_class': LibvirtIface,
            }
        }
    }

    def __new__(cls, vm_type, driver_type):
        return cls.get_style(vm_type, driver_type)


    @classmethod
    def get_vm_type_map(cls, vm_type):
        return cls.VMNet_Style_Map.get(vm_type,
                                        cls.VMNet_Style_Map['default'])


    @classmethod
    def get_driver_type_map(cls, vm_type_map, driver_type):
        return vm_type_map.get(driver_type,
                               vm_type_map['default'])


    @classmethod
    def get_style(cls, vm_type, driver_type):
        style = cls.get_driver_type_map( cls.get_vm_type_map(vm_type),
                                         driver_type )
        return style


class ParamsNet(VMNet):
    """
    Networking information from Params

        Params contents specification-
            vms = <vm names...>
            nics = <nic names...>
            nics_<vm name> = <nic names...>
            # attr: mac, ip, model, nettype, netdst, etc.
            <attr> = value
            <attr>_<nic name> = value
    """

    # __init__ must not presume clean state, it should behave
    # assuming there is existing properties/data on the instance
    # and take steps to preserve or update it as appropriate.
    def __init__(self, params, vm_name):
        self.subclass_pre_init(params, vm_name)
        # use temporary list to initialize
        result_list = []
        nic_name_list = self.params.objects('nics')
        for nic_name in nic_name_list:
            # nic name is only in params scope
            nic_dict = {'nic_name':nic_name}
            nic_params = self.params.object_params(nic_name)
            # avoid processing unsupported properties
            proplist = list(self.container_class.__slots__)
            # nic_name was already set, remove from __slots__ list copy
            del proplist[proplist.index('nic_name')]
            for propertea in proplist:
                # Merge existing propertea values if they exist
                try:
                    existing_value = getattr(self[nic_name], propertea, None)
                except ValueError:
                    existing_value = None
                except IndexError:
                    existing_value = None
                nic_dict[propertea] = nic_params.get(propertea, existing_value)
            result_list.append(nic_dict)
        VMNet.__init__(self, self.container_class, result_list)


    def mac_index(self):
        """
        Generator over mac addresses found in params
        """
        for nic_name in self.params.get('nics'):
            nic_obj_params = self.params.object_params(nic_name)
            mac = nic_obj_params.get('mac')
            if mac:
                yield mac
            else:
                continue


    def reset_mac(self, index_or_name):
        """
        Reset to mac from params if defined and valid, or undefine.
        """
        nic = self[index_or_name]
        nic_name = nic.nic_name
        nic_params = self.params.object_params(nic_name)
        params_mac = nic_params.get('mac')
        if params_mac and self.container_class.mac_is_valid(params_mac):
            new_mac = params_mac.lower()
        else:
            new_mac = None
        nic.mac = new_mac


    def reset_ip(self, index_or_name):
        """
        Reset to ip from params if defined and valid, or undefine.
        """
        nic = self[index_or_name]
        nic_name = nic.nic_name
        nic_params = self.params.object_params(nic_name)
        params_ip = nic_params.get('ip')
        if params_ip:
            new_ip = params_ip
        else:
            new_ip = None
        nic.ip = new_ip


class DbNet(VMNet):
    """
    Networking information from database

        Database specification-
            database values are python string-formatted lists of dictionaries
    """

    _INITIALIZED = False

    # __init__ must not presume clean state, it should behave
    # assuming there is existing properties/data on the instance
    # and take steps to preserve or update it as appropriate.
    def __init__(self, params, vm_name, db_filename, db_key):
        self.subclass_pre_init(params, vm_name)
        self.db_key = db_key
        self.db_filename = db_filename
        self.db_lockfile = db_filename + ".lock"
        self.lock_db()
        # Merge (don't overwrite) existing propertea values if they
        # exist in db
        try:
            entry = self.db_entry()
        except KeyError:
            entry = []
        proplist = list(self.container_class.__slots__)
        # nic_name was already set, remove from __slots__ list copy
        del proplist[proplist.index('nic_name')]
        nic_name_list = self.nic_name_list()
        for db_nic in entry:
            nic_name = db_nic['nic_name']
            if nic_name in nic_name_list:
                for propertea in proplist:
                    # only set properties in db but not in self
                    if db_nic.has_key(propertea):
                        self[nic_name].set_if_none(propertea, db_nic[propertea])
        self.unlock_db()
        if entry:
            VMNet.__init__(self, self.container_class, entry)


    def __setitem__(self, index, value):
        super(DbNet, self).__setitem__(index, value)
        if self._INITIALIZED:
            self.update_db()


    def __getitem__(self, index_or_name):
        # container class attributes are read-only, hook
        # update_db here is only alternative
        if self._INITIALIZED:
            self.update_db()
        return super(DbNet, self).__getitem__(index_or_name)


    def __delitem__(self, index_or_name):
        if isinstance(index_or_name, str):
            index_or_name = self.nic_name_index(index_or_name)
        super(DbNet, self).__delitem__(index_or_name)
        if self._INITIALIZED:
            self.update_db()


    def append(self, value):
        super(DbNet, self).append(value)
        if self._INITIALIZED:
            self.update_db()


    def lock_db(self):
        if not hasattr(self, 'lock'):
            self.lock = lock_file(self.db_lockfile)
            if not hasattr(self, 'db'):
                self.db = shelve.open(self.db_filename)
            else:
                raise DbNoLockError
        else:
            raise DbNoLockError


    def unlock_db(self):
        if hasattr(self, 'db'):
            self.db.close()
            del self.db
            if hasattr(self, 'lock'):
                unlock_file(self.lock)
                del self.lock
            else:
                raise DbNoLockError
        else:
            raise DbNoLockError


    def db_entry(self, db_key=None):
        """
        Returns a python list of dictionaries from locked DB string-format entry
        """
        if not db_key:
            db_key = self.db_key
        try:
            db_entry = self.db[db_key]
        except AttributeError: # self.db doesn't exist:
            raise DbNoLockError
        # Always wear protection
        try:
            eval_result = eval(db_entry, {}, {})
        except SyntaxError:
            raise ValueError("Error parsing entry for %s from "
                             "database '%s'" % (self.db_key,
                                                self.db_filename))
        if not isinstance(eval_result, list):
            raise ValueError("Unexpected database data: %s" % (
                                    str(eval_result)))
        result = []
        for result_dict in eval_result:
            if not isinstance(result_dict, dict):
                raise ValueError("Unexpected database sub-entry data %s" % (
                                    str(result_dict)))
            result.append(result_dict)
        return result


    def save_to_db(self, db_key=None):
        """
        Writes string representation out to database
        """
        if db_key == None:
            db_key = self.db_key
        data = str(self)
        # Avoid saving empty entries
        if len(data) > 3:
            try:
                self.db[self.db_key] = data
            except AttributeError:
                raise DbNoLockError
        else:
            try:
                # make sure old db entry is removed
                del self.db[db_key]
            except KeyError:
                pass


    def update_db(self):
        self.lock_db()
        self.save_to_db()
        self.unlock_db()


    def mac_index(self):
        """Generator of mac addresses found in database"""
        try:
            for db_key in self.db.keys():
                for nic in self.db_entry(db_key):
                    mac = nic.get('mac')
                    if mac:
                        yield mac
                    else:
                        continue
        except AttributeError:
            raise DbNoLockError


class VirtNet(DbNet, ParamsNet):
    """
    Persistent collection of VM's networking information.
    """
    # __init__ must not presume clean state, it should behave
    # assuming there is existing properties/data on the instance
    # and take steps to preserve or update it as appropriate.
    def __init__(self, params, vm_name, db_key,
                                        db_filename="/tmp/address_pool"):
        """
        Load networking info. from db, then from params, then update db.

        @param: params: Params instance using specification above
        @param: vm_name: Name of the VM as might appear in Params
        @param: db_key: database key uniquely identifying VM instance
        @param: db_filename: database file to cache previously parsed params
        """
        # Prevent database updates during initialization
        self._INITIALIZED = False
        # Params always overrides database content
        DbNet.__init__(self, params, vm_name, db_filename, db_key)
        ParamsNet.__init__(self, params, vm_name)
        self.lock_db()
        # keep database updated in case of problems
        self.save_to_db()
        self.unlock_db()
        # signal runtime content handling to methods
        self._INITIALIZED = True


    # Delegating get/setstate() details more to ancestor classes
    # doesn't play well with multi-inheritence.  While possibly
    # more difficult to maintain, hard-coding important property
    # names for pickling works. The possibility also remains open
    # for extensions via style-class updates.
    def __getstate__(self):
        self._INITIALIZED = False # prevent database updates
        state = {'container_items':VMNet.__getstate__(self)}
        for attrname in ['params', 'vm_name', 'db_key', 'db_filename',
                         'vm_type', 'driver_type', 'db_lockfile']:
            state[attrname] = getattr(self, attrname)
        for style_attr in VMNetStyle(self.vm_type, self.driver_type).keys():
            state[style_attr] = getattr(self, style_attr)
        return state


    def __setstate__(self, state):
        self._INITIALIZED = False # prevent db updates during unpickling
        for key in state.keys():
            if key == 'container_items':
                continue # handle outside loop
            setattr(self, key, state.pop(key))
        VMNet.__setstate__(self, state.pop('container_items'))
        self._INITIALIZED = True


    def __eq__(self, other):
        if len(self) != len(other):
            return False
        # Order doesn't matter for most OS's as long as MAC & netdst match
        for nic_name in self.nic_name_list():
            if self[nic_name] != other[nic_name]:
                return False
        return True


    def __ne__(self, other):
        return not self.__eq__(other)


    def mac_index(self):
        """
        Generator for all allocated mac addresses (requires db lock)
        """
        for mac in DbNet.mac_index(self):
            yield mac
        for mac in ParamsNet.mac_index(self):
            yield mac


    def generate_mac_address(self, nic_index_or_name, attempts=1024):
        """
        Set & return valid mac address for nic_index_or_name or raise NetError

        @param: nic_index_or_name: index number or name of NIC
        @return: MAC address string
        @raise: NetError if mac generation failed
        """
        nic = self[nic_index_or_name]
        if nic.has_key('mac'):
            logging.warning("Overwriting mac %s for nic %s with random"
                                % (nic.mac, str(nic_index_or_name)))
        self.free_mac_address(nic_index_or_name)
        self.lock_db()
        attempts_remaining = attempts
        while attempts_remaining > 0:
            mac_attempt = nic.complete_mac_address(self.mac_prefix)
            if mac_attempt not in self.mac_index():
                nic.mac = mac_attempt.lower()
                self.unlock_db()
                return self[nic_index_or_name].mac # calls update_db
            else:
                attempts_remaining -= 1
        self.unlock_db()
        raise NetError("%s/%s MAC generation failed with prefix %s after %d "
                         "attempts for NIC %s on VM %s (%s)" % (
                            self.vm_type,
                            self.driver_type,
                            self.mac_prefix,
                            attempts,
                            str(nic_index_or_name),
                            self.vm_name,
                            self.db_key))


    def free_mac_address(self, nic_index_or_name):
        """
        Remove the mac value from nic_index_or_name and cache unless static

        @param: nic_index_or_name: index number or name of NIC
        """
        nic = self[nic_index_or_name]
        if nic.has_key('mac'):
            # Reset to params definition if any, or None
            self.reset_mac(nic_index_or_name)
        self.update_db()


    def set_mac_address(self, nic_index_or_name, mac):
        """
        Set a MAC address to value specified

        @param: nic_index_or_name: index number or name of NIC
        @raise: NetError if mac already assigned
        """
        nic = self[nic_index_or_name]
        if nic.has_key('mac'):
            logging.warning("Overwriting mac %s for nic %s with %s"
                            % (nic.mac, str(nic_index_or_name), mac))
        nic.mac = mac.lower()
        self.update_db()


    def get_mac_address(self, nic_index_or_name):
        """
        Return a MAC address for nic_index_or_name

        @param: nic_index_or_name: index number or name of NIC
        @return: MAC address string.
        """
        return self[nic_index_or_name].mac.lower()


    def generate_ifname(self, nic_index_or_name):
        """
        Return and set network interface name
        """
        nic_index = self.nic_name_index(self[nic_index_or_name].nic_name)
        prefix = "t%d-" % nic_index
        postfix = generate_random_string(6)
        # Ensure interface name doesn't excede 11 characters
        self[nic_index_or_name].ifname = (prefix + postfix)[-11:]
        return self[nic_index_or_name].ifname # forces update_db


def verify_ip_address_ownership(ip, macs, timeout=10.0):
    """
    Use arping and the ARP cache to make sure a given IP address belongs to one
    of the given MAC addresses.

    @param ip: An IP address.
    @param macs: A list or tuple of MAC addresses.
    @return: True if ip is assigned to a MAC address in macs.
    """
    # Compile a regex that matches the given IP address and any of the given
    # MAC addresses
    mac_regex = "|".join("(%s)" % mac for mac in macs)
    regex = re.compile(r"\b%s\b.*\b(%s)\b" % (ip, mac_regex), re.IGNORECASE)

    # Check the ARP cache
    o = commands.getoutput("%s -n" % find_command("arp"))
    if regex.search(o):
        return True

    # Get the name of the bridge device for arping
    o = commands.getoutput("%s route get %s" % (find_command("ip"), ip))
    dev = re.findall("dev\s+\S+", o, re.IGNORECASE)
    if not dev:
        return False
    dev = dev[0].split()[-1]

    # Send an ARP request
    o = commands.getoutput("%s -f -c 3 -I %s %s" %
                           (find_command("arping"), dev, ip))
    return bool(regex.search(o))


# Utility functions for dealing with external processes

def find_command(cmd):
    for path in ["/usr/local/sbin", "/usr/local/bin",
                "/usr/sbin", "/usr/bin", "/sbin", "/bin"]:
        cmd_path = os.path.join(path, cmd)
        if os.path.exists(cmd_path):
            return cmd_path
    raise ValueError('Missing command: %s' % cmd)


def pid_exists(pid):
    """
    Return True if a given PID exists.

    @param pid: Process ID number.
    """
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def safe_kill(pid, signal):
    """
    Attempt to send a signal to a given process that may or may not exist.

    @param signal: Signal number.
    """
    try:
        os.kill(pid, signal)
        return True
    except Exception:
        return False


def kill_process_tree(pid, sig=signal.SIGKILL):
    """Signal a process and all of its children.

    If the process does not exist -- return.

    @param pid: The pid of the process to signal.
    @param sig: The signal to send to the processes.
    """
    if not safe_kill(pid, signal.SIGSTOP):
        return
    children = commands.getoutput("ps --ppid=%d -o pid=" % pid).split()
    for child in children:
        kill_process_tree(int(child), sig)
    safe_kill(pid, sig)
    safe_kill(pid, signal.SIGCONT)


# The following are utility functions related to ports.

def is_port_free(port, address):
    """
    Return True if the given port is available for use.

    @param port: Port number
    """
    try:
        s = socket.socket()
        #s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if address == "localhost":
            s.bind(("localhost", port))
            free = True
        else:
            s.connect((address, port))
            free = False
    except socket.error:
        if address == "localhost":
            free = False
        else:
            free = True
    s.close()
    return free


def find_free_port(start_port, end_port, address="localhost"):
    """
    Return a host free port in the range [start_port, end_port].

    @param start_port: First port that will be checked.
    @param end_port: Port immediately after the last one that will be checked.
    """
    for i in range(start_port, end_port):
        if is_port_free(i, address):
            return i
    return None


def find_free_ports(start_port, end_port, count, address="localhost"):
    """
    Return count of host free ports in the range [start_port, end_port].

    @count: Initial number of ports known to be free in the range.
    @param start_port: First port that will be checked.
    @param end_port: Port immediately after the last one that will be checked.
    """
    ports = []
    i = start_port
    while i < end_port and count > 0:
        if is_port_free(i, address):
            ports.append(i)
            count -= 1
        i += 1
    return ports


# An easy way to log lines to files when the logging system can't be used

_open_log_files = {}
_log_file_dir = "/tmp"


def log_line(filename, line):
    """
    Write a line to a file.  '\n' is appended to the line.

    @param filename: Path of file to write to, either absolute or relative to
            the dir set by set_log_file_dir().
    @param line: Line to write.
    """
    global _open_log_files, _log_file_dir

    path = get_path(_log_file_dir, filename)
    if path not in _open_log_files:
        try:
            os.makedirs(os.path.dirname(path))
        except OSError:
            pass
        _open_log_files[path] = open(path, "w")
    timestr = time.strftime("%Y-%m-%d %H:%M:%S")
    _open_log_files[path].write("%s: %s\n" % (timestr, line))
    _open_log_files[path].flush()


def set_log_file_dir(directory):
    """
    Set the base directory for log files created by log_line().

    @param dir: Directory for log files.
    """
    global _log_file_dir
    _log_file_dir = directory


# The following are miscellaneous utility functions.

def get_path(base_path, user_path):
    """
    Translate a user specified path to a real path.
    If user_path is relative, append it to base_path.
    If user_path is absolute, return it as is.

    @param base_path: The base path of relative user specified paths.
    @param user_path: The user specified path.
    """
    if os.path.isabs(user_path):
        return user_path
    else:
        return os.path.join(base_path, user_path)


def generate_random_string(length, ignore_str=string.punctuation,
                           convert_str=""):
    """
    Return a random string using alphanumeric characters.

    @param length: Length of the string that will be generated.
    @param ignore_str: Characters that will not include in generated string.
    @param convert_str: Characters that need to be escaped (prepend "\\").

    @return: The generated random string.
    """
    r = random.SystemRandom()
    str = ""
    chars = string.letters + string.digits + string.punctuation
    if not ignore_str:
        ignore_str = ""
    for i in ignore_str:
        chars = chars.replace(i, "")

    while length > 0:
        tmp = r.choice(chars)
        if convert_str and (tmp in convert_str):
            tmp = "\\%s" % tmp
        str += tmp
        length -= 1
    return str


def generate_random_id():
    """
    Return a random string suitable for use as a qemu id.
    """
    return "id" + generate_random_string(6)


def generate_tmp_file_name(file_name, ext=None, directory='/tmp/'):
    """
    Returns a temporary file name. The file is not created.
    """
    while True:
        file_name = (file_name + '-' + time.strftime("%Y%m%d-%H%M%S-") +
                     generate_random_string(4))
        if ext:
            file_name += '.' + ext
        file_name = os.path.join(directory, file_name)
        if not os.path.exists(file_name):
            break

    return file_name


def format_str_for_message(sr):
    """
    Format str so that it can be appended to a message.
    If str consists of one line, prefix it with a space.
    If str consists of multiple lines, prefix it with a newline.

    @param str: string that will be formatted.
    """
    lines = str.splitlines()
    num_lines = len(lines)
    sr = "\n".join(lines)
    if num_lines == 0:
        return ""
    elif num_lines == 1:
        return " " + sr
    else:
        return "\n" + sr


def wait_for(func, timeout, first=0.0, step=1.0, text=None):
    """
    If func() evaluates to True before timeout expires, return the
    value of func(). Otherwise return None.

    @brief: Wait until func() evaluates to True.

    @param timeout: Timeout in seconds
    @param first: Time to sleep before first attempt
    @param steps: Time to sleep between attempts in seconds
    @param text: Text to print while waiting, for debug purposes
    """
    start_time = time.time()
    end_time = time.time() + timeout

    time.sleep(first)

    while time.time() < end_time:
        if text:
            logging.debug("%s (%f secs)", text, (time.time() - start_time))

        output = func()
        if output:
            return output

        time.sleep(step)

    return None


def get_hash_from_file(hash_path, dvd_basename):
    """
    Get the a hash from a given DVD image from a hash file
    (Hash files are usually named MD5SUM or SHA1SUM and are located inside the
    download directories of the DVDs)

    @param hash_path: Local path to a hash file.
    @param cd_image: Basename of a CD image
    """
    hash_file = open(hash_path, 'r')
    for line in hash_file.readlines():
        if dvd_basename in line:
            return line.split()[0]


def run_tests(parser, job):
    """
    Runs the sequence of KVM tests based on the list of dictionaries
    generated by the configuration system, handling dependencies.

    @param parser: Config parser object.
    @param job: Autotest job object.

    @return: True, if all tests ran passed, False if any of them failed.
    """
    prepare_case = ['unattended_install', 'rh_kernel_update',
                    'disable_win_update']
    last_index = -1
    pass_list = []
    offset = 0
    for i, d in enumerate(parser.get_dicts()):
        if d.has_key("prepare_case"):
            prepare_case = d["prepare_case"]
        if d.get("case_type") == "prepare":
            case_mark = ""
            for case in prepare_case:
                if case in d["name"]:
                    img_name = d['image_name'] + '-' + d['image_format']
                    case_mark = "%s-%s" % (case, img_name)
            if case_mark:
                if case_mark in pass_list:
                    offset += 1
                    continue
                else:
                    pass_list.append(case_mark)
        i -= offset
        logging.info("Test %4d:  %s" % (i + 1, d["shortname"]))
        last_index += 1

    status_dict = {}
    failed = False
    # Add the parameter decide if setup host env in the test case
    # For some special tests we only setup host in the first and last case
    # When we need to setup host env we need the host_setup_flag as following:
    #    0(00): do nothing
    #    1(01): setup env
    #    2(10): cleanup env
    #    3(11): setup and cleanup env
    index = 0
    setup_flag = 1
    cleanup_flag = 2
    pass_list = []
    for param_dict in parser.get_dicts():
        tmp_dict = {}
        for key in param_dict:
            if key.endswith("_equal"):
                t_key = key.split("_equal")[0]
                tmp_dict[t_key] = param_dict[key]
            elif key.endswith("_min"):
                t_key = key.split("_min")[0]
                if not d.has_key(t_key) or \
                    cartesian_config.compare_string(param_dict[t_key],
                                                    param_dict[key]) < 0:
                    tmp_dict[t_key] = param_dict[key]
            elif key.endswith("_max"):
                t_key = key.split("_max")[0]
                if not d.has_key(t_key) or \
                    cartesian_config.compare_string(param_dict[t_key],
                                                    param_dict[key]) > 0:
                    tmp_dict[t_key] = param_dict[key]
        for key in tmp_dict:
            param_dict[key] = tmp_dict[key]

        if index == 0:
            if param_dict.get("host_setup_flag", None) is not None:
                flag = int(param_dict["host_setup_flag"])
                param_dict["host_setup_flag"] = flag | setup_flag
            else:
                param_dict["host_setup_flag"] = setup_flag
        if index == last_index:
            if param_dict.get("host_setup_flag", None) is not None:
                flag = int(param_dict["host_setup_flag"])
                param_dict["host_setup_flag"] = flag | cleanup_flag
            else:
                param_dict["host_setup_flag"] = cleanup_flag
        index += 1

        # Add kvm module status
        kvm_default = get_module_params(param_dict.get("sysfs_dir", "sys"),
                                        "kvm")
        param_dict["kvm_default"] = kvm_default

        if param_dict.get("skip") == "yes":
            continue
        dependencies_satisfied = True
        for dep in param_dict.get("dep"):
            for test_name in status_dict.keys():
                if not dep in test_name:
                    continue
                # So the only really non-fatal state is WARN,
                # All the others make it not safe to proceed with dependency
                # execution
                if status_dict[test_name] not in ['GOOD', 'WARN']:
                    dependencies_satisfied = False
                    break
        test_iterations = int(param_dict.get("iterations", 1))
        test_tag = param_dict.get("vm_type") + "." + param_dict.get("shortname")

        if dependencies_satisfied:
            # Setting up profilers during test execution.
            profilers = param_dict.get("profilers", "").split()
            for profiler in profilers:
                job.profilers.add(profiler, **param_dict)
            # We need only one execution, profiled, hence we're passing
            # the profile_only parameter to job.run_test().
            profile_only = bool(profilers) or None
            test_timeout = int(param_dict.get("test_timeout", 14400))
            current_status = job.run_test_detail("virt",
                                                 params=param_dict,
                                                 tag=test_tag,
                                                 iterations=test_iterations,
                                                 profile_only=profile_only,
                                                 timeout=test_timeout)
            for profiler in profilers:
                job.profilers.delete(profiler)
        else:
            # We will force the test to fail as TestNA during preprocessing
            param_dict['dependency_failed'] = 'yes'
            current_status = job.run_test_detail("virt",
                                                 params=param_dict,
                                                 tag=test_tag,
                                                 iterations=test_iterations)

        if not current_status:
            failed = True
        status_dict[param_dict.get("name")] = current_status

    return not failed


def display_attributes(instance):
    """
    Inspects a given class instance attributes and displays them, convenient
    for debugging.
    """
    logging.debug("Attributes set:")
    for member in inspect.getmembers(instance):
        name, value = member
        attribute = getattr(instance, name)
        if not (name.startswith("__") or callable(attribute) or not value):
            logging.debug("    %s: %s", name, value)


def get_full_pci_id(pci_id):
    """
    Get full PCI ID of pci_id.

    @param pci_id: PCI ID of a device.
    """
    cmd = "lspci -D | awk '/%s/ {print $1}'" % pci_id
    status, full_id = commands.getstatusoutput(cmd)
    if status != 0:
        return None
    return full_id


def get_vendor_from_pci_id(pci_id):
    """
    Check out the device vendor ID according to pci_id.

    @param pci_id: PCI ID of a device.
    """
    cmd = "lspci -n | awk '/%s/ {print $3}'" % pci_id
    return re.sub(":", " ", commands.getoutput(cmd))


class Flag(str):
    """
    Class for easy merge cpuflags.
    """
    aliases = {}

    def __new__(cls, flag):
        if flag in Flag.aliases:
            flag = Flag.aliases[flag]
        return str.__new__(cls, flag)

    def __eq__(self, other):
        s = set(self.split("|"))
        o = set(other.split("|"))
        if s & o:
            return True
        else:
            return False

    def __str__(self):
        return self.split("|")[0]

    def __repr__(self):
        return self.split("|")[0]

    def __hash__(self, *args, **kwargs):
        return 0


kvm_map_flags_to_test = {
            Flag('avx')                        :set(['avx']),
            Flag('sse3|pni')                   :set(['sse3']),
            Flag('ssse3')                      :set(['ssse3']),
            Flag('sse4.1|sse4_1|sse4.2|sse4_2'):set(['sse4']),
            Flag('aes')                        :set(['aes','pclmul']),
            Flag('pclmuldq')                   :set(['pclmul']),
            Flag('pclmulqdq')                  :set(['pclmul']),
            Flag('rdrand')                     :set(['rdrand']),
            Flag('sse4a')                      :set(['sse4a']),
            Flag('fma4')                       :set(['fma4']),
            Flag('xop')                        :set(['xop']),
            }


kvm_map_flags_aliases = {
           'sse4_1'              :'sse4.1',
           'sse4_2'              :'sse4.2',
           'pclmuldq'            :'pclmulqdq',
           'sse3'                :'pni',
           'ffxsr'               :'fxsr_opt',
           'xd'                  :'nx',
           'i64'                 :'lm',
           'psn'                 :'pn',
           'clfsh'               :'clflush',
           'dts'                 :'ds',
           'htt'                 :'ht',
           'CMPXCHG8B'           :'cx8',
           'Page1GB'             :'pdpe1gb',
           'LahfSahf'            :'lahf_lm',
           'ExtApicSpace'        :'extapic',
           'AltMovCr8'           :'cr8_legacy',
           'cr8legacy'           :'cr8_legacy'
            }


def kvm_flags_to_stresstests(flags):
    """
    Covert [cpu flags] to [tests]

    @param cpuflags: list of cpuflags
    @return: Return tests like string.
    """
    tests = set([])
    for f in flags:
        tests |= kvm_map_flags_to_test[f]
    param = ""
    for f in tests:
        param += ","+f
    return param


def get_cpu_flags():
    """
    Returns a list of the CPU flags
    """
    flags_re = re.compile(r'^flags\s*:(.*)')
    for line in open('/proc/cpuinfo').readlines():
        match = flags_re.match(line)
        if match:
            return match.groups()[0].split()
    return []


def get_cpu_vendor(cpu_flags=[], verbose=True):
    """
    Returns the name of the CPU vendor, either intel, amd or unknown
    """
    if not cpu_flags:
        cpu_flags = get_cpu_flags()

    if 'vmx' in cpu_flags:
        vendor = 'GenuineIntel'
    elif 'svm' in cpu_flags:
        vendor = 'AuthenticAMD'
    else:
        vendor = 'unknown'

    if verbose:
        logging.debug("Detected CPU vendor as '%s'", vendor)
    return vendor


def get_support_machine_type(qemu_binary="/usr/libexec/qemu-kvm"):
    """
    Get the machine type the host support,return a list of machine type
    """
    o = utils.system_output("%s -M ?" % qemu_binary)
    s = re.findall("(\S*)\s*RHEL\s", o)
    c = re.findall("(RHEL.*PC)", o)
    return (s, c)


def get_cpu_model():
    """
    Get cpu model from host cpuinfo
    """
    def _make_up_pattern(flags):
        """
        Update the check pattern to a certain order and format
        """
        pattern_list = re.split(",", flags.strip())
        pattern_list.sort()
        pattern = r"(\b%s\b)" % pattern_list[0]
        for i in pattern_list[1:]:
            pattern += r".+(\b%s\b)" % i
        return pattern

    cpu_types = {"AuthenticAMD": ["Opteron_G5", "Opteron_G4", "Opteron_G3",
                                  "Opteron_G2", "Opteron_G1"],
                 "GenuineIntel": ["Haswell", "SandyBridge", "Westmere",
                                  "Nehalem", "Penryn", "Conroe"]}
    cpu_type_re = {"Opteron_G5":
                   "f16c,fma,tbm",
                   "Opteron_G4":
                   "avx,xsave,aes,sse4.2|sse4_2,sse4.1|sse4_1,cx16,ssse3,sse4a",
                   "Opteron_G3": "cx16,sse4a",
                   "Opteron_G2": "cx16",
                   "Opteron_G1": "",
                   "Haswell":
                   "fsgsbase,bmi1,hle,avx2,smep,bmi2,erms,invpcid,rtm",
                   "SandyBridge":
                   "avx,xsave,aes,sse4_2|sse4.2,sse4.1|sse4_1,cx16,ssse3",
                   "Westmere": "aes,sse4.2|sse4_2,sse4.1|sse4_1,cx16,ssse3",
                   "Nehalem": "sse4.2|sse4_2,sse4.1|sse4_1,cx16,ssse3",
                   "Penryn": "sse4.1|sse4_1,cx16,ssse3",
                   "Conroe": "ssse3"}

    flags = get_cpu_flags()
    flags.sort()
    cpu_flags = " ".join(flags)
    vendor = get_cpu_vendor(flags)

    cpu_model = ""
    if cpu_flags:
        for cpu_type in cpu_types.get(vendor):
            pattern = _make_up_pattern(cpu_type_re.get(cpu_type))
            if re.findall(pattern, cpu_flags):
                cpu_model = cpu_type
                break
    else:
        logging.warn("Can not get cpu flags from cpuinfo")

    if cpu_model:
        cpu_type_list = cpu_types.get(vendor)
        cpu_support_model = cpu_type_list[cpu_type_list.index(cpu_model):]
        cpu_model = ",".join(cpu_support_model)

    return cpu_model


def get_archive_tarball_name(source_dir, tarball_name, compression):
    '''
    Get the name for a tarball file, based on source, name and compression
    '''
    if tarball_name is None:
        tarball_name = os.path.basename(source_dir)

    if not tarball_name.endswith('.tar'):
        tarball_name = '%s.tar' % tarball_name

    if compression and not tarball_name.endswith('.%s' % compression):
        tarball_name = '%s.%s' % (tarball_name, compression)

    return tarball_name


def archive_as_tarball(source_dir, dest_dir, tarball_name=None,
                       compression='bz2', verbose=True):
    '''
    Saves the given source directory to the given destination as a tarball

    If the name of the archive is omitted, it will be taken from the
    source_dir. If it is an absolute path, dest_dir will be ignored. But,
    if both the destination directory and tarball anem is given, and the
    latter is not an absolute path, they will be combined.

    For archiving directory '/tmp' in '/net/server/backup' as file
    'tmp.tar.bz2', simply use:

    >>> utils_misc.archive_as_tarball('/tmp', '/net/server/backup')

    To save the file it with a different name, say 'host1-tmp.tar.bz2'
    and save it under '/net/server/backup', use:

    >>> utils_misc.archive_as_tarball('/tmp', '/net/server/backup',
                                      'host1-tmp')

    To save with gzip compression instead (resulting in the file
    '/net/server/backup/host1-tmp.tar.gz'), use:

    >>> utils_misc.archive_as_tarball('/tmp', '/net/server/backup',
                                      'host1-tmp', 'gz')
    '''
    tarball_name = get_archive_tarball_name(source_dir,
                                            tarball_name,
                                            compression)
    if not os.path.isabs(tarball_name):
        tarball_path = os.path.join(dest_dir, tarball_name)
    else:
        tarball_path = tarball_name

    if verbose:
        logging.debug('Archiving %s as %s' % (source_dir,
                                              tarball_path))

    os.chdir(os.path.dirname(source_dir))
    tarball = tarfile.TarFile(name=tarball_path, mode='w')
    tarball = tarball.open(name=tarball_path, mode='w:%s' % compression)
    tarball.add(os.path.basename(source_dir))
    tarball.close()


def parallel(targets):
    """
    Run multiple functions in parallel.

    @param targets: A sequence of tuples or functions.  If it's a sequence of
            tuples, each tuple will be interpreted as (target, args, kwargs) or
            (target, args) or (target,) depending on its length.  If it's a
            sequence of functions, the functions will be called without
            arguments.
    @return: A list of the values returned by the functions called.
    """
    threads = []
    for target in targets:
        if isinstance(target, tuple) or isinstance(target, list):
            t = utils.InterruptedThread(*target)
        else:
            t = utils.InterruptedThread(target)
        threads.append(t)
        t.start()
    return [t.join() for t in threads]


class VirtLoggingConfig(logging_config.LoggingConfig):
    """
    Used with the sole purpose of providing convenient logging setup
    for the KVM test auxiliary programs.
    """
    def configure_logging(self, results_dir=None, verbose=False):
        super(VirtLoggingConfig, self).configure_logging(use_console=True,
                                                         verbose=verbose)


class KojiDirIndexParser(HTMLParser.HTMLParser):
    '''
    Parser for HTML directory index pages, specialized to look for RPM links
    '''
    def __init__(self):
        '''
        Initializes a new KojiDirListParser instance
        '''
        HTMLParser.HTMLParser.__init__(self)
        self.package_file_names = []


    def handle_starttag(self, tag, attrs):
        '''
        Handle tags during the parsing

        This just looks for links ('a' tags) for files ending in .rpm
        '''
        if tag == 'a':
            for k, v in attrs:
                if k == 'href' and v.endswith('.rpm'):
                    self.package_file_names.append(v)


class RPMFileNameInfo:
    '''
    Simple parser for RPM based on information present on the filename itself
    '''
    def __init__(self, filename):
        '''
        Initializes a new RpmInfo instance based on a filename
        '''
        self.filename = filename


    def get_filename_without_suffix(self):
        '''
        Returns the filename without the default RPM suffix
        '''
        assert self.filename.endswith('.rpm')
        return self.filename[0:-4]


    def get_filename_without_arch(self):
        '''
        Returns the filename without the architecture

        This also excludes the RPM suffix, that is, removes the leading arch
        and RPM suffix.
        '''
        wo_suffix = self.get_filename_without_suffix()
        arch_sep = wo_suffix.rfind('.')
        return wo_suffix[:arch_sep]


    def get_arch(self):
        '''
        Returns just the architecture as present on the RPM filename
        '''
        wo_suffix = self.get_filename_without_suffix()
        arch_sep = wo_suffix.rfind('.')
        return wo_suffix[arch_sep+1:]


    def get_nvr_info(self):
        '''
        Returns a dictionary with the name, version and release components

        If koji is not installed, this returns None
        '''
        if not KOJI_INSTALLED:
            return None
        return koji.util.koji.parse_NVR(self.get_filename_without_arch())


class KojiClient(object):
    """
    Stablishes a connection with the build system, either koji or brew.

    This class provides convenience methods to retrieve information on packages
    and the packages themselves hosted on the build system. Packages should be
    specified in the KojiPgkSpec syntax.
    """

    CMD_LOOKUP_ORDER = ['/usr/bin/brew', '/usr/bin/koji' ]

    CONFIG_MAP = {'/usr/bin/brew': '/etc/brewkoji.conf',
                  '/usr/bin/koji': '/etc/koji.conf'}


    def __init__(self, cmd=None):
        """
        Verifies whether the system has koji or brew installed, then loads
        the configuration file that will be used to download the files.

        @type cmd: string
        @param cmd: Optional command name, either 'brew' or 'koji'. If not
                set, get_default_command() is used and to look for
                one of them.
        @raise: ValueError
        """
        if not KOJI_INSTALLED:
            raise ValueError('No koji/brew installed on the machine')

        # Instance variables used by many methods
        self.command = None
        self.config = None
        self.config_options = {}
        self.session = None

        # Set koji command or get default
        if cmd is None:
            self.command = self.get_default_command()
        else:
            self.command = cmd

        # Check koji command
        if not self.is_command_valid():
            raise ValueError('Koji command "%s" is not valid' % self.command)

        # Assuming command is valid, set configuration file and read it
        self.config = self.CONFIG_MAP[self.command]
        self.read_config()

        # Setup koji session
        server_url = self.config_options['server']
        session_options = self.get_session_options()
        self.session = koji.ClientSession(server_url,
                                          session_options)


    def read_config(self, check_is_valid=True):
        '''
        Reads options from the Koji configuration file

        By default it checks if the koji configuration is valid

        @type check_valid: boolean
        @param check_valid: whether to include a check on the configuration
        @raises: ValueError
        @returns: None
        '''
        if check_is_valid:
            if not self.is_config_valid():
                raise ValueError('Koji config "%s" is not valid' % self.config)

        config = ConfigParser.ConfigParser()
        config.read(self.config)

        basename = os.path.basename(self.command)
        for name, value in config.items(basename):
            self.config_options[name] = value


    def get_session_options(self):
        '''
        Filter only options necessary for setting up a cobbler client session

        @returns: only the options used for session setup
        '''
        session_options = {}
        for name, value in self.config_options.items():
            if name in ('user', 'password', 'debug_xmlrpc', 'debug'):
                session_options[name] = value
        return session_options


    def is_command_valid(self):
        '''
        Checks if the currently set koji command is valid

        @returns: True or False
        '''
        koji_command_ok = True

        if not os.path.isfile(self.command):
            logging.error('Koji command "%s" is not a regular file',
                          self.command)
            koji_command_ok = False

        if not os.access(self.command, os.X_OK):
            logging.warn('Koji command "%s" is not executable: this is '
                         'not fatal but indicates an unexpected situation',
                         self.command)

        if not self.command in self.CONFIG_MAP.keys():
            logging.error('Koji command "%s" does not have a configuration '
                          'file associated to it', self.command)
            koji_command_ok = False

        return koji_command_ok


    def is_config_valid(self):
        '''
        Checks if the currently set koji configuration is valid

        @returns: True or False
        '''
        koji_config_ok = True

        if not os.path.isfile(self.config):
            logging.error('Koji config "%s" is not a regular file', self.config)
            koji_config_ok = False

        if not os.access(self.config, os.R_OK):
            logging.error('Koji config "%s" is not readable', self.config)
            koji_config_ok = False

        config = ConfigParser.ConfigParser()
        config.read(self.config)
        basename = os.path.basename(self.command)
        if not config.has_section(basename):
            logging.error('Koji configuration file "%s" does not have a '
                          'section "%s", named after the base name of the '
                          'currently set koji command "%s"', self.config,
                           basename, self.command)
            koji_config_ok = False

        return koji_config_ok


    def get_default_command(self):
        '''
        Looks up for koji or brew "binaries" on the system

        Systems with plain koji usually don't have a brew cmd, while systems
        with koji, have *both* koji and brew utilities. So we look for brew
        first, and if found, we consider that the system is configured for
        brew. If not, we consider this is a system with plain koji.

        @returns: either koji or brew command line executable path, or None
        '''
        koji_command = None
        for command in self.CMD_LOOKUP_ORDER:
            if os.path.isfile(command):
                koji_command = command
                break
            else:
                koji_command_basename = os.path.basename(command)
                try:
                    koji_command = os_dep.command(koji_command_basename)
                    break
                except ValueError:
                    pass
        return koji_command


    def get_pkg_info(self, pkg):
        '''
        Returns information from Koji on the package

        @type pkg: KojiPkgSpec
        @param pkg: information about the package, as a KojiPkgSpec instance

        @returns: information from Koji about the specified package
        '''
        info = {}
        if pkg.build is not None:
            info = self.session.getBuild(int(pkg.build))
        elif pkg.tag is not None and pkg.package is not None:
            builds = self.session.listTagged(pkg.tag,
                                             latest=True,
                                             inherit=True,
                                             package=pkg.package)
            if builds:
                info = builds[0]
        return info


    def is_pkg_valid(self, pkg):
        '''
        Checks if this package is altogether valid on Koji

        This verifies if the build or tag specified in the package
        specification actually exist on the Koji server

        @returns: True or False
        '''
        valid = True
        if pkg.build:
            if not self.is_pkg_spec_build_valid(pkg):
                valid = False
        elif pkg.tag:
            if not self.is_pkg_spec_tag_valid(pkg):
                valid = False
        else:
            valid = False
        return valid


    def is_pkg_spec_build_valid(self, pkg):
        '''
        Checks if build is valid on Koji

        @param pkg: a Pkg instance
        '''
        if pkg.build is not None:
            info = self.session.getBuild(int(pkg.build))
            if info:
                return True
        return False


    def is_pkg_spec_tag_valid(self, pkg):
        '''
        Checks if tag is valid on Koji

        @type pkg: KojiPkgSpec
        @param pkg: a package specification
        '''
        if pkg.tag is not None:
            tag = self.session.getTag(pkg.tag)
            if tag:
                return True
        return False


    def get_pkg_rpm_info(self, pkg, arch=None):
        '''
        Returns a list of infomation on the RPM packages found on koji

        @type pkg: KojiPkgSpec
        @param pkg: a package specification
        @type arch: string
        @param arch: packages built for this architecture, but also including
                architecture independent (noarch) packages
        '''
        if arch is None:
            arch = utils.get_arch()
        rpms = []
        info = self.get_pkg_info(pkg)
        if info:
            rpms = self.session.listRPMs(buildID=info['id'],
                                         arches=[arch, 'noarch'])
            if pkg.subpackages:
                rpms = [d for d in rpms if d['name'] in pkg.subpackages]
        return rpms


    def get_pkg_rpm_names(self, pkg, arch=None):
        '''
        Gets the names for the RPM packages specified in pkg

        @type pkg: KojiPkgSpec
        @param pkg: a package specification
        @type arch: string
        @param arch: packages built for this architecture, but also including
                architecture independent (noarch) packages
        '''
        if arch is None:
            arch = utils.get_arch()
        rpms = self.get_pkg_rpm_info(pkg, arch)
        return [rpm['name'] for rpm in rpms]


    def get_pkg_rpm_file_names(self, pkg, arch=None):
        '''
        Gets the file names for the RPM packages specified in pkg

        @type pkg: KojiPkgSpec
        @param pkg: a package specification
        @type arch: string
        @param arch: packages built for this architecture, but also including
                architecture independent (noarch) packages
        '''
        if arch is None:
            arch = utils.get_arch()
        rpm_names = []
        rpms = self.get_pkg_rpm_info(pkg, arch)
        for rpm in rpms:
            arch_rpm_name = koji.pathinfo.rpm(rpm)
            rpm_name = os.path.basename(arch_rpm_name)
            rpm_names.append(rpm_name)
        return rpm_names


    def get_pkg_base_url(self):
        '''
        Gets the base url for packages in Koji
        '''
        if self.config_options.has_key('pkgurl'):
            return self.config_options['pkgurl']
        else:
            return "%s/%s" % (self.config_options['topurl'],
                              'packages')


    def get_scratch_base_url(self):
        '''
        Gets the base url for scratch builds in Koji
        '''
        one_level_up = os.path.dirname(self.get_pkg_base_url())
        return "%s/%s" % (one_level_up, 'scratch')


    def get_pkg_urls(self, pkg, arch=None):
        '''
        Gets the urls for the packages specified in pkg

        @type pkg: KojiPkgSpec
        @param pkg: a package specification
        @type arch: string
        @param arch: packages built for this architecture, but also including
                architecture independent (noarch) packages
        '''
        info = self.get_pkg_info(pkg)
        rpms = self.get_pkg_rpm_info(pkg, arch)
        rpm_urls = []
        base_url = self.get_pkg_base_url()

        for rpm in rpms:
            rpm_name = koji.pathinfo.rpm(rpm)
            url = ("%s/%s/%s/%s/%s" % (base_url,
                                       info['package_name'],
                                       info['version'], info['release'],
                                       rpm_name))
            rpm_urls.append(url)
        return rpm_urls


    def get_pkgs(self, pkg, dst_dir, arch=None):
        '''
        Download the packages

        @type pkg: KojiPkgSpec
        @param pkg: a package specification
        @type dst_dir: string
        @param dst_dir: the destination directory, where the downloaded
                packages will be saved on
        @type arch: string
        @param arch: packages built for this architecture, but also including
                architecture independent (noarch) packages
        '''
        rpm_urls = self.get_pkg_urls(pkg, arch)
        for url in rpm_urls:
            utils.get_file(url,
                           os.path.join(dst_dir, os.path.basename(url)))


    def get_scratch_pkg_urls(self, pkg, arch=None):
        '''
        Gets the urls for the scratch packages specified in pkg

        @type pkg: KojiScratchPkgSpec
        @param pkg: a scratch package specification
        @type arch: string
        @param arch: packages built for this architecture, but also including
                architecture independent (noarch) packages
        '''
        rpm_urls = []

        if arch is None:
            arch = utils.get_arch()
        arches = [arch, 'noarch']

        index_url = "%s/%s/task_%s" % (self.get_scratch_base_url(),
                                       pkg.user,
                                       pkg.task)
        index_parser = KojiDirIndexParser()
        index_parser.feed(urllib.urlopen(index_url).read())

        if pkg.subpackages:
            for p in pkg.subpackages:
                for pfn in index_parser.package_file_names:
                    r = RPMFileNameInfo(pfn)
                    info = r.get_nvr_info()
                    if (p == info['name'] and
                        r.get_arch() in arches):
                        rpm_urls.append("%s/%s" % (index_url, pfn))
        else:
            for pfn in index_parser.package_file_names:
                if (RPMFileNameInfo(pfn).get_arch() in arches):
                    rpm_urls.append("%s/%s" % (index_url, pfn))

        return rpm_urls


    def get_scratch_pkgs(self, pkg, dst_dir, arch=None):
        '''
        Download the packages from a scratch build

        @type pkg: KojiScratchPkgSpec
        @param pkg: a scratch package specification
        @type dst_dir: string
        @param dst_dir: the destination directory, where the downloaded
                packages will be saved on
        @type arch: string
        @param arch: packages built for this architecture, but also including
                architecture independent (noarch) packages
        '''
        rpm_urls = self.get_scratch_pkg_urls(pkg, arch)
        for url in rpm_urls:
            utils.get_file(url,
                           os.path.join(dst_dir, os.path.basename(url)))


DEFAULT_KOJI_TAG = None
def set_default_koji_tag(tag):
    '''
    Sets the default tag that will be used
    '''
    global DEFAULT_KOJI_TAG
    DEFAULT_KOJI_TAG = tag


def get_default_koji_tag():
    return DEFAULT_KOJI_TAG


class KojiPkgSpec(object):
    '''
    A package specification syntax parser for Koji

    This holds information on either tag or build, and packages to be fetched
    from koji and possibly installed (features external do this class).

    New objects can be created either by providing information in the textual
    format or by using the actual parameters for tag, build, package and sub-
    packages. The textual format is useful for command line interfaces and
    configuration files, while using parameters is better for using this in
    a programatic fashion.

    The following sets of examples are interchangeable. Specifying all packages
    part of build number 1000:

        >>> from kvm_utils import KojiPkgSpec
        >>> pkg = KojiPkgSpec('1000')

        >>> pkg = KojiPkgSpec(build=1000)

    Specifying only a subset of packages of build number 1000:

        >>> pkg = KojiPkgSpec('1000:kernel,kernel-devel')

        >>> pkg = KojiPkgSpec(build=1000,
                              subpackages=['kernel', 'kernel-devel'])

    Specifying the latest build for the 'kernel' package tagged with 'dist-f14':

        >>> pkg = KojiPkgSpec('dist-f14:kernel')

        >>> pkg = KojiPkgSpec(tag='dist-f14', package='kernel')

    Specifying the 'kernel' package using the default tag:

        >>> kvm_utils.set_default_koji_tag('dist-f14')
        >>> pkg = KojiPkgSpec('kernel')

        >>> pkg = KojiPkgSpec(package='kernel')

    Specifying the 'kernel' package using the default tag:

        >>> kvm_utils.set_default_koji_tag('dist-f14')
        >>> pkg = KojiPkgSpec('kernel')

        >>> pkg = KojiPkgSpec(package='kernel')

    If you do not specify a default tag, and give a package name without an
    explicit tag, your package specification is considered invalid:

        >>> print kvm_utils.get_default_koji_tag()
        None
        >>> print kvm_utils.KojiPkgSpec('kernel').is_valid()
        False

        >>> print kvm_utils.KojiPkgSpec(package='kernel').is_valid()
        False
    '''

    SEP = ':'

    def __init__(self, text='', tag=None, build=None,
                 package=None, subpackages=[]):
        '''
        Instantiates a new KojiPkgSpec object

        @type text: string
        @param text: a textual representation of a package on Koji that
                will be parsed
        @type tag: string
        @param tag: a koji tag, example: Fedora-14-RELEASE
                (see U{http://fedoraproject.org/wiki/Koji#Tags_and_Targets})
        @type build: number
        @param build: a koji build, example: 1001
                (see U{http://fedoraproject.org/wiki/Koji#Koji_Architecture})
        @type package: string
        @param package: a koji package, example: python
                (see U{http://fedoraproject.org/wiki/Koji#Koji_Architecture})
        @type subpackages: list of strings
        @param subpackages: a list of package names, usually a subset of
                the RPM packages generated by a given build
        '''

        # Set to None to indicate 'not set' (and be able to use 'is')
        self.tag = None
        self.build = None
        self.package = None
        self.subpackages = []

        self.default_tag = None

        # Textual representation takes precedence (most common use case)
        if text:
            self.parse(text)
        else:
            self.tag = tag
            self.build = build
            self.package = package
            self.subpackages = subpackages

        # Set the default tag, if set, as a fallback
        if not self.build and not self.tag:
            default_tag = get_default_koji_tag()
            if default_tag is not None:
                self.tag = default_tag


    def parse(self, text):
        '''
        Parses a textual representation of a package specification

        @type text: string
        @param text: textual representation of a package in koji
        '''
        parts = text.count(self.SEP) + 1
        if parts == 1:
            if text.isdigit():
                self.build = text
            else:
                self.package = text
        elif parts == 2:
            part1, part2 = text.split(self.SEP)
            if part1.isdigit():
                self.build = part1
                self.subpackages = part2.split(',')
            else:
                self.tag = part1
                self.package = part2
        elif parts >= 3:
            # Instead of erroring on more arguments, we simply ignore them
            # This makes the parser suitable for future syntax additions, such
            # as specifying the package architecture
            part1, part2, part3 = text.split(self.SEP)[0:3]
            self.tag = part1
            self.package = part2
            self.subpackages = part3.split(',')


    def _is_invalid_neither_tag_or_build(self):
        '''
        Checks if this package is invalid due to not having either a valid
        tag or build set, that is, both are empty.

        @returns: True if this is invalid and False if it's valid
        '''
        return (self.tag is None and self.build is None)


    def _is_invalid_package_but_no_tag(self):
        '''
        Checks if this package is invalid due to having a package name set
        but tag or build set, that is, both are empty.

        @returns: True if this is invalid and False if it's valid
        '''
        return (self.package and not self.tag)


    def _is_invalid_subpackages_but_no_main_package(self):
        '''
        Checks if this package is invalid due to having a tag set (this is Ok)
        but specifying subpackage names without specifying the main package
        name.

        Specifying subpackages without a main package name is only valid when
        a build is used instead of a tag.

        @returns: True if this is invalid and False if it's valid
        '''
        return (self.tag and self.subpackages and not self.package)


    def is_valid(self):
        '''
        Checks if this package specification is valid.

        Being valid means that it has enough and not conflicting information.
        It does not validate that the packages specified actually existe on
        the Koji server.

        @returns: True or False
        '''
        if self._is_invalid_neither_tag_or_build():
            return False
        elif self._is_invalid_package_but_no_tag():
            return False
        elif self._is_invalid_subpackages_but_no_main_package():
            return False

        return True


    def describe_invalid(self):
        '''
        Describes why this is not valid, in a human friendly way
        '''
        if self._is_invalid_neither_tag_or_build():
            return ('neither a tag nor a build were set, one of them '
                    'must be set')
        elif self._is_invalid_package_but_no_tag():
            return 'package name specified but no tag is set'
        elif self._is_invalid_subpackages_but_no_main_package():
            return 'subpackages specified but no main package is set'

        return 'unkwown reason, seems to be valid'


    def describe(self):
        '''
        Describe this package specification, in a human friendly way

        @returns: package specification description
        '''
        if self.is_valid():
            description = ''
            if not self.subpackages:
                description += 'all subpackages from %s ' % self.package
            else:
                description += ('only subpackage(s) %s from package %s ' %
                                (', '.join(self.subpackages), self.package))

            if self.build:
                description += 'from build %s' % self.build
            elif self.tag:
                description += 'tagged with %s' % self.tag
            else:
                raise ValueError, 'neither build or tag is set'

            return description
        else:
            return ('Invalid package specification: %s' %
                    self.describe_invalid())


    def to_text(self):
        '''
        Return the textual representation of this package spec

        The output should be consumable by parse() and produce the same
        package specification.

        We find that it's acceptable to put the currently set default tag
        as the package explicit tag in the textual definition for completeness.

        @returns: package specification in a textual representation
        '''
        default_tag = get_default_koji_tag()

        if self.build:
            if self.subpackages:
                return "%s:%s" % (self.build, ",".join(self.subpackages))
            else:
                return "%s" % self.build

        elif self.tag:
            if self.subpackages:
                return "%s:%s:%s" % (self.tag, self.package,
                                     ",".join(self.subpackages))
            else:
                return "%s:%s" % (self.tag, self.package)

        elif default_tag is not None:
            # neither build or tag is set, try default_tag as a fallback
            if self.subpackages:
                return "%s:%s:%s" % (default_tag, self.package,
                                     ",".join(self.subpackages))
            else:
                return "%s:%s" % (default_tag, self.package)
        else:
            raise ValueError, 'neither build or tag is set'


    def __repr__(self):
        return ("<KojiPkgSpec tag=%s build=%s pkg=%s subpkgs=%s>" %
                (self.tag, self.build, self.package,
                 ", ".join(self.subpackages)))


class KojiScratchPkgSpec(object):
    '''
    A package specification syntax parser for Koji scratch builds

    This holds information on user, task and subpackages to be fetched
    from koji and possibly installed (features external do this class).

    New objects can be created either by providing information in the textual
    format or by using the actual parameters for user, task and subpackages.
    The textual format is useful for command line interfaces and configuration
    files, while using parameters is better for using this in a programatic
    fashion.

    This package definition has a special behaviour: if no subpackages are
    specified, all packages of the chosen architecture (plus noarch packages)
    will match.

    The following sets of examples are interchangeable. Specifying all packages
    from a scratch build (whose task id is 1000) sent by user jdoe:

        >>> from kvm_utils import KojiScratchPkgSpec
        >>> pkg = KojiScratchPkgSpec('jdoe:1000')

        >>> pkg = KojiScratchPkgSpec(user=jdoe, task=1000)

    Specifying some packages from a scratch build whose task id is 1000, sent
    by user jdoe:

        >>> pkg = KojiScratchPkgSpec('jdoe:1000:kernel,kernel-devel')

        >>> pkg = KojiScratchPkgSpec(user=jdoe, task=1000,
                                     subpackages=['kernel', 'kernel-devel'])
    '''

    SEP = ':'

    def __init__(self, text='', user=None, task=None, subpackages=[]):
        '''
        Instantiates a new KojiScratchPkgSpec object

        @type text: string
        @param text: a textual representation of a scratch build on Koji that
                will be parsed
        @type task: number
        @param task: a koji task id, example: 1001
        @type subpackages: list of strings
        @param subpackages: a list of package names, usually a subset of
                the RPM packages generated by a given build
        '''
        # Set to None to indicate 'not set' (and be able to use 'is')
        self.user = None
        self.task = None
        self.subpackages = []

        # Textual representation takes precedence (most common use case)
        if text:
            self.parse(text)
        else:
            self.user = user
            self.task = task
            self.subpackages = subpackages


    def parse(self, text):
        '''
        Parses a textual representation of a package specification

        @type text: string
        @param text: textual representation of a package in koji
        '''
        parts = text.count(self.SEP) + 1
        if parts == 1:
            raise ValueError('KojiScratchPkgSpec requires a user and task id')
        elif parts == 2:
            self.user, self.task = text.split(self.SEP)
        elif parts >= 3:
            # Instead of erroring on more arguments, we simply ignore them
            # This makes the parser suitable for future syntax additions, such
            # as specifying the package architecture
            part1, part2, part3 = text.split(self.SEP)[0:3]
            self.user = part1
            self.task = part2
            self.subpackages = part3.split(',')


    def __repr__(self):
        return ("<KojiScratchPkgSpec user=%s task=%s subpkgs=%s>" %
                (self.user, self.task, ", ".join(self.subpackages)))


def umount(src, mount_point, fstype):
    """
    Umount the src mounted in mount_point.

    @src: mount source
    @mount_point: mount point
    @type: file system type
    """

    mount_string = "%s %s %s" % (src, mount_point, fstype)
    if mount_string in file("/etc/mtab").read():
        umount_cmd = "umount %s" % mount_point
        try:
            utils.system(umount_cmd)
            return True
        except error.CmdError:
            return False
    else:
        logging.debug("%s is not mounted under %s", src, mount_point)
        return True


def mount(src, mount_point, fstype, perm="rw"):
    """
    Mount the src into mount_point of the host.

    @src: mount source
    @mount_point: mount point
    @fstype: file system type
    @perm: mount premission
    """
    umount(src, mount_point, fstype)
    mount_string = "%s %s %s %s" % (src, mount_point, fstype, perm)

    if mount_string in file("/etc/mtab").read():
        logging.debug("%s is already mounted in %s with %s",
                      src, mount_point, perm)
        return True

    mount_cmd = "mount -t %s %s %s -o %s" % (fstype, src, mount_point, perm)
    try:
        utils.system(mount_cmd)
    except error.CmdError:
        return False

    logging.debug("Verify the mount through /etc/mtab")
    if mount_string in file("/etc/mtab").read():
        logging.debug("%s is successfully mounted", src)
        return True
    else:
        logging.error("Can't find mounted NFS share - /etc/mtab contents \n%s",
                      file("/etc/mtab").read())
        return False


class GitRepoParamHelper(git.GitRepoHelper):
    '''
    Helps to deal with git repos specified in cartersian config files

    This class attempts to make it simple to manage a git repo, by using a
    naming standard that follows this basic syntax:

    <prefix>_name_<suffix>

    <prefix> is always 'git_repo' and <suffix> sets options for this git repo.
    Example for repo named foo:

    git_repo_foo_uri = git://git.foo.org/foo.git
    git_repo_foo_base_uri = /home/user/code/foo
    git_repo_foo_branch = master
    git_repo_foo_lbranch = master
    git_repo_foo_commit = bb5fb8e678aabe286e74c4f2993dc2a9e550b627
    '''
    def __init__(self, params, name, destination_dir):
        '''
        Instantiates a new GitRepoParamHelper
        '''
        self.params = params
        self.name = name
        self.destination_dir = destination_dir
        self._parse_params()


    def _parse_params(self):
        '''
        Parses the params items for entries related to this repo

        This method currently does everything that the parent class __init__()
        method does, that is, sets all instance variables needed by other
        methods. That means it's not strictly necessary to call parent's
        __init__().
        '''
        config_prefix = 'git_repo_%s' % self.name
        logging.debug('Parsing parameters for git repo %s, configuration '
                      'prefix is %s' % (self.name, config_prefix))

        self.base_uri = self.params.get('%s_base_uri' % config_prefix)
        if self.base_uri is None:
            logging.debug('Git repo %s base uri is not set' % self.name)
        else:
            logging.debug('Git repo %s base uri: %s' % (self.name,
                                                        self.base_uri))

        self.uri = self.params.get('%s_uri' % config_prefix)
        logging.debug('Git repo %s uri: %s' % (self.name, self.uri))

        self.branch = self.params.get('%s_branch' % config_prefix, 'master')
        logging.debug('Git repo %s branch: %s' % (self.name, self.branch))

        self.lbranch = self.params.get('%s_lbranch' % config_prefix)
        if self.lbranch is None:
            self.lbranch = self.branch
        logging.debug('Git repo %s lbranch: %s' % (self.name, self.lbranch))

        self.commit = self.params.get('%s_commit' % config_prefix)
        if self.commit is None:
            logging.debug('Git repo %s commit is not set' % self.name)
        else:
            logging.debug('Git repo %s commit: %s' % (self.name, self.commit))

        self.cmd = os_dep.command('git')


class LocalSourceDirHelper(object):
    '''
    Helper class to deal with source code sitting somewhere in the filesystem
    '''
    def __init__(self, source_dir, destination_dir):
        '''
        @param source_dir:
        @param destination_dir:
        @return: new LocalSourceDirHelper instance
        '''
        self.source = source_dir
        self.destination = destination_dir


    def execute(self):
        '''
        Copies the source directory to the destination directory
        '''
        if os.path.isdir(self.destination):
            shutil.rmtree(self.destination)

        if os.path.isdir(self.source):
            shutil.copytree(self.source, self.destination)


class LocalSourceDirParamHelper(LocalSourceDirHelper):
    '''
    Helps to deal with source dirs specified in cartersian config files

    This class attempts to make it simple to manage a source dir, by using a
    naming standard that follows this basic syntax:

    <prefix>_name_<suffix>

    <prefix> is always 'local_src' and <suffix> sets options for this source
    dir.  Example for source dir named foo:

    local_src_foo_path = /home/user/foo
    '''
    def __init__(self, params, name, destination_dir):
        '''
        Instantiate a new LocalSourceDirParamHelper
        '''
        self.params = params
        self.name = name
        self.destination_dir = destination_dir
        self._parse_params()


    def _parse_params(self):
        '''
        Parses the params items for entries related to source dir
        '''
        config_prefix = 'local_src_%s' % self.name
        logging.debug('Parsing parameters for local source %s, configuration '
                      'prefix is %s' % (self.name, config_prefix))

        self.path = self.params.get('%s_path' % config_prefix)
        logging.debug('Local source directory %s path: %s' % (self.name,
                                                              self.path))
        self.source = self.path
        self.destination = self.destination_dir


class LocalTarHelper(object):
    '''
    Helper class to deal with source code in a local tarball
    '''
    def __init__(self, source, destination_dir):
        self.source = source
        self.destination = destination_dir


    def extract(self):
        '''
        Extracts the tarball into the destination directory
        '''
        if os.path.isdir(self.destination):
            shutil.rmtree(self.destination)

        if os.path.isfile(self.source) and tarfile.is_tarfile(self.source):

            name = os.path.basename(self.destination)
            temp_dir = os.path.join(os.path.dirname(self.destination),
                                    '%s.tmp' % name)
            logging.debug('Temporary directory for extracting tarball is %s' %
                          temp_dir)

            if not os.path.isdir(temp_dir):
                os.makedirs(temp_dir)

            tarball = tarfile.open(self.source)
            tarball.extractall(temp_dir)

            #
            # If there's a directory at the toplevel of the tarfile, assume
            # it's the root for the contents, usually source code
            #
            tarball_info = tarball.members[0]
            if tarball_info.isdir():
                content_path = os.path.join(temp_dir,
                                            tarball_info.name)
            else:
                content_path = temp_dir

            #
            # Now move the content directory to the final destination
            #
            shutil.move(content_path, self.destination)

        else:
            raise OSError("%s is not a file or tar file" % self.source)


    def execute(self):
        '''
        Executes all action this helper is suposed to perform

        This is the main entry point method for this class, and all other
        helper classes.
        '''
        self.extract()


class LocalTarParamHelper(LocalTarHelper):
    '''
    Helps to deal with source tarballs specified in cartersian config files

    This class attempts to make it simple to manage a tarball with source code,
    by using a  naming standard that follows this basic syntax:

    <prefix>_name_<suffix>

    <prefix> is always 'local_tar' and <suffix> sets options for this source
    tarball.  Example for source tarball named foo:

    local_tar_foo_path = /tmp/foo-1.0.tar.gz
    '''
    def __init__(self, params, name, destination_dir):
        '''
        Instantiates a new LocalTarParamHelper
        '''
        self.params = params
        self.name = name
        self.destination_dir = destination_dir
        self._parse_params()


    def _parse_params(self):
        '''
        Parses the params items for entries related to this local tar helper
        '''
        config_prefix = 'local_tar_%s' % self.name
        logging.debug('Parsing parameters for local tar %s, configuration '
                      'prefix is %s' % (self.name, config_prefix))

        self.path = self.params.get('%s_path' % config_prefix)
        logging.debug('Local source tar %s path: %s' % (self.name,
                                                        self.path))
        self.source = self.path
        self.destination = self.destination_dir


class RemoteTarHelper(LocalTarHelper):
    '''
    Helper that fetches a tarball and extracts it locally
    '''
    def __init__(self, source_uri, destination_dir):
        self.source = source_uri
        self.destination = destination_dir


    def execute(self):
        '''
        Executes all action this helper class is suposed to perform

        This is the main entry point method for this class, and all other
        helper classes.

        This implementation fetches the remote tar file and then extracts
        it using the functionality present in the parent class.
        '''
        name = os.path.basename(self.source)
        base_dest = os.path.dirname(self.destination_dir)
        dest = os.path.join(base_dest, name)
        utils.get_file(self.source, dest)
        self.source = dest
        self.extract()


class RemoteTarParamHelper(RemoteTarHelper):
    '''
    Helps to deal with remote source tarballs specified in cartersian config

    This class attempts to make it simple to manage a tarball with source code,
    by using a  naming standard that follows this basic syntax:

    <prefix>_name_<suffix>

    <prefix> is always 'local_tar' and <suffix> sets options for this source
    tarball.  Example for source tarball named foo:

    remote_tar_foo_uri = http://foo.org/foo-1.0.tar.gz
    '''
    def __init__(self, params, name, destination_dir):
        '''
        Instantiates a new RemoteTarParamHelper instance
        '''
        self.params = params
        self.name = name
        self.destination_dir = destination_dir
        self._parse_params()


    def _parse_params(self):
        '''
        Parses the params items for entries related to this remote tar helper
        '''
        config_prefix = 'remote_tar_%s' % self.name
        logging.debug('Parsing parameters for remote tar %s, configuration '
                      'prefix is %s' % (self.name, config_prefix))

        self.uri = self.params.get('%s_uri' % config_prefix)
        logging.debug('Remote source tar %s uri: %s' % (self.name,
                                                        self.uri))
        self.source = self.uri
        self.destination = self.destination_dir


class PatchHelper(object):
    '''
    Helper that encapsulates the patching of source code with patch files
    '''
    def __init__(self, source_dir, patches):
        '''
        Initializes a new PatchHelper
        '''
        self.source_dir = source_dir
        self.patches = patches


    def download(self):
        '''
        Copies patch files from remote locations to the source directory
        '''
        for patch in self.patches:
            utils.get_file(patch, os.path.join(self.source_dir,
                                               os.path.basename(patch)))


    def patch(self):
        '''
        Patches the source dir with all patch files
        '''
        os.chdir(self.source_dir)
        for patch in self.patches:
            patch_file = os.path.join(self.source_dir,
                                      os.path.basename(patch))
            utils.system('patch -p1 < %s' % os.path.basename(patch))


    def execute(self):
        '''
        Performs all steps necessary to download patches and apply them
        '''
        self.download()
        self.patch()


class PatchParamHelper(PatchHelper):
    '''
    Helps to deal with patches specified in cartersian config files

    This class attempts to make it simple to patch source coude, by using a
    naming standard that follows this basic syntax:

    [<git_repo>|<local_src>|<local_tar>|<remote_tar>]_<name>_patches

    <prefix> is either a 'local_src' or 'git_repo', that, together with <name>
    specify a directory containing source code to receive the patches. That is,
    for source code coming from git repo foo, patches would be specified as:

    git_repo_foo_patches = ['http://foo/bar.patch', 'http://foo/baz.patch']

    And for for patches to be applied on local source code named also foo:

    local_src_foo_patches = ['http://foo/bar.patch', 'http://foo/baz.patch']
    '''
    def __init__(self, params, prefix, source_dir):
        '''
        Initializes a new PatchParamHelper instance
        '''
        self.params = params
        self.prefix = prefix
        self.source_dir = source_dir
        self._parse_params()


    def _parse_params(self):
        '''
        Parses the params items for entries related to this set of patches

        This method currently does everything that the parent class __init__()
        method does, that is, sets all instance variables needed by other
        methods. That means it's not strictly necessary to call parent's
        __init__().
        '''
        logging.debug('Parsing patch parameters for prefix %s' % self.prefix)
        patches_param_key = '%s_patches' % self.prefix

        self.patches_str = self.params.get(patches_param_key, '[]')
        logging.debug('Patches config for prefix %s: %s' % (self.prefix,
                                                            self.patches_str))

        self.patches = eval(self.patches_str)
        logging.debug('Patches for prefix %s: %s' % (self.prefix,
                                                     ", ".join(self.patches)))


class GnuSourceBuildInvalidSource(Exception):
    '''
    Exception raised when build source dir/file is not valid
    '''
    pass


class SourceBuildFailed(Exception):
    '''
    Exception raised when building with parallel jobs fails

    This serves as feedback for code using *BuildHelper
    '''
    pass


class SourceBuildParallelFailed(Exception):
    '''
    Exception raised when building with parallel jobs fails

    This serves as feedback for code using *BuildHelper
    '''
    pass


class GnuSourceBuildHelper(object):
    '''
    Handles software installation of GNU-like source code

    This basically means that the build will go though the classic GNU
    autotools steps: ./configure, make, make install
    '''
    def __init__(self, source, build_dir, prefix,
                 configure_options=[]):
        '''
        @type source: string
        @param source: source directory or tarball
        @type prefix: string
        @param prefix: installation prefix
        @type build_dir: string
        @param build_dir: temporary directory used for building the source code
        @type configure_options: list
        @param configure_options: options to pass to configure
        @throws: GnuSourceBuildInvalidSource
        '''
        self.source = source
        self.build_dir = build_dir
        self.prefix = prefix
        self.configure_options = configure_options
        self.install_debug_info = True
        self.include_pkg_config_path()


    def include_pkg_config_path(self):
        '''
        Adds the current prefix to the list of paths that pkg-config searches

        This is currently not optional as there is no observed adverse side
        effects of enabling this. As the "prefix" is usually only valid during
        a test run, we believe that having other pkg-config files (*.pc) in
        either '<prefix>/share/pkgconfig' or '<prefix>/lib/pkgconfig' is
        exactly for the purpose of using them.

        @returns: None
        '''
        env_var = 'PKG_CONFIG_PATH'

        include_paths = [os.path.join(self.prefix, 'share', 'pkgconfig'),
                         os.path.join(self.prefix, 'lib', 'pkgconfig')]

        if os.environ.has_key(env_var):
            paths = os.environ[env_var].split(':')
            for include_path in include_paths:
                if include_path not in paths:
                    paths.append(include_path)
            os.environ[env_var] = ':'.join(paths)
        else:
            os.environ[env_var] = ':'.join(include_paths)

        logging.debug('PKG_CONFIG_PATH is: %s' % os.environ['PKG_CONFIG_PATH'])


    def get_configure_path(self):
        '''
        Checks if 'configure' exists, if not, return 'autogen.sh' as a fallback
        '''
        configure_path = os.path.abspath(os.path.join(self.source,
                                                      "configure"))
        autogen_path = os.path.abspath(os.path.join(self.source,
                                                "autogen.sh"))
        if os.path.exists(configure_path):
            return configure_path
        elif os.path.exists(autogen_path):
            return autogen_path
        else:
            raise GnuSourceBuildInvalidSource('configure script does not exist')


    def get_available_configure_options(self):
        '''
        Return the list of available options of a GNU like configure script

        This will run the "configure" script at the source directory

        @returns: list of options accepted by configure script
        '''
        help_raw = utils.system_output('%s --help' % self.get_configure_path(),
                                       ignore_status=True)
        help_output = help_raw.split("\n")
        option_list = []
        for line in help_output:
            cleaned_line = line.lstrip()
            if cleaned_line.startswith("--"):
                option = cleaned_line.split()[0]
                option = option.split("=")[0]
                option_list.append(option)

        return option_list


    def enable_debug_symbols(self):
        '''
        Enables option that leaves debug symbols on compiled software

        This makes debugging a lot easier.
        '''
        enable_debug_option = "--disable-strip"
        if enable_debug_option in self.get_available_configure_options():
            self.configure_options.append(enable_debug_option)
            logging.debug('Enabling debug symbols with option: %s' %
                          enable_debug_option)


    def get_configure_command(self):
        '''
        Formats configure script with all options set

        @returns: string with all configure options, including prefix
        '''
        prefix_option = "--prefix=%s" % self.prefix
        options = self.configure_options
        options.append(prefix_option)
        return "%s %s" % (self.get_configure_path(),
                          " ".join(options))


    def configure(self):
        '''
        Runs the "configure" script passing apropriate command line options
        '''
        configure_command = self.get_configure_command()
        logging.info('Running configure on build dir')
        os.chdir(self.build_dir)
        utils.system(configure_command)


    def make_parallel(self):
        '''
        Runs "make" using the correct number of parallel jobs
        '''
        parallel_make_jobs = utils.count_cpus()
        make_command = "make -j %s" % parallel_make_jobs
        logging.info("Running parallel make on build dir")
        os.chdir(self.build_dir)
        utils.system(make_command)


    def make_non_parallel(self):
        '''
        Runs "make", using a single job
        '''
        os.chdir(self.build_dir)
        utils.system("make")


    def make_clean(self):
        '''
        Runs "make clean"
        '''
        os.chdir(self.build_dir)
        utils.system("make clean")


    def make(self, failure_feedback=True):
        '''
        Runs a parallel make, falling back to a single job in failure

        @param failure_feedback: return information on build failure by raising
                                 the appropriate exceptions
        @raise: SourceBuildParallelFailed if parallel build fails, or
                SourceBuildFailed if single job build fails
        '''
        try:
            self.make_parallel()
        except error.CmdError:
            try:
                self.make_clean()
                self.make_non_parallel()
            except error.CmdError:
                if failure_feedback:
                    raise SourceBuildFailed
            if failure_feedback:
                raise SourceBuildParallelFailed


    def make_install(self):
        '''
        Runs "make install"
        '''
        os.chdir(self.build_dir)
        utils.system("make install")


    install = make_install


    def execute(self):
        '''
        Runs appropriate steps for *building* this source code tree
        '''
        if self.install_debug_info:
            self.enable_debug_symbols()
        self.configure()
        self.make()


class LinuxKernelBuildHelper(object):
    '''
    Handles Building Linux Kernel.
    '''
    def __init__(self, params, prefix, source):
        '''
        @type params: dict
        @param params: dictionary containing the test parameters
        @type source: string
        @param source: source directory or tarball
        @type prefix: string
        @param prefix: installation prefix
        '''
        self.params = params
        self.prefix = prefix
        self.source = source
        self._parse_params()


    def _parse_params(self):
        '''
        Parses the params items for entries related to guest kernel
        '''
        configure_opt_key = '%s_config' % self.prefix
        self.config = self.params.get(configure_opt_key, '')

        build_image_key = '%s_build_image' % self.prefix
        self.build_image = self.params.get(build_image_key,
                                           'arch/x86/boot/bzImage')

        build_target_key = '%s_build_target' % self.prefix
        self.build_target = self.params.get(build_target_key, 'bzImage')

        kernel_path_key = '%s_kernel_path' % self.prefix
        default_kernel_path = os.path.join('/var/tmp/virt_test/images',
                                           self.build_target)
        self.kernel_path = self.params.get(kernel_path_key,
                                           default_kernel_path)

        logging.info('Parsing Linux kernel build parameters for %s',
                     self.prefix)


    def make_guest_kernel(self):
        '''
        Runs "make", using a single job
        '''
        os.chdir(self.source)
        logging.info("Building guest kernel")
        logging.debug("Kernel config is %s" % self.config)
        utils.get_file(self.config, '.config')

        # FIXME currently no support for builddir
        # run old config
        utils.system('yes "" | make oldconfig > /dev/null')
        parallel_make_jobs = utils.count_cpus()
        make_command = "make -j %s %s" % (parallel_make_jobs, self.build_target)
        logging.info("Running parallel make on src dir")
        utils.system(make_command)


    def make_clean(self):
        '''
        Runs "make clean"
        '''
        os.chdir(self.source)
        utils.system("make clean")


    def make(self, failure_feedback=True):
        '''
        Runs a parallel make

        @param failure_feedback: return information on build failure by raising
                                 the appropriate exceptions
        @raise: SourceBuildParallelFailed if parallel build fails, or
        '''
        try:
            self.make_clean()
            self.make_guest_kernel()
        except error.CmdError:
            if failure_feedback:
                raise SourceBuildParallelFailed


    def cp_linux_kernel(self):
        '''
        Copying Linux kernel to target path
        '''
        os.chdir(self.source)
        utils.force_copy(self.build_image, self.kernel_path)


    install = cp_linux_kernel


    def execute(self):
        '''
        Runs appropriate steps for *building* this source code tree
        '''
        self.make()


class GnuSourceBuildParamHelper(GnuSourceBuildHelper):
    '''
    Helps to deal with gnu_autotools build helper in cartersian config files

    This class attempts to make it simple to build source coude, by using a
    naming standard that follows this basic syntax:

    [<git_repo>|<local_src>]_<name>_<option> = value

    To pass extra options to the configure script, while building foo from a
    git repo, set the following variable:

    git_repo_foo_configure_options = --enable-feature
    '''
    def __init__(self, params, name, destination_dir, install_prefix):
        '''
        Instantiates a new GnuSourceBuildParamHelper
        '''
        self.params = params
        self.name = name
        self.destination_dir = destination_dir
        self.install_prefix = install_prefix
        self._parse_params()


    def _parse_params(self):
        '''
        Parses the params items for entries related to source directory

        This method currently does everything that the parent class __init__()
        method does, that is, sets all instance variables needed by other
        methods. That means it's not strictly necessary to call parent's
        __init__().
        '''
        logging.debug('Parsing gnu_autotools build parameters for %s' %
                      self.name)

        configure_opt_key = '%s_configure_options' % self.name
        configure_options = self.params.get(configure_opt_key, '').split()
        logging.debug('Configure options for %s: %s' % (self.name,
                                                        configure_options))

        self.source = self.destination_dir
        self.build_dir = self.destination_dir
        self.prefix = self.install_prefix
        self.configure_options = configure_options
        self.include_pkg_config_path()

        # Support the install_debug_info feature, that automatically
        # adds/keeps debug information on generated libraries/binaries
        install_debug_info_cfg = self.params.get("install_debug_info", "yes")
        self.install_debug_info = install_debug_info_cfg != "no"


def install_host_kernel(job, params):
    """
    Install a host kernel, given the appropriate params.

    @param job: Job object.
    @param params: Dict with host kernel install params.
    """
    install_type = params.get('host_kernel_install_type')

    if install_type == 'rpm':
        logging.info('Installing host kernel through rpm')

        rpm_url = params.get('host_kernel_rpm_url')
        k_basename = os.path.basename(rpm_url)
        dst = os.path.join("/tmp", k_basename)
        k = utils.get_file(rpm_url, dst)
        host_kernel = job.kernel(k)
        host_kernel.install(install_vmlinux=False)
        utils.write_keyval(job.resultdir,
                           {'software_version_kernel': k_basename})
        host_kernel.boot()

    elif install_type in ['koji', 'brew']:
        logging.info('Installing host kernel through koji/brew')

        koji_cmd = params.get('host_kernel_koji_cmd')
        koji_build = params.get('host_kernel_koji_build')
        koji_tag = params.get('host_kernel_koji_tag')

        k_deps = KojiPkgSpec(tag=koji_tag, build=koji_build, package='kernel',
                             subpackages=['kernel-devel', 'kernel-firmware'])
        k = KojiPkgSpec(tag=koji_tag, build=koji_build, package='kernel',
                        subpackages=['kernel'])

        c = KojiClient(koji_cmd)
        logging.info('Fetching kernel dependencies (-devel, -firmware)')
        c.get_pkgs(k_deps, job.tmpdir)
        logging.info('Installing kernel dependencies (-devel, -firmware) '
                     'through %s', install_type)
        k_deps_rpm_file_names = [os.path.join(job.tmpdir, rpm_file_name) for
                                 rpm_file_name in c.get_pkg_rpm_file_names(k_deps)]
        utils.run('rpm -U --force %s' % " ".join(k_deps_rpm_file_names))

        c.get_pkgs(k, job.tmpdir)
        k_rpm = os.path.join(job.tmpdir,
                             c.get_pkg_rpm_file_names(k)[0])
        host_kernel = job.kernel(k_rpm)
        host_kernel.install(install_vmlinux=False)
        utils.write_keyval(job.resultdir,
                           {'software_version_kernel':
                            " ".join(c.get_pkg_rpm_file_names(k_deps))})
        host_kernel.boot()

    elif install_type == 'git':
        logging.info('Chose to install host kernel through git, proceeding')

        repo = params.get('host_kernel_git_repo')
        repo_base = params.get('host_kernel_git_repo_base', None)
        branch = params.get('host_kernel_git_branch')
        commit = params.get('host_kernel_git_commit')
        patch_list = params.get('host_kernel_patch_list')
        if patch_list:
            patch_list = patch_list.split()
        kernel_config = params.get('host_kernel_config', None)

        repodir = os.path.join("/tmp", 'kernel_src')
        r = git.GitRepoHelper(uri=repo, branch=branch, destination_dir=repodir,
                              commit=commit, base_uri=repo_base)
        r.execute()
        host_kernel = job.kernel(r.destination_dir)
        if patch_list:
            host_kernel.patch(patch_list)
        if kernel_config:
            host_kernel.config(kernel_config)
        host_kernel.build()
        host_kernel.install()
        git_repo_version = '%s:%s:%s' % (r.uri, r.branch, r.get_top_commit())
        utils.write_keyval(job.resultdir,
                           {'software_version_kernel': git_repo_version})
        host_kernel.boot()

    else:
        logging.info('Chose %s, using the current kernel for the host',
                     install_type)
        k_version = utils.system_output('uname -r', ignore_status=True)
        utils.write_keyval(job.resultdir,
                           {'software_version_kernel': k_version})


def install_cpuflags_util_on_vm(test, vm, dst_dir, extra_flags=None):
    """
    Install stress to vm.

    @param vm: virtual machine.
    @param dst_dir: Installation path.
    @param extra_flags: Extraflags for gcc compiler.
    """
    if not extra_flags:
        extra_flags = ""

    cpuflags_src = os.path.join(test.virtdir, "deps", "test_cpu_flags")
    cpuflags_dst = os.path.join(dst_dir, "test_cpu_flags")
    session = vm.wait_for_login()
    session.cmd("rm -rf %s" %
                (cpuflags_dst))
    session.cmd("sync")
    vm.copy_files_to(cpuflags_src, dst_dir)
    session.cmd("sync")
    session.cmd("cd %s; make EXTRA_FLAGS='%s';" %
                    (cpuflags_dst, extra_flags))
    session.cmd("sync")
    session.close()


def qemu_has_option(option, qemu_path="/usr/libexec/qemu-kvm"):
    """
    Helper function for command line option wrappers

    @param option: Option need check.
    @param qemu_path: Path for qemu-kvm.
    """
    hlp = commands.getoutput("%s -help" % qemu_path)
    return bool(re.search(r"^-%s(\s|$)" % option, hlp, re.MULTILINE))


def bitlist_to_string(data):
    """
    Transform from bit list to ASCII string.

    @param data: Bit list to be transformed
    """
    result = []
    pos = 0
    c = 0
    while pos < len(data):
        c += data[pos] << (7 - (pos % 8))
        if (pos % 8) == 7:
            result.append(c)
            c = 0
        pos += 1
    return ''.join([ chr(c) for c in result ])


def string_to_bitlist(data):
    """
    Transform from ASCII string to bit list.

    @param data: String to be transformed
    """
    data = [ord(c) for c in data]
    result = []
    for ch in data:
        i = 7
        while i >= 0:
            if ch & (1 << i) != 0:
                result.append(1)
            else:
                result.append(0)
            i -= 1
    return result


def if_nametoindex(ifname):
    """
    Map an interface name into its corresponding index.
    Returns 0 on error, as 0 is not a valid index

    @param ifname: interface name
    """
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
    ifr = struct.pack("16si", ifname, 0)
    r = fcntl.ioctl(ctrl_sock, SIOCGIFINDEX, ifr)
    index = struct.unpack("16si", r)[1]
    ctrl_sock.close()
    return index


def vnet_hdr_probe(tapfd):
    """
    Check if the IFF_VNET_HDR is support by tun.

    @param tapfd: the file descriptor of /dev/net/tun
    """
    u = struct.pack("I", 0)
    try:
        r = fcntl.ioctl(tapfd, TUNGETFEATURES, u)
    except OverflowError:
        logging.debug("Fail to get tun features!")
        return False
    flags = struct.unpack("I", r)[0]
    if flags & IFF_VNET_HDR:
        return True
    else:
        return False


def open_tap(devname, ifname, vnet_hdr=True):
    """
    Open a tap device and returns its file descriptor which is used by
    fd=<fd> parameter of qemu-kvm.

    @param ifname: TAP interface name
    @param vnet_hdr: Whether enable the vnet header
    """
    try:
        tapfd = os.open(devname, os.O_RDWR)
    except OSError, e:
        raise TAPModuleError(devname, "open", e)
    flags = IFF_TAP | IFF_NO_PI
    if vnet_hdr and vnet_hdr_probe(tapfd):
        flags |= IFF_VNET_HDR

    ifr = struct.pack("16sh", ifname, flags)
    try:
        r = fcntl.ioctl(tapfd, TUNSETIFF, ifr)
    except IOError, details:
        raise TAPCreationError(ifname, details)
    ifname = struct.unpack("16sh", r)[0].strip("\x00")
    return tapfd


def is_virtual_network_dev(dev_name):
    """
    @param dev_name: Device name.

    @return: True if dev_name is in virtual/net dir, else false.
    """
    if dev_name in os.listdir("/sys/devices/virtual/net/"):
        return True
    else:
        return False


def find_dnsmasq_listen_address():
    """
    Search all dnsmasq listen addresses.

    @param bridge_name: Name of bridge.
    @param bridge_ip: Bridge ip.
    @return: List of ip where dnsmasq is listening.
    """
    cmd = "ps -Af | grep dnsmasq"
    result = utils.run(cmd).stdout
    return re.findall("--listen-address (.+?) ", result, re.MULTILINE)


def local_runner(cmd, timeout=None):
    return utils.run(cmd, verbose=False, timeout=timeout).stdout


def local_runner_status(cmd, timeout=None):
    return utils.run(cmd, verbose=False, timeout=timeout).exit_status


def get_net_if(runner=None):
    """
    @param output: Output form ip link command.
    @return: List of network interfaces.
    """
    if runner is None:
        runner = local_runner
    cmd = "ip link"
    result = runner(cmd)
    return re.findall("^\d+: (\S+?)[@:].*$", result, re.MULTILINE)


def get_net_if_addrs(if_name, runner=None):
    """
    Get network device ip addresses. ioctl not used because it's not
    compatible with ipv6 address.

    @param if_name: Name of interface.
    @return: List ip addresses of network interface.
    """
    if runner is None:
        runner = local_runner
    cmd = "ip addr show %s" % (if_name)
    result = runner(cmd)
    return {"ipv4": re.findall("inet (.+?)/..?", result, re.MULTILINE),
            "ipv6": re.findall("inet6 (.+?)/...?", result, re.MULTILINE),
            "mac": re.findall("link/ether (.+?) ", result, re.MULTILINE)}


def get_net_if_and_addrs(runner=None):
    """
    @return: Dict of interfaces and their addresses {"ifname": addrs}.
    """
    ret = {}
    ifs = get_net_if(runner)
    for iface in ifs:
        ret[iface] = get_net_if_addrs(iface, runner)
    return ret


def set_net_if_ip(if_name, ip_addr, runner=None):
    """
    Get network device ip addresses. ioctl not used because there is
    incompatibility with ipv6.

    @param if_name: Name of interface.
    @param ip_addr: Interface ip addr in format "ip_address/mask".
    @raise: IfChangeAddrError.
    """
    if runner is None:
        runner = local_runner
    cmd = "ip addr add %s dev %s" % (ip_addr, if_name)
    try:
        runner(cmd)
    except error.CmdError, e:
        raise IfChangeAddrError(if_name, ip_addr, e)


def ipv6_from_mac_addr(mac_addr):
    """
    @return: Ipv6 address for communication in link range.
    """
    mp = mac_addr.split(":")
    mp[0] = ("%x") % (int(mp[0], 16) ^ 0x2)
    return "fe80::%s%s:%sff:fe%s:%s%s" % tuple(mp)


def check_add_dnsmasq_to_br(br_name, tmpdir):
    """
    Add dnsmasq for bridge. dnsmasq could be added only if bridge
    has assigned ip address.

    @param bridge_name: Name of bridge.
    @param bridge_ip: Bridge ip.
    @param tmpdir: Tmp dir for save pid file and ip range file.
    @return: When new dnsmasq is started name of pidfile  otherwise return
             None because system dnsmasq is already started on bridge.
    """
    br_ips = get_net_if_addrs(br_name)["ipv4"]
    if not br_ips:
        raise BRIpError(br_name)
    dnsmasq_listen = find_dnsmasq_listen_address()
    dhcp_ip_start = br_ips[0].split(".")
    dhcp_ip_start[3] = "128"
    dhcp_ip_start = ".".join(dhcp_ip_start)

    dhcp_ip_end = br_ips[0].split(".")
    dhcp_ip_end[3] = "254"
    dhcp_ip_end = ".".join(dhcp_ip_end)

    pidfile = ("%s-dnsmasq.pid") % (br_ips[0])
    leases = ("%s.leases") % (br_ips[0])

    if not (set(br_ips) & set(dnsmasq_listen)):
        logging.debug("There is no dnsmasq on br %s."
                      "Starting new one." % (br_name))
        utils.run("/usr/sbin/dnsmasq --strict-order --bind-interfaces"
                  " --pid-file=%s --conf-file= --except-interface lo"
                  " --listen-address %s --dhcp-range %s,%s --dhcp-leasefile=%s"
                  " --dhcp-lease-max=127 --dhcp-no-override" %
                  (os.path.join(tmpdir, pidfile), br_ips[0], dhcp_ip_start,
                   dhcp_ip_end, (os.path.join(tmpdir, leases))))
        return pidfile
    return None


@__init_openvswitch
def find_bridge_manager(br_name, ovs=None):
    """
    Finds bridge which contain interface iface_name.

    @param br_name: Name of interface.
    @return: (br_manager) which contain bridge or None.
    """
    if ovs is None:
        ovs = __ovs
    # find ifname in standard linux bridge.
    if br_name in __bridge.list_br():
        return __bridge
    elif not ovs is None and br_name in ovs.list_br():
        return ovs
    else:
        return None


@__init_openvswitch
def find_current_bridge(iface_name, ovs=None):
    """
    Finds bridge which contains interface iface_name.

    @param iface_name: Name of interface.
    @return: (br_manager, Bridge) which contain iface_name or None.
    """
    if ovs is None:
        ovs = __ovs
    # find ifname in standard linux bridge.
    master = __bridge
    bridge = master.port_to_br(iface_name)
    if bridge is None:
        master = ovs
        bridge = master.port_to_br(iface_name)

    if bridge is None:
        master = None

    return (master, bridge)


@__init_openvswitch
def change_iface_bridge(ifname, new_bridge, ovs=None):
    """
    Change bridge on which interface was added.

    @param ifname: Iface name or Iface struct.
    @param new_bridge: Name of new bridge.
    """
    if ovs is None:
        ovs = __ovs
    br_manager_new = find_bridge_manager(new_bridge, ovs)
    if br_manager_new is None:
        raise BRNotExistError(new_bridge, "")

    if type(ifname) is str:
        (br_manager_old, br_old) = find_current_bridge(ifname, ovs)
        if not br_manager_old is None:
            br_manager_old.del_port(br_old, ifname)
        br_manager_new.add_port(new_bridge, ifname)
    elif issubclass(type(ifname), VirtIface):
        br_manager_old = find_bridge_manager(ifname.netdst, ovs)
        if not br_manager_old is None:
            br_manager_old.del_port(ifname.netdst, ifname.ifname)
        br_manager_new.add_port(new_bridge, ifname.ifname)
        ifname.netdst = new_bridge
    else:
        raise error.AutotestError("Network interface %s is wrong type %s." %
                                  (ifname, new_bridge))


@__init_openvswitch
def add_to_bridge(ifname, brname, ovs=None):
    """
    Add a TAP device to bridge

    @param ifname: Name of TAP device
    @param brname: Name of the bridge
    @param ovs: OpenVSwitch object.
    """
    if ovs is None:
        ovs = __ovs

    _ifname = None
    if type(ifname) is str:
        _ifname = ifname
    elif issubclass(type(ifname), VirtIface):
        _ifname = ifname.ifname

    if brname in __bridge.list_br():
        #Try add port to standard bridge or openvswitch in compatible mode.
        __bridge.add_port(brname, _ifname)
        return

    if ovs is None:
        raise BRAddIfError(ifname, brname, "There is no bridge in system.")
    #Try add port to OpenVSwitch bridge.
    if brname in ovs.list_br():
        ovs.add_port(brname, ifname)


@__init_openvswitch
def del_from_bridge(ifname, brname, ovs=None):
    """
    Del a TAP device to bridge

    @param ifname: Name of TAP device
    @param brname: Name of the bridge
    @param ovs: OpenVSwitch object.
    """
    if ovs is None:
        ovs = __ovs

    _ifname = None
    if type(ifname) is str:
        _ifname = ifname
    elif issubclass(type(ifname), VirtIface):
        _ifname = ifname.ifname

    if ovs is None:
        raise BRDelIfError(ifname, brname, "There is no bridge in system.")

    if brname in __bridge.list_br():
        #Try add port to standard bridge or openvswitch in compatible mode.
        __bridge.del_port(brname, _ifname)
        return

    #Try add port to OpenVSwitch bridge.
    if brname in ovs.list_br():
        ovs.del_port(brname, _ifname)


def bring_up_ifname(ifname):
    """
    Bring up an interface

    @param ifname: Name of the interface
    """
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
    ifr = struct.pack("16sh", ifname, IFF_UP)
    try:
        fcntl.ioctl(ctrl_sock, SIOCSIFFLAGS, ifr)
    except IOError:
        raise TAPBringUpError(ifname)
    ctrl_sock.close()


def bring_down_ifname(ifname):
    """
    Bring up an interface

    @param ifname: Name of the interface
    """
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
    ifr = struct.pack("16sh", ifname, 0)
    try:
        fcntl.ioctl(ctrl_sock, SIOCSIFFLAGS, ifr)
    except IOError:
        raise TAPBringUpError(ifname)
    ctrl_sock.close()


def if_set_macaddress(ifname, mac):
    """
    Set the mac address for an interface

    @param ifname: Name of the interface
    @mac: Mac address
    """
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)

    ifr = struct.pack("256s", ifname)
    try:
        mac_dev = fcntl.ioctl(ctrl_sock, SIOCGIFHWADDR, ifr)[18:24]
        mac_dev = ":".join(["%02x" % ord(m) for m in mac_dev])
    except IOError, e:
        raise HwAddrGetError(ifname)

    if mac_dev.lower() == mac.lower():
        return

    ifr = struct.pack("16sH14s", ifname, 1,
                      "".join([chr(int(m, 16)) for m in mac.split(":")]))
    try:
        fcntl.ioctl(ctrl_sock, SIOCSIFHWADDR, ifr)
    except IOError, e:
        logging.info(e)
        raise HwAddrSetError(ifname, mac)
    ctrl_sock.close()


def get_module_params(sys_path, module_name):
    """
    Get the kvm module params
    @param sys_path: sysfs path for modules info
    @param module_name: module to check
    """
    dir_params = os.path.join(sys_path, "module", module_name, "parameters")
    module_params = {}
    if os.path.isdir(dir_params):
        for filename in os.listdir(dir_params):
            full_dir = os.path.join(dir_params, filename)
            tmp = open(full_dir, 'r').read().strip()
            module_params[full_dir] = tmp
    else:
        return None
    return module_params


def download_file(url, destination, sha1, interactive=False):
    """
    Verifies if file that can be find on url is on destination with right hash.

    This function will verify the SHA1 hash of the file. If the file
    appears to be missing or corrupted, let the user know.

    @param url: URL where the file can be found.
    @param destination: Directory in local disk where we'd like the file to be.
    @param iso_sha1: SHA1 hash for the file.
    @return: True, if file had to be downloaded
             False, if file didn't have to be downloaded
    """
    file_ok = False
    had_to_download = False
    if not os.path.isdir(destination):
        os.makedirs(destination)
    path = os.path.join(destination, os.path.basename(url))
    if not os.path.isfile(path):
        logging.warning("File %s not found", path)
        logging.warning("Expected SHA1 sum: %s", sha1)
        if interactive:
            answer = utils.ask("Would you like to download it from %s?" % url)
        else:
            answer = 'y'
        if answer == 'y':
            utils.interactive_download(url, path)
            had_to_download = True
        else:
            logging.warning("Missing file %s", path)
            return had_to_download
    else:
        logging.info("Found %s", path)
        logging.info("Expected SHA1 sum: %s", sha1)
        if interactive:
            answer = utils.ask("Would you like to check %s? It might take a"
                               "while" % path)
        else:
            answer = 'y'
        if answer == 'y':
            actual_sha1 = utils.hash_file(path, method='sha1')
            if actual_sha1 != sha1:
                logging.error("Actual SHA1 sum: %s", actual_sha1)
            else:
                logging.info("SHA1 sum check OK")
        else:
            logging.info("File %s present, but chose to not verify it",
                         path)
            return had_to_download

    if file_ok:
        logging.info("%s present, with proper checksum", path)
    return had_to_download


def create_config_files(test_dir, shared_dir, interactive, step=None):
    if step is None:
        step = 0
    logging.info("")
    step += 1
    logging.info("%d - Creating config files from samples (copy the default "
                 "config samples to actual config files)", step)
    config_file_list = glob.glob(os.path.join(test_dir, "cfg", "*.cfg.sample"))
    config_file_list_shared = glob.glob(os.path.join(shared_dir,
                                                     "*.cfg.sample"))

    # Handle overrides of cfg files. Let's say a test provides its own
    # subtest.cfg.sample, this file takes precedence over the shared
    # subtest.cfg.sample. So, yank this file from the cfg file list.

    idx = 0
    for cf in config_file_list_shared:
        basename = os.path.basename(cf)
        target = os.path.join(test_dir, "cfg", basename)
        if target in config_file_list:
            config_file_list_shared.pop(idx)
        idx += 1

    config_file_list += config_file_list_shared

    for config_file in config_file_list:
        src_file = config_file
        dst_file = os.path.join(test_dir, "cfg", os.path.basename(config_file))
        dst_file = dst_file.rstrip(".sample")
        if not os.path.isfile(dst_file):
            logging.debug("Creating config file %s from sample", dst_file)
            shutil.copyfile(src_file, dst_file)
        else:
            diff_result = utils.run("diff -Naur %s %s" % (dst_file, src_file),
                                    ignore_status=True, verbose=False)
            if diff_result.exit_status != 0:
                logging.debug("%s result:\n %s" %
                              (diff_result.command, diff_result.stdout))
                if interactive:
                    answer = utils.ask("Config file  %s differs from %s."
                                       "Overwrite?" % (dst_file,src_file))
                else:
                    answer = "n"

                if answer == "y":
                    logging.debug("Restoring config file %s from sample" %
                                  dst_file)
                    shutil.copyfile(src_file, dst_file)
                else:
                    logging.debug("Preserving existing %s file" % dst_file)
            else:
                logging.debug("Config file %s exists, not touching" % dst_file)


def virt_test_assistant(test_name, test_dir, base_dir, default_userspace_paths,
                        check_modules, online_docs_url, restore_image=False,
                        interactive=True):
    """
    Common virt test assistant module.

    @param test_name: Test name, such as "kvm".
    @param test_dir: Path with the test directory.
    @param base_dir: Base directory used to hold images and isos.
    @param default_userspace_paths: Important programs for a successful test
            execution.
    @param check_modules: Whether we want to verify if a given list of modules
            is loaded in the system.
    @param online_docs_url: URL to an online documentation system, such as a
            wiki page.
    @param restore_image: Whether to restore the image from the pristine.
    @param interactive: Whether to ask for confirmation.

    @raise error.CmdError: If JeOS image failed to uncompress
    @raise ValueError: If 7za was not found
    """
    if interactive:
        logging_manager.configure_logging(VirtLoggingConfig(), verbose=True)
    logging.info("%s test config helper", test_name)
    step = 0
    shared_dir = os.path.abspath(os.path.join(sys.modules[__name__].__file__,
                                              "..", ".."))
    shared_dir = os.path.join(shared_dir, "shared", "cfg")
    logging.info("")
    step += 1
    logging.info("%d - Verifying directories (check if the directory structure "
                 "expected by the default test config is there)", step)
    sub_dir_list = ["images", "isos", "steps_data"]
    for sub_dir in sub_dir_list:
        sub_dir_path = os.path.join(base_dir, sub_dir)
        if not os.path.isdir(sub_dir_path):
            logging.debug("Creating %s", sub_dir_path)
            os.makedirs(sub_dir_path)
        else:
            logging.debug("Dir %s exists, not creating" %
                          sub_dir_path)

    create_config_files(test_dir, shared_dir, interactive, step)

    logging.info("")
    step += 1
    logging.info("%s - Verifying (and possibly downloading) guest image", step)

    # If this is not present, we better tell the user straight away
    try:
        os_dep.command("7za")
    except ValueError:
        raise ValueError("Command 7za not installed. Please install p7zip "
                         "(Red Hat based) or the equivalent for your host")

    guest_tarball = "jeos-17-64.qcow2.7z"
    url = os.path.join("http://lmr.fedorapeople.org/jeos/", guest_tarball)
    tarball_sha1 = "321fc6bacb507a0d30ee6ca7c474800d533cc1a7"
    destination = os.path.join(base_dir, 'images')

    if (interactive and not
        os.path.isfile(os.path.join(destination, guest_tarball))):
        answer = utils.ask("Minimal basic guest image (JeOS) not present. "
                           "Do you want to download it (~ 120MB)?")
    else:
        answer = "y"

    if answer == "y":
        had_to_download = download_file(url, destination, tarball_sha1)
        restore_image = (restore_image or had_to_download)
        tarball_path = os.path.join(destination, guest_tarball)
        if os.path.isfile(tarball_path) and restore_image:
            os.chdir(destination)
            utils.run("7za -y e %s" % tarball_path)

    if default_userspace_paths:
        logging.info("")
        step += 1
        logging.info("%d - Checking if the appropriate userspace programs are "
                     "installed", step)
        for path in default_userspace_paths:
            if not os.path.isfile(path):
                logging.warning("No %s found. You might need to install %s.",
                                path, os.path.basename(path))
            else:
                logging.debug("%s present", path)
        logging.info("If you wish to change any userspace program path, "
                     "you will have to modify tests.cfg")

    if check_modules:
        logging.info("")
        step += 1
        logging.info("%d - Checking for modules %s", step,
                     ", ".join(check_modules))
        for module in check_modules:
            if not utils.module_is_loaded(module):
                logging.warning("Module %s is not loaded. You might want to "
                                "load it", module)
            else:
                logging.debug("Module %s loaded", module)

    if online_docs_url:
        logging.info("")
        step += 1
        logging.info("%d - Verify needed packages to get started", step)
        logging.info("Please take a look at the online documentation: %s",
                     online_docs_url)
        logging.info("")


def create_x509_dir(path, cacert_subj, server_subj, passphrase,
                    secure=False, bits=1024, days=1095):
    """
    Creates directory with freshly generated:
    ca-cart.pem, ca-key.pem, server-cert.pem, server-key.pem,

    @param path: defines path to directory which will be created
    @param cacert_subj: ca-cert.pem subject
    @param server_key.csr subject
    @param passphrase - passphrase to ca-key.pem
    @param secure = False - defines if the server-key.pem will use a passphrase
    @param bits = 1024: bit length of keys
    @param days = 1095: cert expiration

    @raise ValueError: openssl not found or rc != 0
    @raise OSError: if os.makedirs() fails
    """

    ssl_cmd = os_dep.command("openssl")
    path = path + os.path.sep # Add separator to the path
    shutil.rmtree(path, ignore_errors = True)
    os.makedirs(path)

    server_key = "server-key.pem.secure"
    if secure:
        server_key = "server-key.pem"

    cmd_set = [
    ('%s genrsa -des3 -passout pass:%s -out %sca-key.pem %d' %
     (ssl_cmd, passphrase, path, bits)),
    ('%s req -new -x509 -days %d -key %sca-key.pem -passin pass:%s -out '
     '%sca-cert.pem -subj "%s"' %
     (ssl_cmd, days, path, passphrase, path, cacert_subj)),
    ('%s genrsa -out %s %d' % (ssl_cmd, path + server_key, bits)),
    ('%s req -new -key %s -out %s/server-key.csr -subj "%s"' %
     (ssl_cmd, path + server_key, path, server_subj)),
    ('%s x509 -req -passin pass:%s -days %d -in %sserver-key.csr -CA '
     '%sca-cert.pem -CAkey %sca-key.pem -set_serial 01 -out %sserver-cert.pem' %
     (ssl_cmd, passphrase, days, path, path, path, path))
     ]

    if not secure:
        cmd_set.append('%s rsa -in %s -out %sserver-key.pem' %
                       (ssl_cmd, path + server_key, path))

    for cmd in cmd_set:
        utils.run(cmd)
        logging.info(cmd)


class NumaNode(object):
    """
    Numa node to control processes and shared memory.
    """
    def __init__(self, i=-1):
        self.num = self.get_node_num()
        if i < 0:
            self.cpus = self.get_node_cpus(int(self.num) + i).split()
        else:
            self.cpus = self.get_node_cpus(i - 1).split()
        self.dict = {}
        for i in self.cpus:
            self.dict[i] = "free"


    def get_node_num(self):
        """
        Get the number of nodes of current host.
        """
        cmd = utils.run("numactl --hardware")
        return re.findall("available: (\d+) nodes", cmd.stdout)[0]


    def get_node_cpus(self, i):
        """
        Get cpus of a specific node

        @param i: Index of the CPU inside the node.
        """
        cmd = utils.run("numactl --hardware")
        cpus = re.findall("node %s cpus: (.*)" % i, cmd.stdout)
        if cpus:
            cpus = cpus[0]
        else:
            break_flag = False
            cpulist_path = "/sys/devices/system/node/node%s/cpulist" % i
            try:
                cpulist_file = open(cpulist_path, 'r')
                cpus = cpulist_file.read()
                cpulist_file.close()
            except IOError:
                logging.warn("Can not find the cpu list information from both"
                             "numactl and sysfs. Please check your system.")
                break_flag = True
            if not break_flag:
                # Try to expand the numbers with '-' to a string of numbers
                # separated by blank. There number of '-' in the list depends
                # on the physical architecture of the hardware.
                try:
                    convert_list = re.findall("\d+-\d+", cpus)
                    for cstr in convert_list:
                        _ = " "
                        start = min(int(cstr.split("-")[0]),
                                    int(cstr.split("-")[1]))
                        end = max(int(cstr.split("-")[0]),
                                  int(cstr.split("-")[1]))
                        for n in range(start, end+1, 1):
                            _ += "%s " % str(n)
                        cpus = re.sub(cstr, _, cpus)
                except (IndexError, ValueError):
                    logging.warn("The format of cpu list is not the same as"
                                 " expected.")
                    break_flag = False
            if break_flag:
                cpus = ""

        return cpus


    def free_cpu(self, i):
        """
        Release pin of one node.

        @param i: Index of the node.
        """
        self.dict[i] = "free"


    def _flush_pin(self):
        """
        Flush pin dict, remove the record of exited process.
        """
        cmd = utils.run("ps -eLf | awk '{print $4}'")
        all_pids = cmd.stdout
        for i in self.cpus:
            if self.dict[i] != "free" and self.dict[i] not in all_pids:
                self.free_cpu(i)


    @error.context_aware
    def pin_cpu(self, process):
        """
        Pin one process to a single cpu.

        @param process: Process ID.
        """
        self._flush_pin()
        error.context("Pinning process %s to the CPU" % process)
        for i in self.cpus:
            if self.dict[i] == "free":
                self.dict[i] = str(process)
                cmd = "taskset -p %s %s" % (hex(2 ** int(i)), process)
                logging.debug("NumaNode (%s): " % i + cmd)
                utils.run(cmd)
                return i


    def show(self):
        """
        Display the record dict in a convenient way.
        """
        logging.info("Numa Node record dict:")
        for i in self.cpus:
            logging.info("    %s: %s" % (i, self.dict[i]))


def generate_mac_address_simple():
    r = random.SystemRandom()
    mac = "9a:%02x:%02x:%02x:%02x:%02x" % (r.randint(0x00, 0xff),
                                           r.randint(0x00, 0xff),
                                           r.randint(0x00, 0xff),
                                           r.randint(0x00, 0xff),
                                           r.randint(0x00, 0xff))
    return mac


def get_ip_address_by_interface(ifname):
    """
    returns ip address by interface
    @param ifname - interface name
    @raise NetError - When failed to fetch IP address (ioctl raised IOError.).

    Retrieves interface address from socket fd trough ioctl call
    and transforms it into string from 32-bit packed binary
    by using socket.inet_ntoa().

    """
    SIOCGIFADDR = 0x8915 # Get interface address <bits/ioctls.h>
    mysocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        return socket.inet_ntoa(fcntl.ioctl(
                    mysocket.fileno(),
                    SIOCGIFADDR,
                    struct.pack('256s', ifname[:15]) # ifname to binary IFNAMSIZ == 16
                )[20:24])
    except IOError:
        raise NetError("Error while retrieving IP address from interface %s." % ifname)


def standard_value(value_str, standard_unit="M", base="1024"):
    """
    return the value based on the standard unit given

    @param value_str: a string include the data and unit
    @param standard_unit: the unit of the result based
    @param base: the base between two adjacent unit. Normally could be 1024
                 or 1000
    """
    def _get_unit_index(unit_list, unit_value):
        for i in unit_list:
            stand_unit = re.findall("[\s\d](%s)" % i, str(unit_value), re.I)
            if stand_unit:
                return unit_list.index(stand_unit[0].upper())
        return -1

    unit_list = ['B', 'K', 'M', 'G', 'T']
    try:
        data = float(re.findall("[\d\.]+",value_str)[0])
    except IndexError:
        logging.warn("The format is not right. Please check %s"
                     " has both data and unit." % value_str)
        return ""

    unit_index = _get_unit_index(unit_list, value_str)
    stand_index = _get_unit_index(unit_list, " %s" % standard_unit)

    if unit_index < 0 or stand_index < 0:
        logging.warn("Unknown unit. Please check your value '%s' and standard"
                     " unit '%s'" % (value_str, standard_unit))
        return ""

    if unit_index > stand_index:
        multiple = float(base)
    else:
        multiple = float(1) / float(base)

    for i in range(abs(unit_index - stand_index)):
        data *= multiple

    return str(data)

def check_if_vm_vcpu_match(vcpu_desire, vm):
    """
    This checks whether the VM vCPU quantity matches
    the value desired.
    """
    vcpu_actual = vm.get_cpu_count()
    if vcpu_desire != vcpu_actual:
        logging.debug("CPU quantity mismatched !!! guest said it got %s "
          "but we assigned %s" % (vcpu_actual, vcpu_desire))
        return False
    logging.info("CPU quantity matched: %s" % vcpu_actual)
    return True


def get_host_ip_address(params):
    """
    returns ip address of host specified in host_ip_addr parameter If provided
    otherwise ip address on interface specified in netdst paramter is returned
    @param params
    """
    host_ip = params.get('host_ip_addr', None)
    if not host_ip:
        host_ip = get_ip_address_by_interface(params.get('netdst'))
        logging.warning("No IP address of host was provided, using IP address"
                        " on %s interface", str(params.get('netdst')))
    return host_ip


class ForAll(list):
    def __getattr__(self, name):
        def wrapper(*args, **kargs):
            return map(lambda o: o.__getattribute__(name)(*args, **kargs), self)
        return wrapper


class ForAllP(list):
    """
    Parallel version of ForAll
    """
    def __getattr__(self, name):
        def wrapper(*args, **kargs):
            threads = []
            for o in self:
                threads.append(utils.InterruptedThread(o.__getattribute__(name),
                                                       args=args, kwargs=kargs))
            for t in threads:
                t.start()
            return map(lambda t: t.join(), threads)
        return wrapper


class ForAllPSE(list):
    """
    Parallel version of and suppress exception.
    """
    def __getattr__(self, name):
        def wrapper(*args, **kargs):
            threads = []
            for o in self:
                threads.append(utils.InterruptedThread(o.__getattribute__(name),
                                                       args=args, kwargs=kargs))
            for t in threads:
                t.start()

            result = []
            for t in threads:
                ret = {}
                try:
                    ret["return"] = t.join()
                except Exception:
                    ret["exception"] = sys.exc_info()
                    ret["args"] = args
                    ret["kargs"] = kargs
                result.append(ret)
            return result
        return wrapper


def get_pid_path(program_name, pid_files_dir=None):
    if not pid_files_dir:
        base_dir = os.path.dirname(__file__)
        pid_path = os.path.abspath(os.path.join(base_dir, "..", "..",
                                                "%s.pid" % program_name))
    else:
        pid_path = os.path.join(pid_files_dir, "%s.pid" % program_name)

    return pid_path


def write_pid(program_name, pid_files_dir=None):
    """
    Try to drop <program_name>.pid in the main autotest directory.

    Args:
      program_name: prefix for file name
    """
    pidfile = open(get_pid_path(program_name, pid_files_dir), "w")
    try:
        pidfile.write("%s\n" % os.getpid())
    finally:
        pidfile.close()


def delete_pid_file_if_exists(program_name, pid_files_dir=None):
    """
    Tries to remove <program_name>.pid from the main autotest directory.
    """
    pidfile_path = get_pid_path(program_name, pid_files_dir)

    try:
        os.remove(pidfile_path)
    except OSError:
        if not os.path.exists(pidfile_path):
            return
        raise


def get_pid_from_file(program_name, pid_files_dir=None):
    """
    Reads the pid from <program_name>.pid in the autotest directory.

    @param program_name the name of the program
    @return the pid if the file exists, None otherwise.
    """
    pidfile_path = get_pid_path(program_name, pid_files_dir)
    if not os.path.exists(pidfile_path):
        return None

    pidfile = open(get_pid_path(program_name, pid_files_dir), 'r')

    try:
        try:
            pid = int(pidfile.readline())
        except IOError:
            if not os.path.exists(pidfile_path):
                return None
            raise
    finally:
        pidfile.close()

    return pid


def program_is_alive(program_name, pid_files_dir=None):
    """
    Checks if the process is alive and not in Zombie state.

    @param program_name the name of the program
    @return True if still alive, False otherwise
    """
    pid = get_pid_from_file(program_name, pid_files_dir)
    if pid is None:
        return False
    return utils.pid_is_alive(pid)


def signal_program(program_name, sig=signal.SIGTERM, pid_files_dir=None):
    """
    Sends a signal to the process listed in <program_name>.pid

    @param program_name the name of the program
    @param sig signal to send
    """
    pid = get_pid_from_file(program_name, pid_files_dir)
    if pid:
        utils.signal_pid(pid, sig)
