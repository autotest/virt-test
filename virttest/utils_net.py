import openvswitch
import re
import os
import socket
import collections
import fcntl
import struct
import logging
import random
import math
import time
import shelve
import commands

from autotest.client import utils, os_dep
from autotest.client.shared import error
from utils_params import Params
import propcan
import utils_misc
import arch
import aexpect
import virsh
import data_dir
from versionable_class import factory

CTYPES_SUPPORT = True
try:
    import ctypes
except ImportError:
    CTYPES_SUPPORT = False

SYSFS_NET_PATH = "/sys/class/net"
PROCFS_NET_PATH = "/proc/net/dev"
# globals
sock = None
sockfd = None


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


class MacvtapCreationError(NetError):

    def __init__(self, ifname, base_interface, details=None):
        NetError.__init__(self, ifname, details)
        self.ifname = ifname
        self.interface = base_interface
        self.details = details

    def __str__(self):
        e_msg = "Cannot create macvtap device %s " % self.ifname
        e_msg += "base physical interface %s." % self.interface
        if self.details is not None:
            e_msg += ": %s" % self.details
        return e_msg


class MacvtapGetBaseInterfaceError(NetError):

    def __init__(self, ifname=None, details=None):
        NetError.__init__(self, ifname, details)
        self.ifname = ifname
        self.details = details

    def __str__(self):
        e_msg = "Cannot get a valid physical interface to create macvtap."
        if self.ifname:
            e_msg += "physical interface is : %s " % self.ifname
        if self.details is not None:
            e_msg += "error info: %s" % self.details
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


class OpenflowSwitchError(NetError):

    def __init__(self, brname):
        NetError.__init__(self, brname)
        self.brname = brname

    def __str__(self):
        return ("Only support openvswitch, make sure your env support ovs, "
                "and your bridge %s is an openvswitch" % self.brname)


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


class HwOperstarteGetError(NetError):

    def __init__(self, ifname, details=None):
        NetError.__init__(self, ifname)
        self.ifname = ifname
        self.details = details

    def __str__(self):
        return "Get nic %s operstate error, %s" % (self.ifname, self.details)


class VlanError(NetError):

    def __init__(self, ifname, details):
        NetError.__init__(self, ifname, details)
        self.ifname = ifname
        self.details = details

    def __str__(self):
        return ("Vlan error on interface %s: %s" %
                (self.ifname, self.details))


class VMNetError(NetError):

    def __init__(self, reason):
        self.reason = reason

    def __str__(self):
        return self.reason


class DbNoLockError(NetError):

    def __str__(self):
        return "Attempt made to access database with improper locking"


def warp_init_del(func):
    def new_func(*args, **argkw):
        globals()["sock"] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        globals()["sockfd"] = globals()["sock"].fileno()
        try:
            return func(*args, **argkw)
        finally:
            globals()["sock"].close()
            globals()["sock"] = None
            globals()["sockfd"] = None
    return new_func


class Interface(object):

    ''' Class representing a Linux network device. '''

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return "<%s %s at 0x%x>" % (self.__class__.__name__,
                                    self.name, id(self))

    @warp_init_del
    def up(self):
        '''
        Bring up the bridge interface. Equivalent to ifconfig [iface] up.
        '''

        # Get existing device flags
        ifreq = struct.pack('16sh', self.name, 0)
        flags = struct.unpack('16sh',
                              fcntl.ioctl(sockfd, arch.SIOCGIFFLAGS, ifreq))[1]

        # Set new flags
        flags = flags | arch.IFF_UP
        ifreq = struct.pack('16sh', self.name, flags)
        fcntl.ioctl(sockfd, arch.SIOCSIFFLAGS, ifreq)

    @warp_init_del
    def down(self):
        '''
        Bring up the bridge interface. Equivalent to ifconfig [iface] down.
        '''

        # Get existing device flags
        ifreq = struct.pack('16sh', self.name, 0)
        flags = struct.unpack('16sh',
                              fcntl.ioctl(sockfd, arch.SIOCGIFFLAGS, ifreq))[1]

        # Set new flags
        flags = flags & ~arch.IFF_UP
        ifreq = struct.pack('16sh', self.name, flags)
        fcntl.ioctl(sockfd, arch.SIOCSIFFLAGS, ifreq)

    @warp_init_del
    def is_up(self):
        '''
        Return True if the interface is up, False otherwise.
        '''
        # Get existing device flags
        ifreq = struct.pack('16sh', self.name, 0)
        flags = struct.unpack('16sh',
                              fcntl.ioctl(sockfd, arch.SIOCGIFFLAGS, ifreq))[1]

        # Set new flags
        if flags & arch.IFF_UP:
            return True
        else:
            return False

    @warp_init_del
    def get_mac(self):
        '''
        Obtain the device's mac address.
        '''
        ifreq = struct.pack('16sH14s', self.name, socket.AF_UNIX, '\x00' * 14)
        res = fcntl.ioctl(sockfd, arch.SIOCGIFHWADDR, ifreq)
        address = struct.unpack('16sH14s', res)[2]
        mac = struct.unpack('6B8x', address)

        return ":".join(['%02X' % i for i in mac])

    @warp_init_del
    def set_mac(self, newmac):
        '''
        Set the device's mac address. Device must be down for this to
        succeed.
        '''
        macbytes = [int(i, 16) for i in newmac.split(':')]
        ifreq = struct.pack('16sH6B8x', self.name, socket.AF_UNIX, *macbytes)
        fcntl.ioctl(sockfd, arch.SIOCSIFHWADDR, ifreq)

    @warp_init_del
    def get_ip(self):
        """
        Get ip address of this interface
        """
        ifreq = struct.pack('16sH14s', self.name, socket.AF_INET, '\x00' * 14)
        try:
            res = fcntl.ioctl(sockfd, arch.SIOCGIFADDR, ifreq)
        except IOError:
            return None
        ip = struct.unpack('16sH2x4s8x', res)[2]

        return socket.inet_ntoa(ip)

    @warp_init_del
    def set_ip(self, newip):
        """
        Set the ip address of the interface
        """
        ipbytes = socket.inet_aton(newip)
        ifreq = struct.pack('16sH2s4s8s', self.name,
                            socket.AF_INET, '\x00' * 2, ipbytes, '\x00' * 8)
        fcntl.ioctl(sockfd, arch.SIOCSIFADDR, ifreq)

    @warp_init_del
    def get_netmask(self):
        """
        Get ip network netmask
        """
        if not CTYPES_SUPPORT:
            raise error.TestNAError(
                "Getting the netmask requires python > 2.4")
        ifreq = struct.pack('16sH14s', self.name, socket.AF_INET, '\x00' * 14)
        try:
            res = fcntl.ioctl(sockfd, arch.SIOCGIFNETMASK, ifreq)
        except IOError:
            return 0
        netmask = socket.ntohl(struct.unpack('16sH2xI8x', res)[2])

        return 32 - int(math.log(ctypes.c_uint32(~netmask).value + 1, 2))

    @warp_init_del
    def set_netmask(self, netmask):
        """
        Set netmask
        """
        if not CTYPES_SUPPORT:
            raise error.TestNAError(
                "Setting the netmask requires python > 2.4")
        netmask = ctypes.c_uint32(~((2 ** (32 - netmask)) - 1)).value
        nmbytes = socket.htonl(netmask)
        ifreq = struct.pack('16sH2si8s', self.name,
                            socket.AF_INET, '\x00' * 2, nmbytes, '\x00' * 8)
        fcntl.ioctl(sockfd, arch.SIOCSIFNETMASK, ifreq)

    @warp_init_del
    def get_index(self):
        '''
        Convert an interface name to an index value.
        '''
        ifreq = struct.pack('16si', self.name, 0)
        res = fcntl.ioctl(sockfd, arch.SIOCGIFINDEX, ifreq)
        return struct.unpack("16si", res)[1]

    @warp_init_del
    def get_stats(self):
        """
        Get the status information of the Interface
        """
        spl_re = re.compile(r"\s+")

        fp = open(PROCFS_NET_PATH)
        # Skip headers
        fp.readline()
        fp.readline()
        while True:
            data = fp.readline()
            if not data:
                return None

            name, stats_str = data.split(":")
            if name.strip() != self.name:
                continue

            stats = [int(a) for a in spl_re.split(stats_str.strip())]
            break

        titles = ["rx_bytes", "rx_packets", "rx_errs", "rx_drop", "rx_fifo",
                  "rx_frame", "rx_compressed", "rx_multicast", "tx_bytes",
                  "tx_packets", "tx_errs", "tx_drop", "tx_fifo", "tx_colls",
                  "tx_carrier", "tx_compressed"]
        return dict(zip(titles, stats))

    def is_brport(self):
        """
        Check Whether this Interface is a bridge port_to_br
        """
        path = os.path.join(SYSFS_NET_PATH, self.name)
        if os.path.exists(os.path.join(path, "brport")):
            return True
        else:
            return False


