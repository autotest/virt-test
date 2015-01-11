"""
High-level libvirt test utility functions.

This module is meant to reduce code size by performing common test procedures.
Generally, code here should look like test code.

More specifically:
    - Functions in this module should raise exceptions if things go wrong
    - Functions in this module typically use functions and classes from
      lower-level modules (e.g. utils_misc, qemu_vm, aexpect).
    - Functions in this module should not be used by lower-level modules.
    - Functions in this module should be used in the right context.
      For example, a function should not be used where it may display
      misleading or inaccurate info or debug messages.

:copyright: 2014 Red Hat Inc.
"""

import re
import os
import logging
import shutil
import threading
import time
from virttest import virsh
from virttest import xml_utils
from virttest import iscsi
from virttest import nfs
from virttest import data_dir
from virttest import aexpect
from virttest import utils_misc
from virttest import utils_selinux
from virttest import libvirt_storage
from virttest import utils_net
from virttest import gluster
from virttest import remote
from virttest.utils_libvirtd import service_libvirtd_control
from autotest.client import utils
from autotest.client.shared import error
from virttest.libvirt_xml import vm_xml
from virttest.libvirt_xml import xcepts
from virttest.libvirt_xml import NetworkXML
from virttest.libvirt_xml import IPXML
from virttest.libvirt_xml.devices import disk
from virttest.libvirt_xml.devices import hostdev
from virttest.libvirt_xml.devices import controller
from __init__ import ping
try:
    from autotest.client import lv_utils
except ImportError:
    from virttest.staging import lv_utils


class LibvirtNetwork(object):

    """
    Class to create a temporary network for testing.
    """

    def create_vnet_xml(self):
        """
        Create XML for a virtual network.
        """
        net_xml = NetworkXML()
        net_xml.name = self.name
        ip = IPXML(address=self.address)
        net_xml.ip = ip
        return self.address, net_xml

    def create_macvtap_xml(self):
        """
        Create XML for a macvtap network.
        """
        net_xml = NetworkXML()
        net_xml.name = self.name
        net_xml.forward = {'mode': 'bridge', 'dev': self.iface}
        ip = utils_net.get_ip_address_by_interface(self.iface)
        return ip, net_xml

    def create_bridge_xml(self):
        """
        Create XML for a bridged network.
        """
        net_xml = NetworkXML()
        net_xml.name = self.name

        net_xml.forward = {'mode': 'bridge'}
        net_xml.bridge = {'name': self.iface}
        ip = utils_net.get_ip_address_by_interface(self.iface)
        return ip, net_xml

    def __init__(self, net_type, address=None, iface=None):
        self.name = 'virt-test-%s' % net_type
        self.address = address
        self.iface = iface

        if net_type == 'vnet':
            if not self.address:
                raise error.TestError('Create vnet need address be set')
            self.ip, net_xml = self.create_vnet_xml()
        elif net_type == 'macvtap':
            if not self.iface:
                raise error.TestError('Create macvtap need iface be set')
            self.ip, net_xml = self.create_macvtap_xml()
        elif net_type == 'bridge':
            if not self.iface:
                raise error.TestError('Create bridge need iface be set')
            self.ip, net_xml = self.create_bridge_xml()
        else:
            raise error.TestError('Unknown libvirt network type %s' % net_type)
        net_xml.create()

    def destroy(self):
        """
        Clear up created network.
        """
        return virsh.net_destroy(self.name)


def cpus_parser(cpulist):
    """
    Parse a list of cpu list, its syntax is a comma separated list,
    with '-' for ranges and '^' denotes exclusive.
    :param cpulist: a list of physical CPU numbers
    """
    hyphens = []
    carets = []
    commas = []
    others = []

    if cpulist is None:
        return None

    else:
        if "," in cpulist:
            cpulist_list = re.split(",", cpulist)
            for cpulist in cpulist_list:
                if "-" in cpulist:
                    tmp = re.split("-", cpulist)
                    hyphens = hyphens + range(int(tmp[0]), int(tmp[-1]) + 1)
                elif "^" in cpulist:
                    tmp = re.split("\^", cpulist)[-1]
                    carets.append(int(tmp))
                else:
                    try:
                        commas.append(int(cpulist))
                    except ValueError:
                        logging.error("The cpulist has to be an "
                                      "integer. (%s)", cpulist)
        elif "-" in cpulist:
            tmp = re.split("-", cpulist)
            hyphens = range(int(tmp[0]), int(tmp[-1]) + 1)
        elif "^" in cpulist:
            tmp = re.split("^", cpulist)[-1]
            carets.append(int(tmp))
        else:
            try:
                others.append(int(cpulist))
                return others
            except ValueError:
                logging.error("The cpulist has to be an "
                              "integer. (%s)", cpulist)

        cpus_set = set(hyphens).union(set(commas)).difference(set(carets))

        return sorted(list(cpus_set))


def cpus_string_to_affinity_list(cpus_string, num_cpus):
    """
    Parse the cpus_string string to a affinity list.

    e.g
    host_cpu_count = 4
    0       -->     [y,-,-,-]
    0,1     -->     [y,y,-,-]
    0-2     -->     [y,y,y,-]
    0-2,^2  -->     [y,y,-,-]
    r       -->     [y,y,y,y]
    """
    # Check the input string.
    single_pattern = r"\d+"
    between_pattern = r"\d+-\d+"
    exclude_pattern = r"\^\d+"
    sub_pattern = r"(%s)|(%s)|(%s)" % (exclude_pattern,
                                       single_pattern, between_pattern)
    pattern = r"^((%s),)*(%s)$" % (sub_pattern, sub_pattern)
    if not re.match(pattern, cpus_string):
        logging.debug("Cpus_string=%s is not a supported format for cpu_list."
                      % cpus_string)
    # Init a list for result.
    affinity = []
    for i in range(int(num_cpus)):
        affinity.append('-')
    # Letter 'r' means all cpus.
    if cpus_string == "r":
        for i in range(len(affinity)):
            affinity[i] = "y"
        return affinity
    # Split the string with ','.
    sub_cpus = cpus_string.split(",")
    # Parse each sub_cpus.
    for cpus in sub_cpus:
        if "-" in cpus:
            minmum = cpus.split("-")[0]
            maxmum = cpus.split("-")[-1]
            for i in range(int(minmum), int(maxmum) + 1):
                affinity[i] = "y"
        elif "^" in cpus:
            affinity[int(cpus.strip("^"))] = "-"
        else:
            affinity[int(cpus)] = "y"
    return affinity


def cpu_allowed_list_by_task(pid, tid):
    """
    Get the Cpus_allowed_list in status of task.
    """
    cmd = "cat /proc/%s/task/%s/status|grep Cpus_allowed_list:| awk '{print $2}'" % (pid, tid)
    result = utils.run(cmd, ignore_status=True)
    if result.exit_status:
        return None
    return result.stdout.strip()


def clean_up_snapshots(vm_name, snapshot_list=[]):
    """
    Do recovery after snapshot

    :param vm_name: Name of domain
    :param snapshot_list: The list of snapshot name you want to remove
    """
    if not snapshot_list:
        # Get all snapshot names from virsh snapshot-list
        snapshot_list = virsh.snapshot_list(vm_name)

        # Get snapshot disk path
        for snap_name in snapshot_list:
            # Delete useless disk snapshot file if exists
            snap_xml = virsh.snapshot_dumpxml(vm_name,
                                              snap_name).stdout.strip()
            xtf_xml = xml_utils.XMLTreeFile(snap_xml)
            disks_path = xtf_xml.findall('disks/disk/source')
            for disk in disks_path:
                os.system('rm -f %s' % disk.get('file'))
            # Delete snapshots of vm
            virsh.snapshot_delete(vm_name, snap_name)
    else:
        # Get snapshot disk path from domain xml because
        # there is no snapshot info with the name
        dom_xml = vm_xml.VMXML.new_from_dumpxml(vm_name).xmltreefile
        disk_path = dom_xml.find('devices/disk/source').get('file')
        for name in snapshot_list:
            snap_disk_path = disk_path.split(".")[0] + "." + name
            os.system('rm -f %s' % snap_disk_path)


def get_all_cells():
    """
    Use virsh freecell --all to get all cells on host

    ::

        # virsh freecell --all
            0:     124200 KiB
            1:    1059868 KiB
        --------------------
        Total:    1184068 KiB

    That would return a dict like:

    ::

        cell_dict = {"0":"124200 KiB", "1":"1059868 KiB", "Total":"1184068 KiB"}

    :return: cell_dict
    """
    fc_result = virsh.freecell(options="--all", ignore_status=True)
    if fc_result.exit_status:
        if fc_result.stderr.count("NUMA not supported"):
            raise error.TestNAError(fc_result.stderr.strip())
        else:
            raise error.TestFail(fc_result.stderr.strip())
    output = fc_result.stdout.strip()
    cell_list = output.splitlines()
    # remove "------------" line
    del cell_list[-2]
    cell_dict = {}
    for cell_line in cell_list:
        cell_info = cell_line.split(":")
        cell_num = cell_info[0].strip()
        cell_mem = cell_info[-1].strip()
        cell_dict[cell_num] = cell_mem
    return cell_dict


