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

:copyright: 2013 Red Hat Inc.
"""

import re
import os
import logging
from virttest import virsh, xml_utils, iscsi, nfs, data_dir
from autotest.client import utils
from autotest.client import lv_utils
from autotest.client.shared import error
from virttest.libvirt_xml import vm_xml


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


def setup_or_cleanup_nfs(is_setup, mount_dir="", is_mount=False):
    """
    Set up or clean up nfs service on localhost.

    :param is_setup: Boolean value, true for setup, false for cleanup
    :param mount_dir: NFS mount point
    :param is_mount: Boolean value, true for mount, false for umount
    :return: export nfs path or nothing
    """
    tmpdir = os.path.join(data_dir.get_root_dir(), 'tmp')
    mount_src = os.path.join(tmpdir, 'nfs-export')
    if not mount_dir:
        mount_dir = os.path.join(tmpdir, 'nfs-mount')

    nfs_params = {"nfs_mount_dir": mount_dir,
                  "nfs_mount_options": "rw",
                  "nfs_mount_src": mount_src,
                  "setup_local_nfs": "yes",
                  "export_options": "rw,no_root_squash"}
    _nfs = nfs.Nfs(nfs_params)
    if is_setup:
        _nfs.setup()
        if not is_mount:
            _nfs.umount()
        return mount_src
    else:
        _nfs.unexportfs_in_clean = True
        _nfs.cleanup()
        return ""


def setup_or_cleanup_iscsi(is_setup, is_login=True):
    """
    Set up(and login iscsi target) or clean up iscsi service on localhost.

    :param is_setup: Boolean value, true for setup, false for cleanup
    :param is_login: Boolean value, true for login, false for not login
    :return: iscsi device name or iscsi target
    """
    emulated_image = "emulated_iscsi"
    tmpdir = os.path.join(data_dir.get_root_dir(), 'tmp')
    emulated_path = os.path.join(tmpdir, emulated_image)
    emulated_target = "iqn.2001-01.com.virttest:%s.target" % emulated_image
    iscsi_params = {"emulated_image": emulated_path,
                    "target": emulated_target,
                    "image_size": "1G",
                    "iscsi_thread_id": "virt"}
    _iscsi = iscsi.Iscsi(iscsi_params)
    if is_setup:
        utils.run("setenforce 0")
        _iscsi.export_target()
        utils.run("setenforce 1")
        if is_login:
            _iscsi.login()
            iscsi_device = _iscsi.get_device_name()
            logging.debug("iscsi device: %s", iscsi_device)
            if iscsi_device:
                return iscsi_device
            else:
                logging.error("Not find iscsi device.")
        else:
            return emulated_target
    else:
        _iscsi.export_flag = True
        _iscsi.emulated_id = _iscsi.get_target_id()
        _iscsi.cleanup()
        utils.run("rm -f %s" % emulated_path)
    return ""


def define_pool(pool_name, pool_type, pool_target, cleanup_flag):
    """
    To define a given type pool(Support types: 'dir', 'netfs', logical',
    iscsi', 'disk' and 'fs').

    :param pool_name: Name of the pool
    :param pool_type: Type of the pool
    :param pool_target: Target for underlying storage
    """
    extra = ""
    vg_name = pool_name
    cleanup_nfs = False
    cleanup_iscsi = False
    cleanup_logical = False
    if not os.path.exists(pool_target):
        os.mkdir(pool_target)
    if pool_type == "dir":
        pass
    elif pool_type == "netfs":
        # Set up NFS server without mount
        nfs_path = setup_or_cleanup_nfs(True, pool_target, False)
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
    try:
        result = virsh.pool_define_as(pool_name, pool_type, pool_target, extra,
                                      ignore_status=True)
    except error.CmdError:
        logging.error("Define '%s' type pool fail.", pool_type)
    return result