class Macvtap(Interface):

    """
    class of macvtap, base Interface
    """

    def __init__(self, tapname=None):
        if tapname is None:
            self.tapname = "macvtap" + utils_misc.generate_random_id()
        else:
            self.tapname = tapname
        Interface.__init__(self, self.tapname)

    def get_tapname(self):
        return self.tapname

    def get_device(self):
        return "/dev/tap%s" % self.get_index()

    def ip_link_ctl(self, params, ignore_status=False):
        return utils.run(os_dep.command("ip"), timeout=10,
                         ignore_status=ignore_status, verbose=False,
                         args=params)

    def create(self, device, mode="vepa"):
        """
        Create a macvtap device, only when the device does not exist.

        :param device: Macvtap device to be created.
        :param mode: Creation mode.
        """
        path = os.path.join(SYSFS_NET_PATH, self.tapname)
        if not os.path.exists(path):
            self.ip_link_ctl(["link", "add", "link", device, "name",
                             self.tapname, "type", "macvtap", "mode", mode])

    def delete(self):
        path = os.path.join(SYSFS_NET_PATH, self.tapname)
        if os.path.exists(path):
            self.ip_link_ctl(["link", "delete", self.tapname])

    def open(self):
        device = self.get_device()
        try:
            return os.open(device, os.O_RDWR)
        except OSError, e:
            raise TAPModuleError(device, "open", e)


def get_macvtap_base_iface(base_interface=None):
    """
    Get physical interface to create macvtap, if you assigned base interface
    is valid(not belong to any bridge and is up), will use it; else use the
    first physical interface,  which is not a brport and up.
    """
    tap_base_device = None

    (dev_int, _) = get_sorted_net_if()
    if not dev_int:
        err_msg = "Cannot get any physical interface from the host"
        raise MacvtapGetBaseInterfaceError(details=err_msg)

    if base_interface and base_interface in dev_int:
        base_inter = Interface(base_interface)
        if (not base_inter.is_brport()) and base_inter.is_up():
            tap_base_device = base_interface

    if not tap_base_device:
        if base_interface:
            warn_msg = "Can not use '%s' as macvtap base interface, "
            warn_msg += "will choice automatically"
            logging.warn(warn_msg % base_interface)
        for interface in dev_int:
            base_inter = Interface(interface)
            if base_inter.is_brport():
                continue
            if base_inter.is_up():
                tap_base_device = interface
                break

    if not tap_base_device:
        err_msg = ("Could not find a valid physical interface to create "
                   "macvtap, make sure the interface is up and it does not "
                   "belong to any bridge.")
        raise MacvtapGetBaseInterfaceError(details=err_msg)
    return tap_base_device


def create_macvtap(ifname, mode="vepa", base_if=None, mac_addr=None):
    """
    Create Macvtap device, return a object of Macvtap

    :param ifname: macvtap interface name
    :param mode:  macvtap type mode ("vepa, bridge,..)
    :param base_if: physical interface to create macvtap
    :param mac_addr: macvtap mac address
    """
    try:
        base_if = get_macvtap_base_iface(base_if)
        o_macvtap = Macvtap(ifname)
        o_macvtap.create(base_if, mode)
        if mac_addr:
            o_macvtap.set_mac(mac_addr)
        return o_macvtap
    except Exception, e:
        raise MacvtapCreationError(ifname, base_if, e)


def open_macvtap(macvtap_object, queues=1):
    """
    Open a macvtap device and returns its file descriptors which are used by
    fds=<fd1:fd2:..> parameter of qemu

    For single queue, only returns one file descriptor, it's used by
    fd=<fd> legacy parameter of qemu

    If you not have a switch support vepa in you env, run this type case you
    need at least two nic on you host [just workaround]

    :param macvtap_object:  macvtap object
    :param queues: Queue number
    """
    tapfds = []
    for queue in range(int(queues)):
        tapfds.append(str(macvtap_object.open()))
    return ":".join(tapfds)


def create_and_open_macvtap(ifname, mode="vepa", queues=1, base_if=None,
                            mac_addr=None):
    """
    Create a new macvtap device, open it, and return the fds

    :param ifname: macvtap interface name
    :param mode:  macvtap type mode ("vepa, bridge,..)
    :param queues: Queue number
    :param base_if: physical interface to create macvtap
    :param mac_addr: macvtap mac address
    """
    o_macvtap = create_macvtap(ifname, mode, base_if, mac_addr)
    return open_macvtap(o_macvtap, queues)