def check_blockjob(vm_name, target, check_point="none", value="0"):
    """
    Run blookjob command to check block job progress, bandwidth, ect.

    :param vm_name: Domain name
    :param target: Domian disk target dev
    :param check_point: Job progrss, bandwidth or none(no job)
    :param value: Value of progress, bandwidth or 0(no job)
    :return: Boolean value, true for pass, false for fail
    """
    if check_point not in ["progress", "bandwidth", "none"]:
        logging.error("Check point must be: progress, bandwidth or none")
        return False

    try:
        cmd_result = virsh.blockjob(vm_name, target, "--info", ignore_status=True)
        output = cmd_result.stdout.strip()
        err = cmd_result.stderr.strip()
        status = cmd_result.exit_status
    except:
        raise error.TestFail("Error occur when running blockjob command.")
    if status == 0:
        # libvirt print job progress to stderr
        if not len(err):
            logging.debug("No block job find")
            if check_point == "none":
                return True
        else:
            if check_point == "none":
                logging.error("Expect no job but find block job:\n%s", err)
            elif check_point == "progress":
                progress = value + " %"
                if re.search(progress, err):
                    return True
            elif check_point == "bandwidth":
                bandwidth = value + " MiB/s"
                if bandwidth == output.split(':')[1].strip():
                    logging.debug("Bandwidth is equal to %s", bandwidth)
                    return True
                else:
                    logging.error("Bandwidth is not equal to %s", bandwidth)
    else:
        logging.error("Run blockjob command fail")
    return False


def setup_or_cleanup_nfs(is_setup, mount_dir="nfs-mount", is_mount=False,
                         export_options="rw,no_root_squash",
                         mount_options="rw",
                         export_dir="nfs-export",
                         restore_selinux=""):
    """
    Set SElinux to "permissive" and Set up nfs service on localhost.
    Or clean up nfs service on localhost and restore SElinux.

    Note: SElinux status must be backed up and restored after use.
    Example:

    # Setup NFS.
    res = setup_or_cleanup_nfs(is_setup=True)
    # Backup SELinux status.
    selinux_bak = res["selinux_status_bak"]

    # Do something.
    ...

    # Cleanup NFS and restore NFS.
    res = setup_or_cleanup_nfs(is_setup=False, restore_selinux=selinux_bak)

    :param is_setup: Boolean value, true for setup, false for cleanup
    :param mount_dir: NFS mount dir. This can be an absolute path on the
                      host or a relative path origin from libvirt tmp dir.
                      Default to "nfs-mount".
    :param is_mount: Boolean value, Whether the target NFS should be mounted.
    :param export_options: Options for nfs dir. Default to "nfs-export".
    :param mount_options: Options for mounting nfs dir. Default to "rw".
    :param export_dir: NFS export dir. This can be an absolute path on the
                      host or a relative path origin from libvirt tmp dir.
                      Default to "nfs-export".
    :return: A dict contains export and mount result parameters:
             export_dir: Absolute directory of exported local NFS file system.
             mount_dir: Absolute directory NFS file system mounted on.
             selinux_status_bak: SELinux status before set
    """
    result = {}

    tmpdir = data_dir.get_tmp_dir()
    if not os.path.isabs(export_dir):
        export_dir = os.path.join(tmpdir, export_dir)
    if not os.path.isabs(mount_dir):
        mount_dir = os.path.join(tmpdir, mount_dir)
    result["export_dir"] = export_dir
    result["mount_dir"] = mount_dir
    result["selinux_status_bak"] = utils_selinux.get_status()

    nfs_params = {"nfs_mount_dir": mount_dir, "nfs_mount_options": mount_options,
                  "nfs_mount_src": export_dir, "setup_local_nfs": "yes",
                  "export_options": export_options}
    _nfs = nfs.Nfs(nfs_params)

    if is_setup:
        # Set selinux to permissive that the file in nfs
        # can be used freely
        if utils_selinux.is_enforcing():
            utils_selinux.set_status("permissive")

        _nfs.setup()
        if not is_mount:
            _nfs.umount()
            del result["mount_dir"]
    else:
        if restore_selinux:
            utils_selinux.set_status(restore_selinux)
        _nfs.unexportfs_in_clean = True
        _nfs.cleanup()
    return result


def setup_or_cleanup_iscsi(is_setup, is_login=True,
                           emulated_image="emulated_iscsi", image_size="1G",
                           chap_user="", chap_passwd=""):
    """
    Set up(and login iscsi target) or clean up iscsi service on localhost.

    :param is_setup: Boolean value, true for setup, false for cleanup
    :param is_login: Boolean value, true for login, false for not login
    :param emulated_image: name of iscsi device
    :param image_size: emulated image's size
    :param chap_user: CHAP authentication username
    :param chap_passwd: CHAP authentication password
    :return: iscsi device name or iscsi target
    """
    try:
        utils_misc.find_command("tgtadm")
        utils_misc.find_command("iscsiadm")
    except ValueError:
        raise error.TestNAError("Missing command 'tgtadm' and/or 'iscsiadm'.")

    tmpdir = os.path.join(data_dir.get_root_dir(), 'tmp')
    emulated_path = os.path.join(tmpdir, emulated_image)
    emulated_target = "iqn.2001-01.com.virttest:%s.target" % emulated_image
    iscsi_params = {"emulated_image": emulated_path, "target": emulated_target,
                    "image_size": image_size, "iscsi_thread_id": "virt",
                    "chap_user": chap_user, "chap_passwd": chap_passwd}
    _iscsi = iscsi.Iscsi(iscsi_params)
    if is_setup:
        _iscsi.export_target()
        if is_login:
            _iscsi.login()
            # The device doesn't necessarily appear instantaneously, so give
            # about 5 seconds for it to appear before giving up
            iscsi_device = utils_misc.wait_for(_iscsi.get_device_name, 5, 0, 1,
                                               "Searching iscsi device name.")
            if iscsi_device:
                logging.debug("iscsi device: %s", iscsi_device)
                return iscsi_device
            if not iscsi_device:
                logging.error("Not find iscsi device.")
            # Cleanup and return "" - caller needs to handle that
            # _iscsi.export_target() will have set the emulated_id and
            # export_flag already on success...
            _iscsi.cleanup()
            utils.run("rm -f %s" % emulated_path)
        else:
            return emulated_target
    else:
        _iscsi.export_flag = True
        _iscsi.emulated_id = _iscsi.get_target_id()
        _iscsi.cleanup()
        utils.run("rm -f %s" % emulated_path)
    return ""


def get_host_ipv4_addr():
    """
    Get host ipv4 addr
    """
    if_up = utils_net.get_net_if(state="UP")
    for i in if_up:
        ipv4_value = utils_net.get_net_if_addrs(i)["ipv4"]
        logging.debug("ipv4_value is %s", ipv4_value)
        if ipv4_value != []:
            ip_addr = ipv4_value[0]
            break
    if ip_addr is not None:
        logging.info("ipv4 address is %s", ip_addr)
    else:
        raise error.TestFail("Fail to get ip address")
    return ip_addr


def setup_or_cleanup_gluster(is_setup, vol_name, brick_path="", pool_name="",
                             file_path="/etc/glusterfs/glusterd.vol"):
    """
    Set up or clean up glusterfs environment on localhost
    :param is_setup: Boolean value, true for setup, false for cleanup
    :param vol_name: gluster created volume name
    :param brick_path: Dir for create glusterfs
    :return: ip_addr or nothing
    """
    try:
        utils_misc.find_command("gluster")
    except ValueError:
        raise error.TestError("Missing command 'gluster'")
    if not brick_path:
        tmpdir = os.path.join(data_dir.get_root_dir(), 'tmp')
        brick_path = os.path.join(tmpdir, pool_name)
    if is_setup:
        ip_addr = get_host_ipv4_addr()
        gluster.add_rpc_insecure(file_path)
        gluster.glusterd_start()
        logging.debug("finish start gluster")
        gluster.gluster_vol_create(vol_name, ip_addr, brick_path, force=True)
        gluster.gluster_allow_insecure(vol_name)
        logging.debug("finish vol create in gluster")
        return ip_addr
    else:
        gluster.gluster_vol_stop(vol_name, True)
        gluster.gluster_vol_delete(vol_name)
        gluster.gluster_brick_delete(brick_path)
        return ""


