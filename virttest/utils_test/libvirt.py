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
import shutil
from virttest import virsh, xml_utils, iscsi, nfs, data_dir, aexpect
from virttest import utils_misc, utils_selinux, libvirt_storage
from autotest.client import utils
from autotest.client.shared import error
from virttest.libvirt_xml import vm_xml
try:
    from autotest.client import lv_utils
except ImportError:
    from virttest.staging import lv_utils


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
    # virsh freecell --all
        0:     124200 KiB
        1:    1059868 KiB
    --------------------
    Total:    1184068 KiB

    return: cell_dict, {"0":"124200 KiB",
                        "1":"1059868 KiB",
                        "Total":"1184068 KiB"}
    """
    fc_result = virsh.freecell("--all", ignore_status=True)
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


def setup_or_cleanup_nfs(is_setup, mount_dir="", is_mount=False,
                         export_options="rw,no_root_squash",
                         mount_src="nfs-export"):
    """
    Set up or clean up nfs service on localhost.

    :param is_setup: Boolean value, true for setup, false for cleanup
    :param mount_dir: NFS mount point
    :param is_mount: Boolean value, true for mount, false for umount
    :param export_options: options for nfs dir
    :return: export nfs path or nothing
    """
    tmpdir = os.path.join(data_dir.get_root_dir(), 'tmp')
    if not os.path.isabs(mount_src):
        mount_src = os.path.join(tmpdir, mount_src)
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


def setup_or_cleanup_iscsi(is_setup, is_login=True,
                           emulated_image="emulated_iscsi", image_size="1G"):
    """
    Set up(and login iscsi target) or clean up iscsi service on localhost.

    :param is_setup: Boolean value, true for setup, false for cleanup
    :param is_login: Boolean value, true for login, false for not login
    :param emulated_image: name of iscsi device
    :param image_size: emulated image's size
    :return: iscsi device name or iscsi target
    """
    tmpdir = os.path.join(data_dir.get_root_dir(), 'tmp')
    emulated_path = os.path.join(tmpdir, emulated_image)
    emulated_target = "iqn.2001-01.com.virttest:%s.target" % emulated_image
    iscsi_params = {"emulated_image": emulated_path,
                    "target": emulated_target,
                    "image_size": image_size,
                    "iscsi_thread_id": "virt"}
    _iscsi = iscsi.Iscsi(iscsi_params)
    if is_setup:
        sv_status = None
        if utils_misc.selinux_enforcing():
            sv_status = utils_selinux.get_status()
            utils_selinux.set_status("Permissive")
        _iscsi.export_target()
        if sv_status is not None:
            utils_selinux.set_status(sv_status)
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


def mk_part(disk, size="100M"):
    """
    Create a partition for disk
    """
    cmd = "parted -s %s mklabel msdos" % disk
    utils.run(cmd)
    cmd = "parted -s %s mkpart primary ext4 0 %s" % (disk, size)
    utils.run(cmd)


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

    def cleanup_pool(self, pool_name, pool_type, pool_target, emulated_image):
        """
        Delete vols, destroy the created pool and restore the env
        """
        sp = libvirt_storage.StoragePool()
        pv = libvirt_storage.PoolVolume(pool_name)
        if pool_type in ["dir", "netfs"]:
            vols = pv.list_volumes()
            for vol in vols:
                # Ignore failed deletion here for deleting pool
                pv.delete_volume(vol)
        try:
            if not sp.delete_pool(pool_name):
                raise error.TestFail("Delete pool %s failed" % pool_name)
        finally:
            if pool_type == "netfs":
                nfs_server_dir = self.params.get("nfs_server_dir", "nfs-server")
                nfs_path = os.path.join(self.tmpdir, nfs_server_dir)
                setup_or_cleanup_nfs(is_setup=False, mount_dir=nfs_path)
                if os.path.exists(nfs_path):
                    shutil.rmtree(nfs_path)
            if pool_type == "logical":
                cmd = "pvs |grep vg_logical|awk '{print $1}'"
                pv = utils.system_output(cmd)
                utils.run("vgremove -f vg_logical")
                utils.run("pvremove %s" % pv)
            # These types used iscsi device
            if pool_type in ["logical", "iscsi", "fs", "disk", "scsi"]:
                setup_or_cleanup_iscsi(is_setup=False,
                                       emulated_image=emulated_image)
            if pool_type == "dir":
                pool_target = os.path.join(self.tmpdir, pool_target)
                if os.path.exists(pool_target):
                    shutil.rmtree(pool_target)

    def pre_pool(self, pool_name, pool_type, pool_target, emulated_image,
                 image_size="100M"):
        """
        Preapare the specific type pool
        Note:
        1. For scsi type pool, it only could be created from xml file
        2. Other type pools can be created by pool_creat_as function
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
            mk_part(device_name)
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
            nfs_server_dir = self.params.get("nfs_server_dir", "nfs-server")
            nfs_path = os.path.join(self.tmpdir, nfs_server_dir)
            if not os.path.exists(nfs_path):
                os.mkdir(nfs_path)
            pool_target = os.path.join(self.tmpdir, pool_target)
            if not os.path.exists(pool_target):
                os.mkdir(pool_target)
            setup_or_cleanup_nfs(is_setup=True,
                                 export_options="rw,async,no_root_squash",
                                 mount_src=nfs_path)
            source_host = self.params.get("source_host", "localhost")
            extra = "--source-host %s --source-path %s" % (source_host,
                                                           nfs_path)
        elif pool_type == "iscsi":
            logical_device = setup_or_cleanup_iscsi(is_setup=True,
                                            emulated_image=emulated_image,
                                                    image_size=image_size)
            iscsi_session = iscsi.iscsi_get_sessions()
            iscsi_device = ()
            for iscsi_node in iscsi_session:
                if iscsi_node[1].count(emulated_image):
                    iscsi_device = iscsi_node
                    break
            if iscsi_device == ():
                raise error.TestFail("No iscsi device.")
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

        # Create pool
        if pool_type == "scsi":
            re_v = virsh.pool_create(scsi_xml_file)
        else:
            re_v = virsh.pool_create_as(pool_name, pool_type,
                                        pool_target, extra)
        if not re_v:
            raise error.TestFail("Create pool failed.")
        # Check the created pool
        check_actived_pool(pool_name)

    def pre_vol(self, vol_name, vol_format, vol_size, pool_name):
        """
        Preapare the specific type volume in pool
        """
        pv = libvirt_storage.PoolVolume(pool_name)
        if not pv.create_volume(vol_name, vol_size, vol_size, vol_format):
            raise error.TestFail("Prepare volume failed.")
        if not pv.volume_exists(vol_name):
            raise error.TestFail("Can't find volume: %s", vol_name)