class Bridge(object):

    def get_structure(self):
        """
        Get bridge list.
        """
        ebr_i = re.compile(r"^(\S+).*?\s+$", re.MULTILINE)
        br_i = re.compile(r"^(\S+).*?(\S+)$", re.MULTILINE)
        nbr_i = re.compile(r"^\s+(\S+)$", re.MULTILINE)
        out_line = (utils.run(r"brctl show", verbose=False).stdout.splitlines())
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

        :param port_name: Name of port.
        :return: Bridge name or None if there is no bridge which contain port.
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

        :param ifname: Name of TAP device
        :param brname: Name of the bridge
        """
        try:
            self._br_ioctl(arch.SIOCBRADDIF, brname, ifname)
        except IOError, details:
            raise BRAddIfError(ifname, brname, details)

    def del_port(self, brname, ifname):
        """
        Remove a TAP device from bridge

        :param ifname: Name of TAP device
        :param brname: Name of the bridge
        """
        try:
            self._br_ioctl(arch.SIOCBRDELIF, brname, ifname)
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
                __ovs = factory(openvswitch.OpenVSwitchSystem)()
                __ovs.init_system()
                if (not __ovs.check()):
                    raise Exception("Check of OpenVSwitch failed.")
            except Exception, e:
                logging.debug("Host does not support OpenVSwitch: %s", e)

        return func(*args, **kargs)
    return wrap_init


# Global variable for OpenVSwitch
__ovs = None
__bridge = Bridge()


def if_nametoindex(ifname):
    """
    Map an interface name into its corresponding index.
    Returns 0 on error, as 0 is not a valid index

    :param ifname: interface name
    """
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
    ifr = struct.pack("16si", ifname, 0)
    r = fcntl.ioctl(ctrl_sock, arch.SIOCGIFINDEX, ifr)
    index = struct.unpack("16si", r)[1]
    ctrl_sock.close()
    return index


def vnet_mq_probe(tapfd):
    """
    Check if the IFF_MULTI_QUEUE is support by tun.

    :param tapfd: the file descriptor of /dev/net/tun
    """
    u = struct.pack("I", 0)
    try:
        r = fcntl.ioctl(tapfd, arch.TUNGETFEATURES, u)
    except OverflowError:
        logging.debug("Fail to get tun features!")
        return False
    flags = struct.unpack("I", r)[0]
    if flags & arch.IFF_MULTI_QUEUE:
        return True
    else:
        return False


def vnet_hdr_probe(tapfd):
    """
    Check if the IFF_VNET_HDR is support by tun.

    :param tapfd: the file descriptor of /dev/net/tun
    """
    u = struct.pack("I", 0)
    try:
        r = fcntl.ioctl(tapfd, arch.TUNGETFEATURES, u)
    except OverflowError:
        logging.debug("Fail to get tun features!")
        return False
    flags = struct.unpack("I", r)[0]
    if flags & arch.IFF_VNET_HDR:
        return True
    else:
        return False


def open_tap(devname, ifname, queues=1, vnet_hdr=True):
    """
    Open a tap device and returns its file descriptors which are used by
    fds=<fd1:fd2:..> parameter of qemu

    For single queue, only returns one file descriptor, it's used by
    fd=<fd> legacy parameter of qemu

    :param devname: TUN device path
    :param ifname: TAP interface name
    :param queues: Queue number
    :param vnet_hdr: Whether enable the vnet header
    """
    tapfds = []

    for i in range(int(queues)):
        try:
            tapfds.append(str(os.open(devname, os.O_RDWR)))
        except OSError, e:
            raise TAPModuleError(devname, "open", e)

        flags = arch.IFF_TAP | arch.IFF_NO_PI

        if vnet_mq_probe(int(tapfds[i])):
            flags |= arch.IFF_MULTI_QUEUE
        elif (int(queues) > 1):
            raise TAPCreationError(ifname, "Host doesn't support MULTI_QUEUE")

        if vnet_hdr and vnet_hdr_probe(int(tapfds[i])):
            flags |= arch.IFF_VNET_HDR

        ifr = struct.pack("16sh", ifname, flags)
        try:
            r = fcntl.ioctl(int(tapfds[i]), arch.TUNSETIFF, ifr)
        except IOError, details:
            raise TAPCreationError(ifname, details)

    return ':'.join(tapfds)


def is_virtual_network_dev(dev_name):
    """
    :param dev_name: Device name.

    :return: True if dev_name is in virtual/net dir, else false.
    """
    if dev_name in os.listdir("/sys/devices/virtual/net/"):
        return True
    else:
        return False


def find_dnsmasq_listen_address():
    """
    Search all dnsmasq listen addresses.

    :param bridge_name: Name of bridge.
    :param bridge_ip: Bridge ip.
    :return: List of ip where dnsmasq is listening.
    """
    cmd = "ps -Af | grep dnsmasq"
    result = utils.run(cmd).stdout
    return re.findall("--listen-address (.+?) ", result, re.MULTILINE)


def local_runner(cmd, timeout=None):
    return utils.run(cmd, verbose=False, timeout=timeout).stdout


def local_runner_status(cmd, timeout=None):
    return utils.run(cmd, verbose=False, timeout=timeout).exit_status


def get_net_if(runner=None, state=None):
    """
    :param runner: command runner.
    :param div_phy_virt: if set true, will return a tuple division real
                         physical interface and virtual interface
    :return: List of network interfaces.
    """
    if runner is None:
        runner = local_runner
    if state is None:
        state = ".*"
    cmd = "ip link"
    result = runner(cmd)
    return re.findall(r"^\d+: (\S+?)[@:].*state %s.*$" % (state),
                      result,
                      re.MULTILINE)


def get_sorted_net_if():
    """
    Get all network interfaces, but sort them among physical and virtual if.

    :return: Tuple (physical interfaces, virtual interfaces)
    """
    all_interfaces = get_net_if()
    phy_interfaces = []
    vir_interfaces = []
    for d in all_interfaces:
        path = os.path.join(SYSFS_NET_PATH, d)
        if not os.path.isdir(path):
            continue
        if not os.path.exists(os.path.join(path, "device")):
            vir_interfaces.append(d)
        else:
            phy_interfaces.append(d)
    return (phy_interfaces, vir_interfaces)


def get_net_if_addrs(if_name, runner=None):
    """
    Get network device ip addresses. ioctl not used because it's not
    compatible with ipv6 address.

    :param if_name: Name of interface.
    :return: List ip addresses of network interface.
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
    :return: Dict of interfaces and their addresses {"ifname": addrs}.
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

    :param if_name: Name of interface.
    :param ip_addr: Interface ip addr in format "ip_address/mask".
    :raise: IfChangeAddrError.
    """
    if runner is None:
        runner = local_runner
    cmd = "ip addr add %s dev %s" % (ip_addr, if_name)
    try:
        runner(cmd)
    except error.CmdError, e:
        raise IfChangeAddrError(if_name, ip_addr, e)


def get_net_if_operstate(ifname, runner=None):
    """
    Get linux host/guest network device operstate.

    :param if_name: Name of the interface.
    :raise: HwOperstarteGetError.
    """
    if runner is None:
        runner = local_runner
    cmd = "cat /sys/class/net/%s/operstate" % ifname
    try:
        operstate = runner(cmd)
        if "up" in operstate:
            return "up"
        elif "down" in operstate:
            return "down"
        elif "unknown" in operstate:
            return "unknown"
        else:
            raise HwOperstarteGetError(ifname, "operstate is not known.")
    except error.CmdError:
        raise HwOperstarteGetError(ifname, "run operstate cmd error.")


def ipv6_from_mac_addr(mac_addr):
    """
    :return: Ipv6 address for communication in link range.
    """
    mp = mac_addr.split(":")
    mp[0] = ("%x") % (int(mp[0], 16) ^ 0x2)
    return "fe80::%s%s:%sff:fe%s:%s%s" % tuple(mp)


def check_add_dnsmasq_to_br(br_name, tmpdir):
    """
    Add dnsmasq for bridge. dnsmasq could be added only if bridge
    has assigned ip address.

    :param bridge_name: Name of bridge.
    :param bridge_ip: Bridge ip.
    :param tmpdir: Tmp dir for save pid file and ip range file.
    :return: When new dnsmasq is started name of pidfile  otherwise return
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

    :param br_name: Name of interface.
    :return: (br_manager) which contain bridge or None.
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

    :param iface_name: Name of interface.
    :return: (br_manager, Bridge) which contain iface_name or None.
    """
    if ovs is None:
        ovs = __ovs
    # find ifname in standard linux bridge.
    master = __bridge
    bridge = master.port_to_br(iface_name)
    if bridge is None and ovs:
        master = ovs
        bridge = master.port_to_br(iface_name)

    if bridge is None:
        master = None

    return (master, bridge)


@__init_openvswitch
def change_iface_bridge(ifname, new_bridge, ovs=None):
    """
    Change bridge on which interface was added.

    :param ifname: Iface name or Iface struct.
    :param new_bridge: Name of new bridge.
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

    :param ifname: Name of TAP device
    :param brname: Name of the bridge
    :param ovs: OpenVSwitch object.
    """
    if ovs is None:
        ovs = __ovs

    _ifname = None
    if type(ifname) is str:
        _ifname = ifname
    elif issubclass(type(ifname), VirtIface):
        _ifname = ifname.ifname

    if brname in __bridge.list_br():
        # Try add port to standard bridge or openvswitch in compatible mode.
        __bridge.add_port(brname, _ifname)
        return

    if ovs is None:
        raise BRAddIfError(ifname, brname, "There is no bridge in system.")
    # Try add port to OpenVSwitch bridge.
    if brname in ovs.list_br():
        ovs.add_port(brname, ifname)


@__init_openvswitch
def del_from_bridge(ifname, brname, ovs=None):
    """
    Del a TAP device to bridge

    :param ifname: Name of TAP device
    :param brname: Name of the bridge
    :param ovs: OpenVSwitch object.
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
        # Try add port to standard bridge or openvswitch in compatible mode.
        __bridge.del_port(brname, _ifname)
        return

    # Try add port to OpenVSwitch bridge.
    if brname in ovs.list_br():
        ovs.del_port(brname, _ifname)