def define_pool(pool_name, pool_type, pool_target, cleanup_flag, **kwargs):
    """
    To define a given type pool(Support types: 'dir', 'netfs', logical',
    iscsi', 'gluster', 'disk' and 'fs').

    :param pool_name: Name of the pool
    :param pool_type: Type of the pool
    :param pool_target: Target for underlying storage
    :param cleanup_flag: A list contains 3 booleans and 1 string stands for
                         need_cleanup_nfs, need_cleanup_iscsi,
                         need_cleanup_logical, selinux_bak and
                         need_cleanup_gluster
    :param kwargs: key words for sepcial pool define. eg, glusterfs pool
                         source path and source name, etc
    """

    extra = ""
    vg_name = pool_name
    cleanup_nfs = False
    cleanup_iscsi = False
    cleanup_logical = False
    selinux_bak = ""
    cleanup_gluster = False
    if not os.path.exists(pool_target) and pool_type != "gluster":
        os.mkdir(pool_target)
    if pool_type == "dir":
        pass
    elif pool_type == "netfs":
        # Set up NFS server without mount
        res = setup_or_cleanup_nfs(True, pool_target, False)
        nfs_path = res["export_dir"]
        selinux_bak = res["selinux_status_bak"]
        cleanup_nfs = True
        extra = "--source-host %s --source-path %s" % ('localhost',
                                                       nfs_path)
    elif pool_type == "logical":
        # Create vg by using iscsi device
        lv_utils.vg_create(vg_name, setup_or_cleanup_iscsi(True))
        cleanup_iscsi = True
        cleanup_logical = True
        extra = "--source-name %s" % vg_name
    elif pool_type == "iscsi":
        # Set up iscsi target without login
        iscsi_target = setup_or_cleanup_iscsi(True, False)
        cleanup_iscsi = True
        extra = "--source-host %s  --source-dev %s" % ('localhost',
                                                       iscsi_target)
    elif pool_type == "disk":
        # Set up iscsi target and login
        device_name = setup_or_cleanup_iscsi(True)
        cleanup_iscsi = True
        # Create a partition to make sure disk pool can start
        cmd = "parted -s %s mklabel msdos" % device_name
        utils.run(cmd)
        cmd = "parted -s %s mkpart primary ext4 0 100" % device_name
        utils.run(cmd)
        extra = "--source-dev %s" % device_name
    elif pool_type == "fs":
        # Set up iscsi target and login
        device_name = setup_or_cleanup_iscsi(True)
        cleanup_iscsi = True
        # Format disk to make sure fs pool can start
        cmd = "mkfs.ext4 -F %s" % device_name
        utils.run(cmd)
        extra = "--source-dev %s" % device_name
    elif pool_type == "gluster":
        gluster_source_path = kwargs.get('gluster_source_path')
        gluster_source_name = kwargs.get('gluster_source_name')
        gluster_file_name = kwargs.get('gluster_file_name')
        gluster_file_type = kwargs.get('gluster_file_type')
        gluster_file_size = kwargs.get('gluster_file_size')
        gluster_vol_number = kwargs.get('gluster_vol_number')

        # Prepare gluster service and create volume
        hostip = setup_or_cleanup_gluster(True, gluster_source_name,
                                          pool_name=pool_name)
        logging.debug("hostip is %s", hostip)
        # create image in gluster volume
        file_path = "gluster://%s/%s" % (hostip, gluster_source_name)
        for i in range(gluster_vol_number):
            file_name = "%s_%d" % (gluster_file_name, i)
            utils.run("qemu-img create -f %s %s/%s %s" %
                      (gluster_file_type, file_path, file_name,
                       gluster_file_size))
        cleanup_gluster = True
        extra = "--source-host %s --source-path %s --source-name %s" % \
                (hostip, gluster_source_path, gluster_source_name)
    elif pool_type in ["scsi", "mpath", "rbd", "sheepdog"]:
        raise error.TestNAError(
            "Pool type '%s' has not yet been supported in the test." %
            pool_type)
    else:
        raise error.TestFail("Invalid pool type: '%s'." % pool_type)
    # Mark the clean up flags
    cleanup_flag[0] = cleanup_nfs
    cleanup_flag[1] = cleanup_iscsi
    cleanup_flag[2] = cleanup_logical
    cleanup_flag[3] = selinux_bak
    cleanup_flag[4] = cleanup_gluster
    try:
        result = virsh.pool_define_as(pool_name, pool_type, pool_target, extra,
                                      ignore_status=True)
    except error.CmdError:
        logging.error("Define '%s' type pool fail.", pool_type)
    return result


def verify_virsh_console(session, user, passwd, timeout=10, debug=False):
    """
    Run commands in console session.
    """
    log = ""
    console_cmd = "cat /proc/cpuinfo"
    try:
        while True:
            match, text = session.read_until_last_line_matches(
                [r"[E|e]scape character is", r"login:",
                 r"[P|p]assword:", session.prompt],
                timeout, internal_timeout=1)

            if match == 0:
                if debug:
                    logging.debug("Got '^]', sending '\\n'")
                session.sendline()
            elif match == 1:
                if debug:
                    logging.debug("Got 'login:', sending '%s'", user)
                session.sendline(user)
            elif match == 2:
                if debug:
                    logging.debug("Got 'Password:', sending '%s'", passwd)
                session.sendline(passwd)
            elif match == 3:
                if debug:
                    logging.debug("Got Shell prompt -- logged in")
                break

        status, output = session.cmd_status_output(console_cmd)
        logging.info("output of command:\n%s", output)
        session.close()
    except (aexpect.ShellError,
            aexpect.ExpectError), detail:
        log = session.get_output()
        logging.error("Verify virsh console failed:\n%s\n%s", detail, log)
        session.close()
        return False

    if not re.search("processor", output):
        logging.error("Verify virsh console failed: Result does not match.")
        return False

    return True


def pci_label_from_address(address_dict, radix=10):
    """
    Generate a pci label from a dict of address.

    :param address_dict: A dict contains domain, bus, slot and function.
    :param radix: The radix of your data in address_dict.

    Example:

    ::

        address_dict = {'domain': '0x0000', 'bus': '0x08', 'slot': '0x10', 'function': '0x0'}
        radix = 16
        return = pci_0000_08_10_0
    """
    if not set(['domain', 'bus', 'slot', 'function']).issubset(
            address_dict.keys()):
        raise error.TestError("Param %s does not contain keys of "
                              "['domain', 'bus', 'slot', 'function']." %
                              str(address_dict))
    domain = int(address_dict['domain'], radix)
    bus = int(address_dict['bus'], radix)
    slot = int(address_dict['slot'], radix)
    function = int(address_dict['function'], radix)
    pci_label = ("pci_%04x_%02x_%02x_%01x" % (domain, bus, slot, function))
    return pci_label


def mk_label(disk, label="msdos", session=None):
    """
    Set label for disk.
    """
    mklabel_cmd = "parted -s %s mklabel %s" % (disk, label)
    if session:
        session.cmd(mklabel_cmd)
    else:
        utils.run(mklabel_cmd)


def mk_part(disk, size="100M", session=None):
    """
    Create a partition for disk
    """
    mklabel_cmd = "parted -s %s mklabel msdos" % disk
    mkpart_cmd = "parted -s %s mkpart primary ext4 0 %s" % (disk, size)
    if session:
        session.cmd(mklabel_cmd)
        session.cmd(mkpart_cmd)
    else:
        utils.run(mklabel_cmd)
        utils.run(mkpart_cmd)


def mkfs(partition, fs_type, options="", session=None):
    """
    Make a file system on the partition
    """
    mkfs_cmd = "mkfs.%s -F %s %s" % (fs_type, partition, options)
    if session:
        session.cmd(mkfs_cmd)
    else:
        utils.run(mkfs_cmd)


def get_parts_list(session=None):
    """
    Get all partition lists.
    """
    parts_cmd = "cat /proc/partitions"
    if session:
        _, parts_out = session.cmd_status_output(parts_cmd)
    else:
        parts_out = utils.run(parts_cmd).stdout
    parts = []
    if parts_out:
        for line in parts_out.rsplit("\n"):
            if line.startswith("major") or line == "":
                continue
            parts_line = line.rsplit()
            if len(parts_line) == 4:
                parts.append(parts_line[3])
    logging.debug("Find parts: %s" % parts)
    return parts


def check_actived_pool(pool_name):
    """
    Check if pool_name exist in active pool list
    """
    sp = libvirt_storage.StoragePool()
    if not sp.pool_exists(pool_name):
        raise error.TestFail("Can't find pool %s" % pool_name)
    if not sp.is_pool_active(pool_name):
        raise error.TestFail("Pool %s is not active." % pool_name)
    logging.debug("Find active pool %s", pool_name)
    return True


