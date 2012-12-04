"""
Virtualization test utility functions.

@copyright: 2008-2009 Red Hat Inc.
"""

import time, string, random, socket, os, signal, re, logging, commands, cPickle
import fcntl, shelve, sys, UserDict, inspect, tarfile
import struct, shutil, platform
from autotest.client import utils, os_dep
from autotest.client.shared import error, logging_config
from autotest.client.shared import git
import openvswitch, utils_koji

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
                logging.warn("Exception thrown while loading env")
                logging.warn(e)
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
        # First, let's close the log files opened in old directories
        close_log_file(filename)
        # Then, let's open the new file
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


def close_log_file(filename):
    global _open_log_files, _log_file_dir
    remove = []
    for k in _open_log_files:
        if os.path.basename(k) == filename:
            f = _open_log_files[k]
            f.close()
            remove.append(k)
    if remove:
        for key_to_remove in remove:
            _open_log_files.pop(key_to_remove)


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
    sr = ""
    chars = string.letters + string.digits + string.punctuation
    if not ignore_str:
        ignore_str = ""
    for i in ignore_str:
        chars = chars.replace(i, "")

    while length > 0:
        tmp = r.choice(chars)
        if convert_str and (tmp in convert_str):
            tmp = "\\%s" % tmp
        sr += tmp
        length -= 1
    return sr


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
    last_index = -1
    for i, d in enumerate(parser.get_dicts()):
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
    for param_dict in parser.get_dicts():
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
        param_dict["kvm_default"] = get_module_params(param_dict.get("sysfs_dir", "sys"), "kvm")

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
                job.profilers.add(profiler)
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
            'sse4.1'              :'sse4_1',
            'sse4.2'              :'sse4_2',
            'pclmulqdq'           :'pclmuldq',
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
        vendor = 'intel'
    elif 'svm' in cpu_flags:
        vendor = 'amd'
    else:
        vendor = 'unknown'

    if verbose:
        logging.debug("Detected CPU vendor as '%s'", vendor)
    return vendor


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

        k_deps = utils_koji.KojiPkgSpec(tag=koji_tag, build=koji_build,
                                        package='kernel',
                                subpackages=['kernel-devel', 'kernel-firmware'])
        k = utils_koji.KojiPkgSpec(tag=koji_tag, build=koji_build,
                                   package='kernel', subpackages=['kernel'])

        c = utils_koji.KojiClient(koji_cmd)
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


def install_disktest_on_vm(test, vm, src_dir, dst_dir):
    """
    Install stress to vm.

    @param vm: virtual machine.
    @param src_dir: Source path.
    @param dst_dir: Instaltation path.
    """
    disktest_src = src_dir
    disktest_dst = os.path.join(dst_dir, "disktest")
    session = vm.wait_for_login()
    session.cmd("rm -rf %s" % (disktest_dst))
    session.cmd("mkdir -p %s" % (disktest_dst))
    session.cmd("sync")
    vm.copy_files_to(disktest_src, disktest_dst)
    session.cmd("sync")
    session.cmd("cd %s; make;" %
                    (os.path.join(disktest_dst, "src")))
    session.cmd("sync")
    session.close()


def qemu_has_option(option, qemu_path="/usr/bin/qemu-kvm"):
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


def get_cpu_model():
    """
    Get cpu model from host cpuinfo
    """
    def _cpu_flags_sort(cpu_flags):
        """
        Update the cpu flags get from host to a certain order and format
        """
        flag_list = re.split("\s+", cpu_flags.strip())
        flag_list.sort()
        cpu_flags = " ".join(flag_list)
        return cpu_flags

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

    vendor_re = "vendor_id\s+:\s+(\w+)"
    cpu_flags_re = "flags\s+:\s+([\w\s]+)\n"

    cpu_types = {"AuthenticAMD": ["Opteron_G4", "Opteron_G3", "Opteron_G2",
                                 "Opteron_G1"],
                 "GenuineIntel": ["SandyBridge", "Westmere", "Nehalem",
                                  "Penryn", "Conroe"]}
    cpu_type_re = {"Opteron_G4":
                  "avx,xsave,aes,sse4.2|sse4_2,sse4.1|sse4_1,cx16,ssse3,sse4a",
                   "Opteron_G3": "cx16,sse4a",
                   "Opteron_G2": "cx16",
                   "Opteron_G1": "",
                   "SandyBridge":
                   "avx,xsave,aes,sse4_2|sse4.2,sse4.1|sse4_1,cx16,ssse3",
                   "Westmere": "aes,sse4.2|sse4_2,sse4.1|sse4_1,cx16,ssse3",
                   "Nehalem": "sse4.2|sse4_2,sse4.1|sse4_1,cx16,ssse3",
                   "Penryn": "sse4.1|sse4_1,cx16,ssse3",
                   "Conroe": "ssse3"}

    fd = open("/proc/cpuinfo")
    cpu_info = fd.read()
    fd.close()

    vendor = re.findall(vendor_re, cpu_info)[0]
    cpu_flags = re.findall(cpu_flags_re, cpu_info)

    cpu_model = ""
    if cpu_flags:
        cpu_flags = _cpu_flags_sort(cpu_flags[0])
        for cpu_type in cpu_types.get(vendor):
            pattern = _make_up_pattern(cpu_type_re.get(cpu_type))
            if re.findall(pattern, cpu_flags):
                cpu_model = cpu_type
                break
    else:
        logging.warn("Can not Get cpu flags from cpuinfo")

    if cpu_model:
        cpu_type_list = cpu_types.get(vendor)
        cpu_support_model = cpu_type_list[cpu_type_list.index(cpu_model):]
        cpu_model = ",".join(cpu_support_model)

    return cpu_model


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