@__init_openvswitch
def openflow_manager(br_name, command, flow_options=None, ovs=None):
    """
    Manager openvswitch flow rules

    :param br_name: name of the bridge
    :param command: manager cmd(add-flow, del-flows, dump-flows..)
    :param flow_options: open flow options
    :param ovs: OpenVSwitch object.
    """
    if ovs is None:
        ovs = __ovs

    if ovs is None or br_name not in ovs.list_br():
        raise OpenflowSwitchError(br_name)

    manager_cmd = "ovs-ofctl %s %s" % (command, br_name)
    if flow_options:
        manager_cmd += " %s" % flow_options
    utils.run(manager_cmd)


def bring_up_ifname(ifname):
    """
    Bring up an interface

    :param ifname: Name of the interface
    """
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
    ifr = struct.pack("16sh", ifname, arch.IFF_UP)
    try:
        fcntl.ioctl(ctrl_sock, arch.SIOCSIFFLAGS, ifr)
    except IOError:
        raise TAPBringUpError(ifname)
    ctrl_sock.close()


def bring_down_ifname(ifname):
    """
    Bring up an interface

    :param ifname: Name of the interface
    """
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
    ifr = struct.pack("16sh", ifname, 0)
    try:
        fcntl.ioctl(ctrl_sock, arch.SIOCSIFFLAGS, ifr)
    except IOError:
        raise TAPBringUpError(ifname)
    ctrl_sock.close()


def if_set_macaddress(ifname, mac):
    """
    Set the mac address for an interface

    :param ifname: Name of the interface
    @mac: Mac address
    """
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)

    ifr = struct.pack("256s", ifname)
    try:
        mac_dev = fcntl.ioctl(ctrl_sock, arch.SIOCGIFHWADDR, ifr)[18:24]
        mac_dev = ":".join(["%02x" % ord(m) for m in mac_dev])
    except IOError, e:
        raise HwAddrGetError(ifname)

    if mac_dev.lower() == mac.lower():
        return

    ifr = struct.pack("16sH14s", ifname, 1,
                      "".join([chr(int(m, 16)) for m in mac.split(":")]))
    try:
        fcntl.ioctl(ctrl_sock, arch.SIOCSIFHWADDR, ifr)
    except IOError, e:
        logging.info(e)
        raise HwAddrSetError(ifname, mac)
    ctrl_sock.close()


class VirtIface(propcan.PropCan, object):
    """
    Networking information for single guest interface and host connection.
    """

    __slots__ = ('nic_name', 'mac', 'nic_model', 'ip',
                 'nettype', 'netdst')

    # Default to qemu-kvm prefix
    MACPREFIX = '52:54:00'
    # Make sure first byte generated is always zero and it follows
    # the class definition.  This helps provide more predictable
    # addressing while avoiding clashes between multiple NICs.
    LASTBYTE = random.SystemRandom().randint(0x00, 0xff)

    # Flag to turn off nettype warnings (mostly for unittests)
    NETTYPEWARN = True

    def __getstate__(self):
        """Help VirtIface objects be pickleable"""
        state = {}
        for key in self.__class__.__all_slots__:
            if key in self:
                state[key] = self[key]
        return state

    def __setstate__(self, state):
        """Help VirtIface objects be pickleable"""
        self.__init__(state)

    # This also helps with unittesting
    @staticmethod
    def arp_cache_macs():
        for mac in parse_arp().keys():
            yield mac

    @staticmethod
    def mac_is_valid(mac):
        # Result will be short if any conversion fails
        int_list = VirtIface.mac_str_to_int_list(mac)
        mac_str = VirtIface.int_list_to_mac_str(int_list)
        if len(mac_str) != len(mac):
            raise NetError("Mac address '%s' is not valid" % mac)

    def needs_mac(self):
        """
        Return True if nic has no mac or an incomplete mac
        """
        if hasattr(self, 'mac'):
            if self.mac is None or len(self.mac) < 17:
                return True
            else:
                return self.mac_is_valid(self.mac)
        return True

    def generate_mac_address(self, existing_macs=None, attempts=1024):
        """
        Set randomly generated mac address not found in existing_macs
        """
        if existing_macs is None:
            existing_macs = []
        # Add in known macs on local subnet
        arp_cache = self.arp_cache_macs()
        while attempts:
            mac = self.complete_mac_address()
            if mac in existing_macs or mac in arp_cache:
                attempts -= 1
            else:
                break
        if attempts:
            self.mac = mac
        else:
            raise NetError("MAC generation failed with prefix %s for NIC %s"
                           % (self.MACPREFIX,
                              self.nic_name))
        return self.mac

    @staticmethod
    def mac_str_to_int_list(mac_str):
        """
        Convert list of string bytes to int list

        :param mac: String format, ':' separated, mac address
        :return: list of 0 <= integer <= 256
        """
        int_list = []
        for byte in mac_str.split(':'):
            if len(byte.strip()) < 2:
                continue # skip non-zero padded byte strings
            try:
                _int = int(byte, base=16)
                if _int < 0 or _int > 255:
                    break
                else:
                    int_list.append(_int)
            except ValueError:
                break
        return int_list

    @staticmethod
    def int_list_to_mac_str(int_list):
        """
        Return string formatting of int mac_bytes

        :param int_list: list of 0 <= integer <= 256
        :return: String format, ':' separated, mac address
        """
        byte_str_list = []
        for _int in int_list:
            if _int < 16:  #  needs zero-padding
                byte_str_list.append("0%x" % _int)
            else:
                byte_str_list.append("%x" % _int)
        return ":".join(byte_str_list)

    def generate_byte(self):
        """
        Return next byte from ring
        """
        while True:
            self.__class__.LASTBYTE += 1
            if self.__class__.LASTBYTE > 0xff:
                self.__class__.LASTBYTE = 0
            yield self.__class__.LASTBYTE

    def complete_mac_address(self):
        """
        Append randomly started bytes to MACPREFIX
        """
        # Convertng from, then to str guaranteese format is correct
        if self.has_key('mac'):
            self.mac_is_valid(self.mac)
            mac = self.mac_str_to_int_list(self.mac)
        else:
            self.mac_is_valid(self.MACPREFIX)
            mac = self.mac_str_to_int_list(self.MACPREFIX)
        if len(mac) < 6:
            for byte in self.generate_byte():
                mac.append(byte)
                if len(mac) == 6:
                    break
        return self.int_list_to_mac_str(mac)

    @staticmethod
    def giabi(name):
        """
        Shortcut to Get IP Address by interface ("device" name)
        """
        return get_ip_address_by_interface(name)

    def set_nettype(self, value):
        """
        Log warning for unknown/unsupported networking types
        """
        if self.NETTYPEWARN:
            if value not in ('user', 'network', 'bridge', 'private', 'macvtap'):
                logging.warning('Setting nic %s to unknown/unsupported '
                                'nettype %s', self.nic_name, value)
        return self.__dict_set__('nettype', value)