class PoolVolumeTest(object):

    """Test class for storage pool or volume"""

    def __init__(self, test, params):
        self.tmpdir = test.tmpdir
        self.params = params
        self.selinux_bak = ""

    def cleanup_pool(self, pool_name, pool_type, pool_target, emulated_image,
                     source_name=None):
        """
        Delete vols, destroy the created pool and restore the env
        """
        sp = libvirt_storage.StoragePool()
        try:
            if sp.pool_exists(pool_name):
                pv = libvirt_storage.PoolVolume(pool_name)
                if pool_type in ["dir", "netfs", "logical", "disk"]:
                    vols = pv.list_volumes()
                    for vol in vols:
                        # Ignore failed deletion here for deleting pool
                        pv.delete_volume(vol)
                if not sp.delete_pool(pool_name):
                    raise error.TestFail("Delete pool %s failed" % pool_name)
        finally:
            source_format = self.params.get("source_format")
            if pool_type == "netfs" and source_format != 'glusterfs':
                nfs_server_dir = self.params.get("nfs_server_dir", "nfs-server")
                nfs_path = os.path.join(self.tmpdir, nfs_server_dir)
                setup_or_cleanup_nfs(is_setup=False, export_dir=nfs_path,
                                     restore_selinux=self.selinux_bak)
                if os.path.exists(nfs_path):
                    shutil.rmtree(nfs_path)
            if pool_type == "logical":
                cmd = "pvs |grep vg_logical|awk '{print $1}'"
                pv = utils.system_output(cmd)
                # Cleanup logical volume anyway
                utils.run("vgremove -f vg_logical", ignore_status=True)
                utils.run("pvremove %s" % pv, ignore_status=True)
            # These types used iscsi device
            if pool_type in ["logical", "iscsi", "fs", "disk", "scsi"]:
                setup_or_cleanup_iscsi(is_setup=False,
                                       emulated_image=emulated_image)
                if pool_type == "scsi":
                    scsi_xml_file = self.params.get("scsi_xml_file")
                    if not os.path.exists(scsi_xml_file):
                        scsi_xml_file = os.path.join(self.tmpdir, scsi_xml_file)
                    if os.path.exists(scsi_xml_file):
                        os.remove(scsi_xml_file)
            if pool_type in ["dir", "fs", "netfs"]:
                pool_target = os.path.join(self.tmpdir, pool_target)
                if os.path.exists(pool_target):
                    shutil.rmtree(pool_target)
            if pool_type == "gluster" or source_format == 'glusterfs':
                setup_or_cleanup_gluster(False, source_name)

    def pre_pool(self, pool_name, pool_type, pool_target, emulated_image,
                 image_size="100M", pre_disk_vol=[], source_name=None,
                 source_path=None, export_options="rw,async,no_root_squash"):
        """
        Preapare the specific type pool

        Note:
            1. For scsi type pool, it only could be created from xml file
            2. Other type pools can be created by pool_creat_as function
            3. Disk pool will not allow to create volume with virsh commands
               So we can prepare it before pool created

        :param pool_name: created pool name
        :param pool_type: dir, disk, logical, fs, netfs or else
        :param pool_target: target of storage pool
        :param emulated_image: use an image file to simulate a scsi disk
                               it could be used for disk, logical pool
        :param image_size: the size for emulated image
        :param pre_disk_vol: a list include partition size to be created
                             no more than 4 partition because msdos label
        """
        extra = ""
        if pool_type == "dir":
            logging.info("Pool path:%s", self.tmpdir)
            pool_target = os.path.join(self.tmpdir, pool_target)
            if not os.path.exists(pool_target):
                os.mkdir(pool_target)
        elif pool_type == "disk":
            device_name = setup_or_cleanup_iscsi(is_setup=True,
                                                 emulated_image=emulated_image,
                                                 image_size=image_size)
            # If pre_vol is None, disk pool will have no volume
            if type(pre_disk_vol) == list and len(pre_disk_vol):
                for vol in pre_disk_vol:
                    mk_part(device_name, vol)
            else:
                mk_label(device_name, "gpt")
            extra = " --source-dev %s" % device_name
        elif pool_type == "fs":
            device_name = setup_or_cleanup_iscsi(is_setup=True,
                                                 emulated_image=emulated_image,
                                                 image_size=image_size)
            cmd = "mkfs.ext4 -F %s" % device_name
            pool_target = os.path.join(self.tmpdir, pool_target)
            if not os.path.exists(pool_target):
                os.mkdir(pool_target)
            extra = " --source-dev %s" % device_name
            utils.run(cmd)
        elif pool_type == "logical":
            logical_device = setup_or_cleanup_iscsi(is_setup=True,
                                                    emulated_image=emulated_image,
                                                    image_size=image_size)
            cmd_pv = "pvcreate %s" % logical_device
            vg_name = "vg_%s" % pool_type
            cmd_vg = "vgcreate %s %s" % (vg_name, logical_device)
            extra = "--source-name %s" % vg_name
            utils.run(cmd_pv)
            utils.run(cmd_vg)
            # Create a small volume for verification
            # And VG path will not exist if no any volume in.(bug?)
            cmd_lv = "lvcreate --name default_lv --size 1M %s" % vg_name
            utils.run(cmd_lv)
        elif pool_type == "netfs":
            pool_target = os.path.join(self.tmpdir, pool_target)
            if not os.path.exists(pool_target):
                os.mkdir(pool_target)
            source_format = self.params.get("source_format")
            if source_format == 'glusterfs':
                hostip = setup_or_cleanup_gluster(True, source_name,
                                                  pool_name=pool_name)
                logging.debug("hostip is %s", hostip)
                extra = "--source-host %s --source-path %s" % (hostip,
                                                               source_name)
                extra += " --source-format %s" % source_format
                utils.system("setsebool virt_use_fusefs on")
            else:
                nfs_server_dir = self.params.get("nfs_server_dir", "nfs-server")
                nfs_path = os.path.join(self.tmpdir, nfs_server_dir)
                if not os.path.exists(nfs_path):
                    os.mkdir(nfs_path)
                res = setup_or_cleanup_nfs(is_setup=True,
                                           export_options=export_options,
                                           export_dir=nfs_path)
                self.selinux_bak = res["selinux_status_bak"]
                source_host = self.params.get("source_host", "localhost")
                extra = "--source-host %s --source-path %s" % (source_host,
                                                               nfs_path)
        elif pool_type == "iscsi":
            setup_or_cleanup_iscsi(is_setup=True,
                                   emulated_image=emulated_image,
                                   image_size=image_size)
            # Verify if expected iscsi device has been set
            iscsi_sessions = iscsi.iscsi_get_sessions()
            iscsi_device = ()
            for iscsi_node in iscsi_sessions:
                if iscsi_node[1].count(emulated_image):
                    # Remove port for pool operations
                    ip_addr = iscsi_node[0].split(":3260")[0]
                    iscsi_device = (ip_addr, iscsi_node[1])
                    break
            if iscsi_device == ():
                raise error.TestFail("No matched iscsi device.")
            if "::" in iscsi_device[0]:
                iscsi_device = ('localhost', iscsi_device[1])
            extra = " --source-host %s  --source-dev %s" % iscsi_device
        elif pool_type == "scsi":
            scsi_xml_file = self.params.get("scsi_xml_file")
            if not os.path.exists(scsi_xml_file):
                scsi_xml_file = os.path.join(self.tmpdir, scsi_xml_file)
                logical_device = setup_or_cleanup_iscsi(is_setup=True,
                                                        emulated_image=emulated_image,
                                                        image_size=image_size)
                cmd = ("iscsiadm -m session -P 3 |grep -B3 %s| grep Host|awk "
                       "'{print $3}'" % logical_device.split('/')[2])
                scsi_host = utils.system_output(cmd)
                scsi_xml = """
<pool type='scsi'>
  <name>%s</name>
   <source>
    <adapter type='scsi_host' name='host%s'/>
  </source>
  <target>
    <path>/dev/disk/by-path</path>
  </target>
</pool>
""" % (pool_name, scsi_host)
                logging.debug("Prepare the scsi pool xml: %s", scsi_xml)
                xml_object = open(scsi_xml_file, 'w')
                xml_object.write(scsi_xml)
                xml_object.close()
        elif pool_type == "gluster":
            # Prepare gluster service and create volume
            hostip = setup_or_cleanup_gluster(True, source_name,
                                              pool_name=pool_name)
            logging.debug("hostip is %s", hostip)
            extra = "--source-host %s --source-path %s --source-name %s" % \
                    (hostip, source_path, source_name)

        # Create pool
        if pool_type == "scsi":
            re_v = virsh.pool_create(scsi_xml_file)
        else:
            re_v = virsh.pool_create_as(pool_name, pool_type,
                                        pool_target, extra, debug=True)

        if not re_v:
            raise error.TestFail("Create pool failed.")

        ret = virsh.pool_dumpxml(pool_name)
        logging.debug("The created pool xml is: %s" % ret)

        # Check the created pool
        check_actived_pool(pool_name)

    def pre_vol(self, vol_name, vol_format, capacity, allocation, pool_name):
        """
        Preapare the specific type volume in pool
        """
        pv = libvirt_storage.PoolVolume(pool_name)
        if not pv.create_volume(vol_name, capacity, allocation, vol_format):
            raise error.TestFail("Prepare volume failed.")
        if not pv.volume_exists(vol_name):
            raise error.TestFail("Can't find volume: %s", vol_name)