class LibvirtQemuIface(VirtIface):
    """
    Networking information specific to libvirt qemu
    """
    # FIXME: Should openvswitch have it's own interface class?
    __slots__ = ['g_nic_name']


class LibvirtXenIface(VirtIface):
    """
    Networking information specific to xen
    """
    __slots__ = []
    # This is special for Xen, because Xen is "special"
    MACPREFIX = "00:16:3e"


# TODO: Split into classes along pci_assignable values
class QemuIface(VirtIface):
    """
    Networking information specific to Qemu-
    """

    __slots__ = ['vlan', 'device_id', 'ifname', 'tapfds',
                 'tapfd_ids', 'netdev_id', 'tftp', 'bootindex',
                 'bootfile', 'nic_extra_params', 'vhost',
                 'netdev_extra_params', 'queues', 'vhostfds',
                 'vectors', 'pci_assignable', 'enable_msix_vectors',
                 'root_dir', 'pci_addr', 'pci_bus', 'macvtap_mode'
                 'device_driver', 'device_name', 'enable_vhostfd']

    # Wether or not full paths should be supplied on access
    MANGLE_PATHS = True
    # Weather or not to enforce integer values
    FORCE_INTS = True

    def set_vlan(self, value):
        if self.FORCE_INTS:
            self.__dict_set__('vlan', int(value))
        else:
            self.__dict_set__('vlan', value)

    def set_queues(self, value):
        if self.FORCE_INTS:
            self.__dict_set__('queues', int(value))
        else:
            self.__dict_set__('queues', value)

    def set_vectors(self, value):
        if self.FORCE_INTS:
            self.__dict_set__('vectors', int(value))
        else:
            self.__dict_set__('vectors', value)

    # Store filename, return full path
    def get_tftp(self):
        tftp = self.__dict_get__('tftp')
        if self.MANGLE_PATHS and self.get('root_dir') is not None:
            return utils_misc.get_path(self.root_dir, tftp)
        else:
            return tftp

    # Some qemu_vm specific helpers
    def generate_ifname(self):
        prefix = "t%d-" % self.vlan
        postfix = utils_misc.generate_random_string(6)
        # Ensure interface name doesn't excede 11 characters
        self.ifname = (prefix[:5] + postfix)

    def generate_netdev_id(self):
        self.netdev_id = utils_misc.generate_random_id()

    def generate_tapfd_ids(self):
        self.tapfd_ids = [utils_misc.generate_random_id()
                          for queue in xrange(self.queues)]

    def generate_device_id(self):
        self.device_id = utils_misc.generate_random_id()

    def add_nic_tap(self):
        if self.nettype == 'macvtap':
            macvtap_mode = self.get("macvtap_mode", "vepa")
            self.tapfds = create_and_open_macvtap(self.ifname,
                                                  macvtap_mode,
                                                  self.queues,
                                                  self.netdst,
                                                  self.mac)
        else:
            self.tapfds = open_tap("/dev/net/tun", self.ifname,
                                   queues=self.queues, vnet_hdr=True)
            logging.debug("Adding NIC %s to bridge %s",
                          self.nic_name, self.netdst)
            if self.nettype == 'bridge':
                add_to_bridge(self.ifname, self.netdst)
        bring_up_ifname(self.ifname)

    def del_nic_tap(self):
        try:
            if self.nettype == 'macvtap':
                logging.info("Remove macvtap for nic %s", self.nic_name)
                tap = Macvtap(self.ifname)
                tap.delete()
            else:
                logging.debug("Removing NIC %s from bridge %s",
                              self.nic_name, self.netdst)
                if self.tapfds:
                    for i in self.tapfds.split(':'):
                        os.close(int(i))
                if self.vhostfds:
                    for i in self.vhostfds.split(':'):
                        os.close(int(i))
                if self.ifname and self.ifname not in get_net_if():
                    _, br_name = find_current_bridge(self.ifname)
                    if br_name == self.netdst:
                        del_from_bridge(self.ifname, self.netdst)
        except TypeError:
            logging.warning("Ignoring failure to remove tap")


class VirtNetBase(collections.MutableSequence, list):
    """
    Collection of networking information with basic facilities
    """

    # Skip comparison of these keys to other instances items
    do_not_compare = set(['nic_name'])

    # May be overridden by subclasses
    container_class = VirtIface

    # Opaqe Cache instances for possible use by subclasses
    last_source = None

    def __init__(self, container_class=VirtIface, iterable=None):
        """
        Parser base-class of networking information into a container_class

        :param vm: Virt.BaseVM instance
        :param container_class: a VirtIface or subclass instance
        """
        super(VirtNetBase, self).__init__()
        self.container_class = container_class
        if iterable is not None:
            for item in iterable:
                self.append(item)

    def __getitem__(self, index_or_name):
        try:
            return list.__getitem__(self, index_or_name)
        except TypeError: # index_or_name is a string
            # Raises Index error if name not found
            index = self.nic_name_index(index_or_name)
            return list.__getitem__(self, index)

    def __setitem__(self, index_or_name, value):
        if not isinstance(value, VirtIface):
            value = self.container_class(value)
        if isinstance(index_or_name, (str, unicode)):
            index = self.nic_name_index(index_or_name)
        else:
            index = int(index_or_name)
        list.__setitem__(self, index, value)

    def __delitem__(self, index_or_name):
        try:
            list.__delitem__(self, index_or_name)
        except TypeError:
            index = self.nic_name_index(index_or_name)
            list.__delitem__(self, index)

    def __len__(self):
        return list.__len__(self)

    def __eq__(self, other):
        if len(self) != len(other):
            return False
        # Don't assume different container class items won't match
        for index, self_nic in enumerate(self):
            other_nic = other[index]
            self_keys = set(self_nic.keys()) - self.do_not_compare
            other_keys = set(other_nic.keys()) - self.do_not_compare
            if self_keys.symmetric_difference(other_keys):
                return False
            else:
                # all keys are common to both
                for key in self_keys:
                    value = self_nic[key]
                    if value != other_nic[key]:
                        return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def insert(self, index, item):
        if not isinstance(item, VirtIface):
            item = list.insert(self, index, self.container_class(item))
        if item['nic_name'] in self.nic_name_list():
            raise VMNetError("Attempting to insert duplicate nic_name item")
        return list.insert(self, index, item)

    def append(self, value):
        if not isinstance(value, VirtIface):
            value = self.container_class(value)
        if value['nic_name'] in self.nic_name_list():
            raise VMNetError("Attempting to append nic with duplicate "
                             "nic_name: '%s'" % value['nic_name'])
        else:
            list.append(self, value)

    def __reduce__(self):
        # Don't attempt to pickle opaque objects
        call = self.__class__
        args = (self.container_class,)
        state = {}
        iterator = (item for item in self)
        return (call, args, state, iterator)

    def nic_name_index(self, name):
        """
        Return the index number for name, or raise KeyError
        """
        return self.nic_name_list().index(str(name))

    def nic_name_list(self):
        """
        Obtain list of nic names from lookup of contents 'nic_name' key.
        """
        return [item['nic_name'] for item in self]

    def all_macs(self, other=None):
        """
        Generator over all instance mac addresses (duplicates possible)

        :param other: Separate VirtNet subclass to check also
        :return: generator over mac address strings
        """
        gen1 = (nic.mac for nic in self if hasattr(nic, 'mac'))
        gen2 = self.container_class.arp_cache_macs()
        for mac in gen1:
            yield mac
        for mac in gen2:
            yield mac
        if other is not None:
            for mac in other:
                yield mac

    def host_ip(self):
        """
        Return IPv4 address of a host-side interface
        """
        # Empty 'params' dict forces lookup by default host device
        return get_host_ip_address({})

    def update_from(self, source, key=None):
        """
        Add/update current contents from iterable source of dict-likes

        :param source: iterable source of dict-likes containing nic info.
        :param key: ignored, for sub-class use
        """
        del key
        # DO NOT update last_source, it is opaque to this class
        for index, nic in enumerate(source):
            if nic.get('nic_name') is None:
                logging.warning("Refusing to enumerate VirtIface or subclass "
                                "instance without required nic_name "
                                "parameter: %s", nic)
                continue
            if not isinstance(nic, VirtIface):
                nic = self.container_class(nic)
            try:
                self[index].update(nic)
            except IndexError:
                self.append(nic)

    def load_from(self, source, key=None):
        """
        Remove existing, then add contents from iterable source of dict-likes

        :param source: iterable source of dict-likes containing nic info.
        :param key: passed through to update_from()
        """
        del self[::]
        self.update_from(source, key)

    def merge_from(self, source, key=None):
        """
        Add contents from iterable source of dict-likes, then update existing

        :param source: iterable source of dict-likes containing nic info.
        :param key: passed through to update_from()
        """
        old_contents = [item for item in self]
        self.load_from(source, key)
        self.update_from(old_contents, key)

    def convert_to(self, other_class):
        """Returns another VirtNetBase subclass containing the same data"""
        if not issubclass(other_class, VirtNetBase):
            raise TypeError("Other class '%s' is not a VirtNetBase or subclass"
                            % other_class)
        return other_class(self.container_class, self)

class VirtNetParams(VirtNetBase):
    """
    Interface to read networking info from a params instance
    """

    def update_from(self, source, key):
        """
        Add/update contents from source params for key vm_name

        :param source: A Params instance
        :param key: vm_name of properties to load
        """
        if not isinstance(source, Params):
            raise ValueError("Source must be a Params instance, not a %s"
                             % source.__class__.__name__)
        self.last_source = source
        if key is None or key not in source.objects('vms'):
            raise ValueError("Can't load networking params for Vm '%s'"
                             " because it is not in 'vms' params key"
                              % key)
        # Super class requires flat-list
        new_source = []
        # Get nics_<vm_name>
        vm_params = source.object_params(key)
        # nic_name parameter must be added specially
        for nic_name in vm_params.objects('nics'):
            nic_params = vm_params.object_params(nic_name)
            # nic_params is a copy, safe to modify
            nic_params['nic_name'] = nic_name
            # Don't present a netdst for user-mode networking
            if nic_params.has_key('nettype'):
                if nic_params.has_key('netdst'):
                    if nic_params['nettype'] == 'user':
                        del nic_params['netdst']
            new_source.append(nic_params)
        super(VirtNetParams, self).update_from(new_source, key)


    def _params_macs(self):
        if self.last_source is not None:
            for vm_name in self.last_source.objects('vms'):
                vm_params = self.last_source.object_params(vm_name)
                for nic_name in vm_params.objects('nics'):
                    nic_params = vm_params.object_params(nic_name)
                    mac = nic_params.get('mac')
                    if mac is not None:
                        mac = mac.strip().lower()
                        # Only return complete & valid macs found in params
                        valid = self.container_class.mac_is_valid(mac)
                        length = len(mac) == 17 #  characters long
                        if valid and length:
                            yield mac

    def all_macs(self, other=None):
        """
        Generator over all instance mac addresses (duplicates possible)

        :param other: Separate VirtNet subclass to check also
        :return: generator over mac address strings
        """
        gen1 = super(VirtNetParams, self).all_macs(other)
        gen2 = self._params_macs()
        for mac in gen1:
            yield mac
        for mac in gen2:
            yield mac

    def host_ip(self):
        """
        Return IPv4 address of a host-side interface
        """
        if self.last_source is not None:
            return get_host_ip_address(self.last_source)
        else:
            # Call with empty params
            super(VirtNetParams, self).host_ip()