##########Migration Relative functions##############
class MigrationTest(object):

    """Class for migration tests"""

    def __init__(self):
        # To get result in thread, using member parameters
        # Result of virsh migrate command
        # True means command executed successfully
        self.RET_MIGRATION = True
        # A lock for threads
        self.RET_LOCK = threading.RLock()
        # The time spent when migrating vms
        # format: vm_name -> time(seconds)
        self.mig_time = {}

    def thread_func_migration(self, vm, desturi, options=None):
        """
        Thread for virsh migrate command.

        :param vm: A libvirt vm instance(local or remote).
        :param desturi: remote host uri.
        """
        # Migrate the domain.
        try:
            if options is None:
                options = "--live --timeout=60"
            stime = int(time.time())
            vm.migrate(desturi, option=options, ignore_status=False,
                       debug=True)
            etime = int(time.time())
            self.mig_time[vm.name] = etime - stime
        except error.CmdError, detail:
            logging.error("Migration to %s failed:\n%s", desturi, detail)
            self.RET_LOCK.acquire()
            self.RET_MIGRATION = False
            self.RET_LOCK.release()

    def do_migration(self, vms, srcuri, desturi, migration_type, options=None,
                     thread_timeout=60):
        """
        Migrate vms.

        :param vms: migrated vms.
        :param srcuri: local uri, used when migrate vm from remote to local
        :param descuri: remote uri, used when migrate vm from local to remote
        :param migration_type: do orderly for simultaneous migration
        """
        if migration_type == "orderly":
            for vm in vms:
                migration_thread = threading.Thread(target=self.thread_func_migration,
                                                    args=(vm, desturi, options))
                migration_thread.start()
                migration_thread.join(thread_timeout)
                if migration_thread.isAlive():
                    logging.error("Migrate %s timeout.", migration_thread)
                    self.RET_LOCK.acquire()
                    self.RET_MIGRATION = False
                    self.RET_LOCK.release()
        elif migration_type == "cross":
            # Migrate a vm to remote first,
            # then migrate another to remote with the first vm back
            vm_remote = vms.pop()
            self.thread_func_migration(vm_remote, desturi)
            for vm in vms:
                thread1 = threading.Thread(target=self.thread_func_migration,
                                           args=(vm_remote, srcuri, options))
                thread2 = threading.Thread(target=self.thread_func_migration,
                                           args=(vm, desturi, options))
                thread1.start()
                thread2.start()
                thread1.join(thread_timeout)
                thread2.join(thread_timeout)
                vm_remote = vm
                if thread1.isAlive() or thread1.isAlive():
                    logging.error("Cross migrate timeout.")
                    self.RET_LOCK.acquire()
                    self.RET_MIGRATION = False
                    self.RET_LOCK.release()
            # Add popped vm back to list
            vms.append(vm_remote)
        elif migration_type == "simultaneous":
            migration_threads = []
            for vm in vms:
                migration_threads.append(threading.Thread(
                                         target=self.thread_func_migration,
                                         args=(vm, desturi, options)))
            # let all migration going first
            for thread in migration_threads:
                thread.start()

            # listen threads until they end
            for thread in migration_threads:
                thread.join(thread_timeout)
                if thread.isAlive():
                    logging.error("Migrate %s timeout.", thread)
                    self.RET_LOCK.acquire()
                    self.RET_MIGRATION = False
                    self.RET_LOCK.release()

        if not self.RET_MIGRATION:
            raise error.TestFail()

    def cleanup_dest_vm(self, vm, srcuri, desturi):
        """
        Cleanup migrated vm on remote host.
        """
        vm.connect_uri = desturi
        if vm.exists():
            if vm.is_persistent():
                vm.undefine()
            if vm.is_alive():
                # If vm on remote host is unaccessible
                # graceful shutdown may cause confused
                vm.destroy(gracefully=False)
        # Set connect uri back to local uri
        vm.connect_uri = srcuri


def check_exit_status(result, expect_error=False):
    """
    Check the exit status of virsh commands.

    :param result: Virsh command result object
    :param expect_error: Boolean value, expect command success or fail
    """
    if not expect_error:
        if result.exit_status != 0:
            raise error.TestFail(result.stderr)
        else:
            logging.debug("Command output:\n%s", result.stdout.strip())
    elif expect_error and result.exit_status == 0:
        raise error.TestFail("Expect fail, but run successfully.")


def check_iface(iface_name, checkpoint, extra="", **dargs):
    """
    Check interface with specified checkpoint.

    :param iface_name: Interface name
    :param checkpoint: Check if interface exists, MAC address, IP address or
                       ping out. Support values: [exists, mac, ip, ping]
    :param extra: Extra string for checking
    :return: Boolean value, true for pass, false for fail
    """
    support_check = ["exists", "mac", "ip", "ping"]
    iface = utils_net.Interface(name=iface_name)
    check_pass = False
    try:
        if checkpoint == "exists":
            # extra is iface-list option
            list_find, ifcfg_find = (False, False)
            # Check virsh list output
            result = virsh.iface_list(extra, ignore_status=True)
            check_exit_status(result, False)
            output = re.findall(r"(\S+)\ +(\S+)\ +(\S+|\s+)[\ +\n]",
                                str(result.stdout))
            if filter(lambda x: x[0] == iface_name, output[1:]):
                list_find = True
            logging.debug("Find '%s' in virsh iface-list output: %s",
                          iface_name, list_find)
            # Check network script
            iface_script = "/etc/sysconfig/network-scripts/ifcfg-" + iface_name
            ifcfg_find = os.path.exists(iface_script)
            logging.debug("Find '%s': %s", iface_script, ifcfg_find)
            check_pass = list_find and ifcfg_find
        elif checkpoint == "mac":
            # extra is the MAC address to compare
            iface_mac = iface.get_mac().lower()
            check_pass = iface_mac == extra
            logging.debug("MAC address of %s: %s", iface_name, iface_mac)
        elif checkpoint == "ip":
            # extra is the IP address to compare
            iface_ip = iface.get_ip()
            check_pass = iface_ip == extra
            logging.debug("IP address of %s: %s", iface_name, iface_ip)
        elif checkpoint == "ping":
            # extra is the ping destination
            count = dargs.get("count", 3)
            timeout = dargs.get("timeout", 5)
            ping_s, _ = ping(dest=extra, count=count, interface=iface_name,
                             timeout=timeout,)
            check_pass = ping_s == 0
        else:
            logging.debug("Support check points are: %s", support_check)
            logging.error("Unsupport check point: %s", checkpoint)
    except Exception, detail:
        raise error.TestFail("Interface check failed: %s" % detail)
    return check_pass


def create_hostdev_xml(pci_id, boot_order=0):
    """
    Create a hostdev configuration file.

    :param pci_id: such as "0000:03:04.0"
    """
    # Create attributes dict for device's address element
    device_domain = pci_id.split(':')[0]
    device_domain = "0x%s" % device_domain
    device_bus = pci_id.split(':')[1]
    device_bus = "0x%s" % device_bus
    device_slot = pci_id.split(':')[-1].split('.')[0]
    device_slot = "0x%s" % device_slot
    device_function = pci_id.split('.')[-1]
    device_function = "0x%s" % device_function

    hostdev_xml = hostdev.Hostdev()
    hostdev_xml.mode = "subsystem"
    hostdev_xml.managed = "yes"
    hostdev_xml.hostdev_type = "pci"
    if boot_order:
        hostdev_xml.boot_order = boot_order
    attrs = {'domain': device_domain, 'slot': device_slot,
             'bus': device_bus, 'function': device_function}
    hostdev_xml.source_address = hostdev_xml.new_source_address(**attrs)
    logging.debug("Hostdev XML:\n%s", str(hostdev_xml))
    return hostdev_xml.xml


def create_disk_xml(params):
    """
    Create a disk configuration file.
    """
    # Create attributes dict for disk's address element
    type_name = params.get("type_name", "file")
    target_dev = params.get("target_dev", "vdb")
    target_bus = params.get("target_bus", "virtio")
    diskxml = disk.Disk(type_name)
    diskxml.device = params.get("device_type", "disk")
    snapshot_attr = params.get('disk_snapshot_attr')
    if snapshot_attr:
        diskxml.snapshot = snapshot_attr
    source_attrs = {}
    source_host = []
    auth_attrs = {}
    driver_attrs = {}
    try:
        if type_name == "file":
            source_file = params.get("source_file", "")
            source_attrs = {'file': source_file}
        elif type_name == "block":
            source_file = params.get("source_file", "")
            source_attrs = {'dev': source_file}
        elif type_name == "dir":
            source_dir = params.get("source_dir", "")
            source_attrs = {'dir': source_dir}
        elif type_name == "volume":
            source_pool = params.get("source_pool")
            source_volume = params.get("source_volume")
            source_mode = params.get("source_mode", "")
            source_attrs = {'pool': source_pool, 'volume': source_volume,
                            'mode': source_mode}
        elif type_name == "network":
            source_protocol = params.get("source_protocol")
            source_name = params.get("source_name")
            source_host_name = params.get("source_host_name")
            source_host_port = params.get("source_host_port")
            transport = params.get("transport")
            source_attrs = {'protocol': source_protocol, 'name': source_name}
            source_host = [{'name': source_host_name, 'port': source_host_port}]
            if transport:
                source_host[0].update({'transport': transport})
        else:
            error.TestNAError("Unsupport disk type %s" % type_name)
        source_startupPolicy = params.get("source_startupPolicy")
        if source_startupPolicy:
            source_attrs['startupPolicy'] = source_startupPolicy
        diskxml.source = diskxml.new_disk_source(attrs=source_attrs,
                                                 hosts=source_host)
        auth_user = params.get("auth_user")
        secret_type = params.get("secret_type")
        secret_usage = params.get("secret_usage")
        if auth_user:
            auth_attrs['auth_user'] = auth_user
        if secret_type:
            auth_attrs['secret_type'] = secret_type
        if secret_usage:
            auth_attrs['secret_usage'] = secret_usage
        if auth_attrs:
            diskxml.auth = diskxml.new_auth(**auth_attrs)
        driver_name = params.get("driver_name", "qemu")
        driver_type = params.get("driver_type", "")
        driver_cache = params.get("driver_cache", "")
        driver_discard = params.get("driver_discard", "")
        if driver_name:
            driver_attrs['name'] = driver_name
        if driver_type:
            driver_attrs['type'] = driver_type
        if driver_cache:
            driver_attrs['cache'] = driver_cache
        if driver_discard:
            driver_attrs['discard'] = driver_discard
        if driver_attrs:
            diskxml.driver = driver_attrs
        diskxml.readonly = "yes" == params.get("readonly", "no")
        diskxml.share = "yes" == params.get("shareable", "no")
        diskxml.target = {'dev': target_dev, 'bus': target_bus}
    except Exception, detail:
        logging.error("Fail to create disk XML:\n%s", detail)
    logging.debug("Disk XML %s:\n%s", diskxml.xml, str(diskxml))

    # Wait for file completed
    def file_exists():
        if not utils.run("ls %s" % diskxml.xml,
                         ignore_status=True).exit_status:
            return True
    utils_misc.wait_for(file_exists, 5)

    return diskxml.xml


def set_domain_state(vm, vm_state):
    """
    Set domain state.

    :param vm: the vm object
    :param vm_state: the given vm state string "shut off", "running"
                     "paused", "halt" or "pm_suspend"
    """
    # reset domain state
    if vm.is_alive():
        vm.destroy(gracefully=False)
    if not vm_state == "shut off":
        vm.start()
        session = vm.wait_for_login()
    if vm_state == "paused":
        vm.pause()
    elif vm_state == "halt":
        try:
            session.cmd("halt")
        except (aexpect.ShellProcessTerminatedError, aexpect.ShellStatusError):
            # The halt command always gets these errors, but execution is OK,
            # skip these errors
            pass
    elif vm_state == "pm_suspend":
        # Execute "pm-suspend-hybrid" command directly will get Timeout error,
        # so here execute it in background, and wait for 3s manually
        if session.cmd_status("which pm-suspend-hybrid"):
            raise error.TestNAError("Cannot execute this test for domain"
                                    " doesn't have pm-suspend-hybrid command!")
        session.cmd("pm-suspend-hybrid &")
        time.sleep(3)


def set_guest_agent(vm):
    """
    Set domain xml with guest agent channel and install guest agent rpm
    in domain.

    :param vm: the vm object
    """
    # reset domain state
    if vm.is_alive():
        vm.destroy(gracefully=False)
    vmxml = vm_xml.VMXML.new_from_inactive_dumpxml(vm.name)
    logging.debug("Attempting to set guest agent channel")
    vmxml.set_agent_channel(vm.name)
    vm.start()
    session = vm.wait_for_login()
    # Check if qemu-ga already started automatically
    cmd = "rpm -q qemu-guest-agent || yum install -y qemu-guest-agent"
    stat_install = session.cmd_status(cmd, 300)
    if stat_install != 0:
        raise error.TestFail("Fail to install qemu-guest-agent, make "
                             "sure that you have usable repo in guest")

    # Check if qemu-ga already started
    stat_ps = session.cmd_status("ps aux |grep [q]emu-ga")
    if stat_ps != 0:
        session.cmd("qemu-ga -d")
        # Check if the qemu-ga really started
        stat_ps = session.cmd_status("ps aux |grep [q]emu-ga")
        if stat_ps != 0:
            raise error.TestFail("Fail to run qemu-ga in guest")


def set_vm_disk(vm, params, tmp_dir=None):
    """
    Replace vm first disk with given type in domain xml, including file type
    (local, nfs), network type(gluster, iscsi), block type(use connected iscsi
    block disk).

    For all types, all following params are common and need be specified:

        disk_device: default to 'disk'
        disk_type: 'block' or 'network'
        disk_target: default to 'vda'
        disk_target_bus: default to 'virtio'
        disk_format: default to 'qcow2'
        disk_src_protocol: 'iscsi', 'gluster' or 'netfs'

    For 'gluster' network type, following params are gluster only and need be
    specified:

        vol_name: string
        pool_name: default to 'gluster-pool'
        transport: 'tcp', 'rdma' or '', default to ''

    For 'iscsi' network type, following params need be specified:

        image_size: default to "10G", 10G is raw size of jeos disk
        disk_src_host: default to "127.0.0.1"
        disk_src_port: default to "3260"

    For 'netfs' network type, following params need be specified:

        mnt_path_name: the mount dir name, default to "nfs-mount"
        export_options: nfs mount options, default to "rw,no_root_squash,fsid=0"

    For 'block' type, using connected iscsi block disk, following params need
    be specified:

        image_size: default to "10G", 10G is raw size of jeos disk

    :param vm: the vm object
    :param tmp_dir: string, dir path
    :param params: dict, dict include setup vm disk xml configurations
    """
    vmxml = vm_xml.VMXML.new_from_inactive_dumpxml(vm.name)
    logging.debug("original xml is: %s", vmxml.xmltreefile)
    disk_device = params.get("disk_device", "disk")
    disk_snapshot_attr = params.get("disk_snapshot_attr")
    disk_type = params.get("disk_type")
    disk_target = params.get("disk_target", 'vda')
    disk_target_bus = params.get("disk_target_bus", "virtio")
    disk_src_protocol = params.get("disk_source_protocol")
    disk_src_host = params.get("disk_source_host", "127.0.0.1")
    disk_src_port = params.get("disk_source_port", "3260")
    image_size = params.get("image_size", "10G")
    disk_format = params.get("disk_format", "qcow2")
    mnt_path_name = params.get("mnt_path_name", "nfs-mount")
    exp_opt = params.get("export_options", "rw,no_root_squash,fsid=0")
    first_disk = vm.get_first_disk_devices()
    blk_source = first_disk['source']
    disk_xml = vmxml.devices.by_device_tag('disk')[0]
    src_disk_format = disk_xml.xmltreefile.find('driver').get('type')
    disk_params = {'device_type': disk_device,
                   'disk_snapshot_attr': disk_snapshot_attr,
                   'type_name': disk_type,
                   'target_dev': disk_target,
                   'target_bus': disk_target_bus,
                   'driver_type': disk_format,
                   'driver_cache': 'none'}

    if not tmp_dir:
        tmp_dir = data_dir.get_tmp_dir()

    # gluster only params
    vol_name = params.get("vol_name")
    pool_name = params.get("pool_name", "gluster-pool")
    transport = params.get("transport", "")
    brick_path = os.path.join(tmp_dir, pool_name)
    image_convert = "yes" == params.get("image_convert", 'yes')

    if vm.is_alive():
        vm.destroy(gracefully=False)
    # Replace domain disk with iscsi, gluster, block or netfs disk
    if disk_src_protocol == 'iscsi':
        if disk_type == 'block':
            is_login = True
        elif disk_type == 'network':
            is_login = False
        else:
            raise error.TestFail("Disk type '%s' not expected, only disk "
                                 "type 'block' or 'network' work with "
                                 "'iscsi'" % disk_type)

        # Setup iscsi target
        emu_n = "emulated_iscsi"
        iscsi_target = setup_or_cleanup_iscsi(is_setup=True,
                                              is_login=is_login,
                                              image_size=image_size,
                                              emulated_image=emu_n)

        # Copy first disk to emulated backing store path
        emulated_path = os.path.join(tmp_dir, emu_n)
        cmd = "qemu-img convert -f %s -O raw %s %s" % (src_disk_format,
                                                       blk_source,
                                                       emulated_path)
        utils.run(cmd, ignore_status=False)

        if disk_type == 'block':
            disk_params_src = {'source_file': iscsi_target}
        else:
            disk_params_src = {'source_protocol': disk_src_protocol,
                               'source_name': iscsi_target + "/1",
                               'source_host_name': disk_src_host,
                               'source_host_port': disk_src_port}
    elif disk_src_protocol == 'gluster':
        # Setup gluster.
        host_ip = setup_or_cleanup_gluster(True, vol_name,
                                           brick_path, pool_name)
        logging.debug("host ip: %s " % host_ip)
        dist_img = "gluster.%s" % disk_format

        if image_convert:
            # Convert first disk to gluster disk path
            disk_cmd = ("qemu-img convert -f %s -O %s %s /mnt/%s" %
                        (src_disk_format, disk_format, blk_source, dist_img))
        else:
            # create another disk without convert
            disk_cmd = "qemu-img create -f %s /mnt/%s 10M" % (src_disk_format,
                                                              dist_img)

        # Mount the gluster disk and create the image.
        utils.run("mount -t glusterfs %s:%s /mnt; %s; umount /mnt"
                  % (host_ip, vol_name, disk_cmd))

        disk_params_src = {'source_protocol': disk_src_protocol,
                           'source_name': "%s/%s" % (vol_name, dist_img),
                           'source_host_name': host_ip,
                           'source_host_port': "24007"}
        if transport:
            disk_params_src.update({"transport": transport})
    elif disk_src_protocol == 'netfs':
        # Setup nfs
        res = setup_or_cleanup_nfs(True, mnt_path_name,
                                   is_mount=True,
                                   export_options=exp_opt)
        exp_path = res["export_dir"]
        mnt_path = res["mount_dir"]
        params["selinux_status_bak"] = res["selinux_status_bak"]
        dist_img = "nfs-img"

        # Convert first disk to gluster disk path
        disk_cmd = ("qemu-img convert -f %s -O %s %s %s/%s" %
                    (src_disk_format, disk_format,
                     blk_source, exp_path, dist_img))
        utils.run(disk_cmd, ignore_status=False)

        src_file_path = "%s/%s" % (mnt_path, dist_img)
        disk_params_src = {'source_file': src_file_path}
    else:
        raise error.TestNAError("Disk source protocol %s not supported in "
                                "current test" % disk_src_protocol)

    # Delete disk elements
    disks = vmxml.get_devices(device_type="disk")
    for disk_ in disks:
        if disk_.target['dev'] == disk_target:
            vmxml.del_device(disk_)

    # New disk xml
    new_disk = disk.Disk(type_name=disk_type)
    new_disk.new_disk_source(attrs={'file': blk_source})
    disk_params.update(disk_params_src)
    disk_xml = create_disk_xml(disk_params)
    new_disk.xml = disk_xml
    # Add new disk xml and redefine vm
    vmxml.add_device(new_disk)
    logging.debug("The vm xml now is: %s" % vmxml.xmltreefile)
    vmxml.sync()
    vm.start()