class VirtNetDB(VirtNetBase):
    """
    Interface to read/write networking info to a database
    """

    @staticmethod
    def _lock_db(filename):
        """Lock database and return lockfile and dict-like instance"""
        return (utils_misc.lock_file(filename + ".lock"), shelve.open(filename))

    @staticmethod
    def _unlock_db(lockfile, database):
        try:
            database.close()
        except AttributeError:  # Ignore if database is None
            pass
        try:
            utils_misc.unlock_file(lockfile)
        except AttributeError:  # Ignore if lockfile is None
            pass

    def update_from(self, source, key):
        """
        Add/update from database filename source for key vm instance

        :param source: database filename
        :param key: key in database
        """
        # ABS defines key as optional, but it's required for this class
        if key is None or key.strip() == '':
            raise ValueError("Must pass key to update_from() "
                             "on VirtNetDB or subclass instance")
        self.last_source = source
        try:
            lockfile, database = self._lock_db(source) # Blocks!
            source = database[key]
        finally:
            self._unlock_db(lockfile, database)
        super(VirtNetDB, self).update_from(source, key)

    def store_to(self, destination, key):
        """
        Save current contents as a list of dictionaries to destination under key
        """
        # Assume future access to same location
        self.last_source = destination
        # No need to store instance attributes
        contents = []
        for nic in self:
            contents.append(nic)
        lockfile = database = None
        try:
            lockfile, database = self._lock_db(destination) # Blocks!
            database[key] = contents
        finally:
            self._unlock_db(lockfile, database)

    def remove(self, key, dbfilename=None):
        """
        Remove all database entries for key, if they exist
        """
        if dbfilename is None:
            dbfilename = self.last_source
        try:
            try:
                lockfile, database = self._lock_db(dbfilename) # Blocks!
                del database[key]
            finally:
                self._unlock_db(lockfile, database)
        except KeyError:
            pass

    def _db_macs(self, dbfilename=None):
        if dbfilename is None:
            dbfilename = self.last_source
            contents = []
            try:
                lockfile, database = self._lock_db(dbfilename) # Blocks!
                for value in database.values():
                    contents.append(value)
            finally:
                self._unlock_db(lockfile, database)
            for value in contents:
                for nic in value:
                    if nic.has_key('mac'):
                        yield nic['mac']

    def all_macs(self, other=None):
        """
        Generator over all mac addresses found in last database used
        """
        gen1 = super(VirtNetDB, self).all_macs(other)
        gen2 = self._db_macs()
        for mac in gen1:
            yield mac
        for mac in gen2:
            yield mac

class VirtNetLibvirt(VirtNetBase):
    """
    Interface to read networking info from libvirt VM's definitions
    """

    # Skip comparison of these keys to other instances items
    # needed for interoperability with qemu_vm params
    do_not_compare = set(QemuIface.__slots__)
    do_not_compare.add('nic_name')  #  not used in libvirt
    do_not_compare.add('ip')  #  not used in libvirt

    # Mostly to help with unittesting
    _virsh_class = virsh.Virsh

    def update_from(self, source, key):
        """
        Add/update from virsh instance with vm name as key

        :param source: virsh instance
        :param key: domain name
        """
        if not isinstance(source, self._virsh_class):
            raise ValueError("Source must be a virsh or subclass instance")
        self.last_source = source
        nic_list = []
        # Convention is to start from nic1
        index = 1
        for iface in self.iflist_to_dict()[key]:
            nic = {'nic_name':'nic%d' % index}
            if iface.get('mac') is not None:
                nic['mac'] = iface['mac']
            nic['nic_model'] = iface.get('model', 'virtio')
            nic['nettype'] = iface.get('type', 'user')
            if nic['nettype'] != 'user':
                nic['netdst'] = iface.get('source')
            nic_list.append(nic)
            index += 1
        super(VirtNetLibvirt, self).update_from(nic_list, key)

    def all_domnames(self):
        """Return list of all current domains"""
        if self.last_source is None:
            return []
        cmdresult = self.last_source.dom_list(options="--all")
        assert cmdresult.exit_status == 0
        lines = cmdresult.stdout.strip().splitlines()
        # remove header lines
        del lines[0:2]
        # 2nd column is domain name
        return [line.split()[1] for line in lines]

    def iflist_to_dict(self):
        result = {}
        for dom_name in self.all_domnames():
            domiflist = []
            cmdresult = self.last_source.domiflist(dom_name)
            assert cmdresult.exit_status == 0
            lines = cmdresult.stdout.strip().splitlines()
            # top-down processing
            lines.reverse()
            columns = [col.strip().lower() for col in lines.pop().split()]
            while lines:
                data = [dat.strip().lower() for dat in lines.pop().split()]
                if len(data) < len(columns):
                    continue  # "--------" line
                domiflist.append(dict(zip(columns, data)))
            result[dom_name] = domiflist
        return result

    def _libvirt_macs(self):
        # Don't care about domain name
        for domiflist in self.iflist_to_dict().values():
            for iface in domiflist:
                yield iface['mac']

    def all_macs(self, other=None):
        """
        Generator over all mac addresses found in last database used
        """
        gen1 = super(VirtNetLibvirt, self).all_macs(other)
        gen2 = self._libvirt_macs()
        for mac in gen1:
            yield mac
        for mac in gen2:
            yield mac


def parse_arp():
    """
    Read /proc/net/arp, return a mapping of MAC to IP

    :return: dict mapping MAC to IP
    """
    ret = {}
    arp_cache = file('/proc/net/arp').readlines()

    for line in arp_cache:
        mac = line.split()[3]
        ip = line.split()[0]

        # Skip the header
        if mac.count(":") != 5:
            continue

        ret[mac] = ip

    return ret