def attach_additional_device(vm_name, targetdev, disk_path, params, config=True):
    """
    Create a disk with disksize, then attach it to given vm.

    :param vm_name: Libvirt VM name.
    :param disk_path: path of attached disk
    :param targetdev: target of disk device
    :param params: dict include necessary configurations of device
    """
    logging.info("Attaching disk...")

    # Update params for source file
    params['source_file'] = disk_path
    params['target_dev'] = targetdev

    # Create a file of device
    xmlfile = create_disk_xml(params)

    # To confirm attached device do not exist.
    if config:
        extra = "--config"
    else:
        extra = ""
    virsh.detach_disk(vm_name, targetdev, extra=extra)

    return virsh.attach_device(domain_opt=vm_name, file_opt=xmlfile,
                               flagstr=extra, debug=True)


def device_exists(vm, target_dev):
    """
    Check if given target device exists on vm.
    """
    targets = vm.get_blk_devices().keys()
    if target_dev in targets:
        return True
    return False


def create_local_disk(disk_type, path=None,
                      size="10", disk_format="raw",
                      vgname=None, lvname=None):
    if disk_type != "lvm" and path is None:
        raise error.TestError("Path is needed for creating local disk")
    if path:
        utils.run("mkdir -p %s" % os.path.dirname(path))
    try:
        size = str(float(size)) + "G"
    except ValueError:
        pass
    cmd = ""
    if disk_type == "file":
        cmd = "qemu-img create -f %s %s %s" % (disk_format, path, size)
    elif disk_type == "floppy":
        cmd = "dd if=/dev/zero of=%s count=1024 bs=1024" % path
    elif disk_type == "iso":
        cmd = "mkisofs -o %s /root/*.*" % path
    elif disk_type == "lvm":
        if vgname is None or lvname is None:
            raise error.TestError("Both VG name and LV name are needed")
        lv_utils.lv_create(vgname, lvname, size)
        path = "/dev/%s/%s" % (vgname, lvname)
    else:
        raise error.TestError("Unknown disk type %s" % disk_type)
    if cmd:
        utils.run(cmd, ignore_status=True)
    return path


def delete_local_disk(disk_type, path=None,
                      vgname=None, lvname=None):
    if disk_type in ["file", "floppy", "iso"]:
        if path is None:
            raise error.TestError("Path is needed for deleting local disk")
        else:
            cmd = "rm -f %s" % path
            utils.run(cmd, ignore_status=True)
    elif disk_type == "lvm":
        if vgname is None or lvname is None:
            raise error.TestError("Both VG name and LV name needed")
        lv_utils.lv_remove(vgname, lvname)
    else:
        raise error.TestError("Unknown disk type %s" % disk_type)


def create_scsi_disk(scsi_option, scsi_size="2048"):
    """
    Get the scsi device created by scsi_debug kernel module

    :param scsi_option. The scsi_debug kernel module options.
    :return: scsi device if it is created successfully.
    """
    try:
        utils_misc.find_command("lsscsi")
    except ValueError:
        raise error.TestNAError("Missing command 'lsscsi'.")

    try:
        # Load scsi_debug kernel module.
        # Unload it first if it's already loaded.
        if utils.module_is_loaded("scsi_debug"):
            utils.unload_module("scsi_debug")
        utils.load_module("scsi_debug dev_size_mb=%s %s"
                          % (scsi_size, scsi_option))
        # Get the scsi device name
        scsi_disk = utils.run("lsscsi|grep scsi_debug|"
                              "awk '{print $6}'").stdout.strip()
        logging.info("scsi disk: %s" % scsi_disk)
        return scsi_disk
    except Exception, e:
        logging.error(str(e))
        return None


def delete_scsi_disk():
    """
    Delete scsi device by removing scsi_debug kernel module.
    """
    if utils.module_is_loaded("scsi_debug"):
        utils.unload_module("scsi_debug")


def set_controller_multifunction(vm_name, controller_type='scsi'):
    """
    Set multifunction on for controller device and expand to all function.
    """
    vmxml = vm_xml.VMXML.new_from_dumpxml(vm_name)
    exist_controllers = vmxml.get_devices("controller")
    # Used to contain controllers in format:
    # domain:bus:slot:func -> controller object
    expanded_controllers = {}
    # The index of controller
    index = 0
    for e_controller in exist_controllers:
        if e_controller.type != controller_type:
            continue
        # Set multifunction on
        address_attrs = e_controller.address.attrs
        address_attrs['multifunction'] = "on"
        domain = address_attrs['domain']
        bus = address_attrs['bus']
        slot = address_attrs['slot']
        all_funcs = ["0x0", "0x1", "0x2", "0x3", "0x4", "0x5", "0x6"]
        for func in all_funcs:
            key = "%s:%s:%s:%s" % (domain, bus, slot, func)
            address_attrs['function'] = func
            # Create a new controller instance
            new_controller = controller.Controller(controller_type)
            new_controller.xml = str(xml_utils.XMLTreeFile(e_controller.xml))
            new_controller.index = index
            new_controller.address = new_controller.new_controller_address(
                attrs=address_attrs)
            # Expand controller to all functions with multifunction
            if key not in expanded_controllers.keys():
                expanded_controllers[key] = new_controller
                index += 1

    logging.debug("Expanded controllers: %s", expanded_controllers.values())
    vmxml.del_controller(controller_type)
    vmxml.set_controller(expanded_controllers.values())
    vmxml.sync()


def attach_disks(vm, path, vgname, params):
    """
    Attach multiple disks.According parameter disk_type in params,
    it will create lvm or file type disks.

    :param path: file type disk's path
    :param vgname: lvm type disk's volume group name
    """
    # Additional disk on vm
    disks_count = int(params.get("added_disks_count", 1)) - 1
    multifunction_on = "yes" == params.get("multifunction_on", "no")
    disk_size = params.get("added_disk_size", "0.1")
    disk_type = params.get("added_disk_type", "file")
    disk_target = params.get("added_disk_target", "virtio")
    disk_format = params.get("added_disk_format", "raw")
    # Whether attaching device with --config
    attach_config = "yes" == params.get("attach_disk_config", "yes")

    def generate_disks_index(count, target="virtio"):
        # Created disks' index
        target_list = []
        # Used to flag progression
        index = 0
        # A list to maintain prefix for generating device
        # ['a','b','c'] means prefix abc
        prefix_list = []
        while count > 0:
            # Out of range for current prefix_list
            if (index / 26) > 0:
                # Update prefix_list to expand disks, such as [] -> ['a'],
                # ['z'] -> ['a', 'a'], ['z', 'z'] -> ['a', 'a', 'a']
                prefix_index = len(prefix_list)
                if prefix_index == 0:
                    prefix_list.append('a')
                # Append a new prefix to list, then update pre-'z' in list
                # to 'a' to keep the progression 1
                while prefix_index > 0:
                    prefix_index -= 1
                    prefix_cur = prefix_list[prefix_index]
                    if prefix_cur == 'z':
                        prefix_list[prefix_index] = 'a'
                        # All prefix in prefix_list are 'z',
                        # it's time to expand it.
                        if prefix_index == 0:
                            prefix_list.append('a')
                    else:
                        # For whole prefix_list, progression is 1
                        prefix_list[prefix_index] = chr(ord(prefix_cur) + 1)
                        break
                # Reset for another iteration
                index = 0
            prefix = "".join(prefix_list)
            suffix_index = index % 26
            suffix = chr(ord('a') + suffix_index)
            index += 1
            count -= 1

            # Generate device target according to driver type
            if target == "virtio":
                target_dev = "vd%s" % (prefix + suffix)
            elif target == "scsi":
                target_dev = "sd%s" % (prefix + suffix)
            target_list.append(target_dev)
        return target_list

    target_list = generate_disks_index(disks_count, disk_target)

    # A dict include disks information: source file and size
    added_disks = {}
    for target_dev in target_list:
        # Do not attach if it does already exist
        if device_exists(vm, target_dev):
            continue

        # Prepare controller for special disks like virtio-scsi
        # Open multifunction to add more controller for disks(150 or more)
        if multifunction_on:
            set_controller_multifunction(vm.name, disk_target)

        disk_params = {}
        disk_params['type_name'] = disk_type
        disk_params['target_dev'] = target_dev
        disk_params['target_bus'] = disk_target
        disk_params['device_type'] = params.get("device_type", "disk")
        device_name = "%s_%s" % (target_dev, vm.name)
        disk_path = os.path.join(os.path.dirname(path), device_name)
        disk_path = create_local_disk(disk_type, disk_path,
                                      disk_size, disk_format,
                                      vgname, device_name)
        added_disks[disk_path] = disk_size
        result = attach_additional_device(vm.name, target_dev, disk_path,
                                          disk_params, attach_config)
        if result.exit_status:
            raise error.TestFail("Attach device %s failed."
                                 % target_dev)
    logging.debug("New VM XML:\n%s", vm.get_xml())
    return added_disks


def define_new_vm(vm_name, new_name):
    """
    Just define a new vm from given name
    """
    try:
        vmxml = vm_xml.VMXML.new_from_dumpxml(vm_name)
        vmxml.vm_name = new_name
        del vmxml.uuid
        vmxml.define()
        return True
    except xcepts.LibvirtXMLError, detail:
        logging.error(detail)
        return False


def remotely_control_libvirtd(server_ip, server_user, server_pwd,
                              action='restart', status_error='no'):
    """
    Remotely restart libvirt service
    """
    session = None
    try:
        session = remote.wait_for_login('ssh', server_ip, '22',
                                        server_user, server_pwd,
                                        r"[\#\$]\s*$")
        logging.info("%s libvirt daemon\n", action)
        service_libvirtd_control(action, session)
        session.close()
    except (remote.LoginError, aexpect.ShellError, error.CmdError), detail:
        if session:
            session.close()
        if status_error == "no":
            raise error.TestFail("Failed to %s libvirtd service on "
                                 "server: %s\n", action, detail)
        else:
            logging.info("It is an expect %s", detail)


def connect_libvirtd(uri, read_only="", virsh_cmd="list", auth_user=None,
                     auth_pwd=None, vm_name="", status_error="no",
                     extra="", log_level='LIBVIRT_DEBUG=3', su_user="",
                     patterns_virsh_cmd=".*Id\s*Name\s*State\s*.*"):
    """
    Connect libvirt daemon
    """
    patterns_yes_no = r".*[Yy]es.*[Nn]o.*"
    patterns_auth_name_comm = r".*name:.*"
    patterns_auth_name_xen = r".*name.*root.*:.*"
    patterns_auth_pwd = r".*[Pp]assword.*"

    command = "%s %s virsh %s -c %s %s %s" % (extra, log_level, read_only,
                                              uri, virsh_cmd, vm_name)
    # allow specific user to run virsh command
    if su_user != "":
        command = "su %s -c '%s'" % (su_user, command)

    logging.info("Execute %s", command)
    # setup shell session
    session = aexpect.ShellSession(command, echo=True)

    try:
        # requires access authentication
        match_list = [patterns_yes_no, patterns_auth_name_comm,
                      patterns_auth_name_xen, patterns_auth_pwd,
                      patterns_virsh_cmd]
        while True:
            match, text = session.read_until_any_line_matches(match_list,
                                                              timeout=30,
                                                              internal_timeout=1)
            if match == -5:
                logging.info("Matched 'yes/no', details: <%s>", text)
                session.sendline("yes")
            elif match == -3 or match == -4:
                logging.info("Matched 'username', details: <%s>", text)
                session.sendline(auth_user)
            elif match == -2:
                logging.info("Matched 'password', details: <%s>", text)
                session.sendline(auth_pwd)
            elif match == -1:
                logging.info("Expected output of virsh command: <%s>", text)
                break
            else:
                logging.error("The real prompt text: <%s>", text)
                break

        session.close()
        return True
    except (aexpect.ShellError, aexpect.ExpectError), details:
        log = session.get_output()
        session.close()
        logging.error("Failed to connect libvirtd: %s\n%s", details, log)
        return False


def get_all_vol_paths():
    """
    Get all volumes' path in host
    """
    vol_path = []
    sp = libvirt_storage.StoragePool()
    for pool_name in sp.list_pools().keys():
        pv = libvirt_storage.PoolVolume(pool_name)
        for path in pv.list_volumes().values():
            vol_path.append(path)
    return set(vol_path)


def do_migration(vm_name, uri, extra, auth_pwd, auth_user="root",
                 options="--verbose", virsh_patterns=".*100\s%.*"):
    """
    Migrate VM to target host.
    """
    patterns_yes_no = r".*[Yy]es.*[Nn]o.*"
    patterns_auth_name = r".*name:.*"
    patterns_auth_pwd = r".*[Pp]assword.*"

    command = "%s virsh migrate %s %s %s" % (extra, vm_name, options, uri)
    logging.info("Execute %s", command)
    # setup shell session
    session = aexpect.ShellSession(command, echo=True)

    try:
        # requires access authentication
        match_list = [patterns_yes_no, patterns_auth_name,
                      patterns_auth_pwd, virsh_patterns]
        while True:
            match, text = session.read_until_any_line_matches(match_list,
                                                              timeout=30,
                                                              internal_timeout=1)
            if match == -4:
                logging.info("Matched 'yes/no', details: <%s>", text)
                session.sendline("yes")
            elif match == -3:
                logging.info("Matched 'username', details: <%s>", text)
                session.sendline(auth_user)
            elif match == -2:
                logging.info("Matched 'password', details: <%s>", text)
                session.sendline(auth_pwd)
            elif match == -1:
                logging.info("Expected output of virsh migrate: <%s>", text)
                break
            else:
                logging.error("The real prompt text: <%s>", text)
                break

        session.close()
        return True
    except (aexpect.ShellError, aexpect.ExpectError), details:
        log = session.get_output()
        session.close()
        logging.error("Failed to migrate %s: %s\n%s", vm_name, details, log)
        return False


def update_vm_disk_source(vm_name, disk_source_path, source_type="file"):
    """
    Update disk source path of the VM

    :param source_type: it may be 'dev' or 'file' type, which is default
    """
    if not os.path.isdir(disk_source_path):
        logging.error("Require disk source path!!")
        return False
    # Prepare to update VM first disk source file
    vmxml = vm_xml.VMXML.new_from_dumpxml(vm_name)
    devices = vmxml.devices
    disk_index = devices.index(devices.by_device_tag('disk')[0])
    disks = devices[disk_index]
    disk_source = disks.source.get_attrs().get(source_type)
    logging.debug("The disk source file of the VM: %s", disk_source)
    if not os.path.exists(disk_source):
        logging.error("The disk source doesn't exist!!")
        return False

    vm_name_with_format = os.path.basename(disk_source)
    new_disk_source = os.path.join(disk_source_path, vm_name_with_format)
    logging.debug("The new disk source file of the VM: %s", new_disk_source)

    # Update VM disk source file
    disks.source = disks.new_disk_source(**{'attrs': {'%s' % source_type:
                                                      "%s" % new_disk_source}})
    # SYNC VM XML change
    vmxml.devices = devices
    logging.debug("The new VM XML:\n%s", vmxml.xmltreefile)
    vmxml.sync()
    return True


def hotplug_domain_vcpu(vm_name, vcpu_count, set_cmd="setvcpus",
                        action="hotplug"):
    """
    Hotplug/Unhotplug vcpu for domian

    :param vm_name: Domain name, id, uuid
    :param vcpu_count: For 'setvcpus', it means the current vcpus count
                       For 'qemu-monitor-command', it's used to get max vcpu
                       num by (vcpu_count - 1)
    :param set_cmd: The vcpu hotplug/unhotplug operate command
    :param action: hotplug/unhotplug action
    """
    if action not in ["hotplug", "unhotplug"]:
        raise ValueError("Unsupport operate action for vcpu:%s" % action)
    if set_cmd == "setvcpus":
        result = virsh.setvcpus(vm_name, vcpu_count, "--live", debug=True)
    elif set_cmd == "qemu-monitor-command":
        cpu_opt = "cpu-add"
        if action == "unhotplug":
            cpu_opt = "cpu-del"
        result = virsh.qemu_monitor_command(vm_name,
                            '{\"execute\":\"%s\",\"arguments\":{\"id\":%d}}'\
                                            % (cpu_opt, (vcpu_count - 1)),
                                            "--pretty",
                                            debug=True)
    else:
        raise ValueError("Unsupport hotplug operate command for vcpu:%s"
                         % set_cmd)
    return result