def verify_ip_address_ownership(ip, macs, timeout=10.0):
    """
    Use arping and the ARP cache to make sure a given IP address belongs to one
    of the given MAC addresses.

    :param ip: An IP address.
    :param macs: A list or tuple of MAC addresses.
    :return: True if ip is assigned to a MAC address in macs.
    """
    ip_map = parse_arp()
    for mac in macs:
        if ip_map.get(mac) == ip:
            return True

    # Compile a regex that matches the given IP address and any of the given
    # MAC addresses
    mac_regex = "|".join("(%s)" % mac for mac in macs)
    regex = re.compile(r"\b%s\b.*\b(%s)\b" % (ip, mac_regex), re.IGNORECASE)

    # Get the name of the bridge device for arping
    o = commands.getoutput("%s route get %s" %
                           (utils_misc.find_command("ip"), ip))
    dev = re.findall(r"dev\s+\S+", o, re.IGNORECASE)
    if not dev:
        return False
    dev = dev[0].split()[-1]

    # Send an ARP request
    o = commands.getoutput("%s -f -c 3 -I %s %s" %
                           (utils_misc.find_command("arping"), dev, ip))
    return bool(regex.search(o))


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
    :param ifname - interface name
    :raise NetError - When failed to fetch IP address (ioctl raised IOError.).

    Retrieves interface address from socket fd trough ioctl call
    and transforms it into string from 32-bit packed binary
    by using socket.inet_ntoa().

    """
    mysocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        return socket.inet_ntoa(fcntl.ioctl(
            mysocket.fileno(),
            arch.SIOCGIFADDR,
            # ifname to binary IFNAMSIZ == 16
            struct.pack('256s', ifname[:15])
        )[20:24])
    except IOError:
        raise NetError(
            "Error while retrieving IP address from interface %s." % ifname)


def get_host_ip_address(params):
    """
    returns ip address of host specified in host_ip_addr parameter If provided.
    Otherwise look up the ip address on interface used for the default route.
    :param params
    """
    host_ip = params.get('host_ip_addr')
    if host_ip is None:
        rt_tbl = open('/proc/net/route', 'rb')
        header = rt_tbl.readline()
        # Uniform lower-case for consistent references
        col_names = [name.lower() for name in header.split()]
        # Only need 3 columns data, using dict would be overkill
        iface_idx = col_names.index('iface')
        dest_idx = col_names.index('destination')
        flag_idx = col_names.index('flags')
        # Flags defined by kernel: include/linux/route.h
        RTF_UP = 0x0001 #  route usable (flags)
        # default route dest will be '00000000' and RTF_GATEWAY & RTF_UP set
        for line in rt_tbl:
            data = tuple([name.lower() for name in line.split()])
            flags = int(data[flag_idx]) #  bit-field
            dest = data[dest_idx] #  byte-reversed hexadecimal
            iface = data[iface_idx] #  device name
            if bool(flags & RTF_UP):
                if dest == '00000000':  # 'default' route
                    return get_ip_address_by_interface(iface)
        # Command failed or no default route defined
        raise NetError("Can't determine host ip from host_ip_addr param "
                       "or from default route device name.")
    # Not None, assume value is correct
    return host_ip


def get_linux_ifname(session, mac_address=""):
    """
    Get the interface name through the mac address.

    :param session: session to the virtual machine
    @mac_address: the macaddress of nic

    :raise error.TestError in case it was not possible to determine the
            interface name.
    """
    def _process_output(cmd, reg_pattern):
        try:
            output = session.cmd(cmd)
            ifname_list = re.findall(reg_pattern, output, re.I)
            if not ifname_list:
                return None
            if mac_address:
                return ifname_list[0]
            if "lo" in ifname_list:
                ifname_list.remove("lo")
            return ifname_list
        except aexpect.ShellCmdError:
            return None

    # Try ifconfig first
    i = _process_output("ifconfig -a", r"(\w+)\s+Link.*%s" % mac_address)
    if i is not None:
        return i

    # No luck, try ip link
    i = _process_output("ip link | grep -B1 '%s' -i" % mac_address,
                        r"\d+:\s+(\w+):\s+.*")
    if i is not None:
        return i

    # No luck, look on /sys
    cmd = r"grep '%s' /sys/class/net/*/address " % mac_address
    i = _process_output(cmd, r"net/(\w+)/address:%s" % mac_address)
    if i is not None:
        return i

    # If we came empty handed, let's raise an error
    raise error.TestError("Failed to determine interface name with "
                          "mac %s" % mac_address)


def restart_guest_network(session, nic_name=None):
    """
    Restart guest's network via serial console.

    :param session: session to virtual machine
    @nic_name: nic card name in guest to restart
    """
    if_list = []
    if not nic_name:
        # initiate all interfaces on guest.
        o = session.cmd_output("ip link")
        if_list = re.findall(r"\d+: (eth\d+):", o)
    else:
        if_list.append(nic_name)

    if if_list:
        session.sendline("killall dhclient && "
                         "dhclient %s &" % ' '.join(if_list))


def update_mac_ip_address(vm, params, timeout=None):
    """
    Get mac and ip address from guest then update the mac pool and
    address cache

    :param vm: VM object
    :param params: Dictionary with the test parameters.
    """
    network_query = params.get("network_query", "ifconfig")
    restart_network = params.get("restart_network", "service network restart")
    mac_ip_filter = params.get("mac_ip_filter")
    if timeout is None:
        timeout = int(params.get("login_timeout"))
    session = vm.wait_for_serial_login(timeout=360)
    end_time = time.time() + timeout
    macs_ips = []
    num = 0
    while time.time() < end_time:
        try:
            if num % 3 == 0 and num != 0:
                session.cmd(restart_network)
            output = session.cmd_status_output(network_query)[1]
            macs_ips = re.findall(mac_ip_filter, output, re.S)
            # Get nics number
        except Exception, err:
            logging.error(err)
        nics = params.get("nics")
        nic_minimum = len(re.split(r"\s+", nics.strip()))
        if len(macs_ips) == nic_minimum:
            break
        num += 1
        time.sleep(5)
    if len(macs_ips) < nic_minimum:
        logging.error("Not all nics get ip address")

    for (_ip, mac) in macs_ips:
        vlan = macs_ips.index((_ip, mac))
        # _ip, mac are in different sequence in Fedora and RHEL guest.
        if re.match(".\d+\.\d+\.\d+\.\d+", mac):
            _ip, mac = mac, _ip
        if "-" in mac:
            mac = mac.replace("-", ".")
        vm.address_cache[mac.lower()] = _ip
        vm.virtnet.set_mac_address(vlan, mac)


def get_windows_nic_attribute(session, key, value, target, timeout=240):
    """
    Get the windows nic attribute using wmic. All the support key you can
    using wmic to have a check.

    :param session: session to the virtual machine
    :param key: the key supported by wmic
    :param value: the value of the key
    :param target: which nic attribute you want to get.

    """
    cmd = 'wmic nic where %s="%s" get %s' % (key, value, target)
    o = session.cmd(cmd, timeout=timeout).strip()
    if not o:
        raise error.TestError("Get guest nic attribute %s failed!" % target)
    return o.splitlines()[-1]


def set_win_guest_nic_status(session, connection_id, status, timeout=240):
    """
    Set windows guest nic ENABLED/DISABLED

    :param  session : session to virtual machine
    :param  connection_id : windows guest nic netconnectionid
    :param  status : set nic ENABLED/DISABLED
    """
    cmd = 'netsh interface set interface name="%s" admin=%s'
    session.cmd(cmd % (connection_id, status), timeout=timeout)


def disable_windows_guest_network(session, connection_id, timeout=240):
    return set_win_guest_nic_status(session, connection_id,
                                    "DISABLED", timeout)


def enable_windows_guest_network(session, connection_id, timeout=240):
    return set_win_guest_nic_status(session, connection_id,
                                    "ENABLED", timeout)


def restart_windows_guest_network(session, connection_id, timeout=240,
                                  mode="netsh"):
    """
    Restart guest's network via serial console. mode "netsh" can not
    works in winxp system

    :param session: session to virtual machine
    :param connection_id: windows nic connectionid,it means connection name,
                          you Can get connection id string via wmic
    """
    if mode == "netsh":
        disable_windows_guest_network(session, connection_id, timeout=timeout)
        enable_windows_guest_network(session, connection_id, timeout=timeout)
    elif mode == "devcon":
        restart_windows_guest_network_by_devcon(session, connection_id)


def restart_windows_guest_network_by_key(session, key, value, timeout=240,
                                         mode="netsh"):
    """
    Restart the guest network by nic Attribute like connectionid,
    interfaceindex, "netsh" can not work in winxp system.
    using devcon mode must download devcon.exe and put it under c:\

    :param session: session to virtual machine
    :param key: the key supported by wmic nic
    :param value: the value of the key
    :param timeout: timeout
    :param mode: command mode netsh or devcon
    """
    if mode == "netsh":
        oper_key = "netconnectionid"
    elif mode == "devcon":
        oper_key = "pnpdeviceid"

    id = get_windows_nic_attribute(session, key, value, oper_key, timeout)
    if not id:
        raise error.TestError("Get nic %s failed" % oper_key)
    if mode == "devcon":
        id = id.split("&")[-1]

    restart_windows_guest_network(session, id, timeout, mode)


def set_guest_network_status_by_devcon(session, status, netdevid,
                                       timeout=240):
    """
    using devcon to enable/disable the network device.
    using it must download the devcon.exe, and put it under c:\
    """
    set_cmd = r"c:\devcon.exe %s  =Net @PCI\*\*%s" % (status, netdevid)
    session.cmd(set_cmd, timeout=timeout)


def restart_windows_guest_network_by_devcon(session, netdevid, timeout=240):

    set_guest_network_status_by_devcon(session, 'disable', netdevid)
    set_guest_network_status_by_devcon(session, 'enable', netdevid)
