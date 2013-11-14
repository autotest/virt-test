import logging
import re
import os
import shutil
from virttest import iscsi, virsh
from autotest.client import utils
from autotest.client.shared import error


def run(test, params, env):
    """
    Test virsh vol-create-from command to cover the following matrix:

    pool = [source, destination]
    pool_type = [dir, disk, fs, logical, netfs, iscsi, scsi]
    volume_format = [raw, qcow2, qed]

    Note, both 'iscsi' and 'scsi' type pools don't support create volume by
    virsh, so which can't be destination pools. And for disk pool, it can't
    create volume with specified format.
    """

    src_pool_type = params.get("src_pool_type")
    src_pool_target = params.get("src_pool_target")
    src_emulated_image = params.get("src_emulated_image")
    src_vol_format = params.get("src_vol_format")
    dest_pool_type = params.get("dest_pool_type")
    dest_pool_target = params.get("dest_pool_target")
    dest_emulated_image = params.get("dest_emulated_image")
    dest_vol_format = params.get("dest_vol_format")
    nfs_server_dir = params.get("nfs_server_dir", "nfs-server")
    source_host = params.get("source_host", "localhost")
    prealloc_option = params.get("prealloc_option")
    status_error = params.get("status_error", "no")

    def login_iscsi(emulated_image, image_size):
        """
        Login the iscsi target, and return the device
        """

        utils.run("setenforce 0")
        emulated_image_path = os.path.join(test.tmpdir, emulated_image)
        emulated_target = "iqn.2001-01.com.autotest:%s.target" % emulated_image
        iscsi_params = {"emulated_image": emulated_image_path,
                        "target": emulated_target,
                        "image_size": image_size}
        _iscsi = iscsi.Iscsi(iscsi_params)
        _iscsi.export_target()
        _iscsi.login()
        iscsi_device = _iscsi.get_device_name()
        logging.debug("iscsi device: %s", iscsi_device)
        utils.run("setenforce 1")
        return iscsi_device

    def set_nfs_server(share_cfg):
        """
        Start nfs server on host.
        """

        shutil.copyfile("/etc/exports", "/etc/exports.virt")
        cmd = "echo '%s' > /etc/exports" % (share_cfg)
        utils.run(cmd)
        utils.run("service nfs restart")

    def mk_part(disk):
        """
        Create a partition for disk
        """

        cmd = "parted -s %s mklabel msdos" % disk
        utils.run(cmd)
        cmd = "parted -s %s mkpart primary ext4 0 100" % disk
        utils.run(cmd)

    def check_pool(pool_name):
        """
        Check if pool_name exist in active pool list
        """

        output = virsh.pool_list(option="", ignore_status=True)
        if output.exit_status != 0:
            raise error.TestFail("Virsh pool-list command failed:\n%s" %
                                 output.stderr)
        pool_list = re.findall(r"([\w-]+[\w]+)\s+(\w+)\s+(\w+)", str(output))
        find_pool = False
        for pool in pool_list:
            if pool_name in pool[0]:
                logging.debug("Find active pool %s", pool_name)
                find_pool = True
        return find_pool

    def get_vol_list(pool_name):
        """
        Get a volume from the given pool
        """

        # Get the volume list stored in a variable
        output = virsh.vol_list(pool_name, ignore_status=True)
        if output.exit_status != 0:
            raise error.TestFail("Virsh vol-list command failed:\n%s" %
                                 output.stderr)
        vol_list = re.findall(r"\n(.+\S+)\ +\S+", str(output.stdout))
        return vol_list

    def check_vol(vol_name, pool_name):
        """
        Check if vol_name exist in the given pool
        """

        return (vol_name in get_vol_list(pool_name))

    def cleanup_pool(pool_name, pool_type, pool_target):
        """
        Delete vols, destroy the created pool and restore the env
        """
        if pool_type in ["dir", "netfs"]:
            vols = get_vol_list(pool_name)
            for vol in vols:
                result = virsh.vol_delete(vol, pool_name)
                if result.exit_status:
                    raise error.TestFail("Command virsh vol-delete failed:\n%s"
                                         % result.stderr)
            else:
                logging.debug("Delete volume %s from pool %s", vol, pool_name)
        if not virsh.pool_destroy(pool_name):
            raise error.TestFail("Command virsh pool-destroy failed")
        else:
            logging.debug("Destroy pool %s", pool_name)
        if pool_type == "netfs":
            shutil.move("/etc/exports.virt", "/etc/exports")
            utils.run("service nfs restart")
            nfs_path = os.path.join(test.tmpdir, nfs_server_dir)
            if os.path.exists(nfs_path):
                shutil.rmtree(nfs_path)
        if pool_type == "logical":
            cmd = "pvs |grep vg_logical|awk '{print $1}'"
            pv = utils.system_output(cmd)
            utils.run("vgremove -f vg_logical")
            utils.run("pvremove %s" % pv)
        if pool_type in ["dir", "fs", "netfs"]:
            pool_target = os.path.join(test.tmpdir, pool_target)
            if os.path.exists(pool_target):
                shutil.rmtree(pool_target)

    def cleanup_iscsi():
        """
        Logout all iscsi target and restart tgtd service
        """
        iscsi_session = iscsi.iscsi_get_sessions()
        if iscsi_session:
            utils.run("iscsiadm -m node -u")
        utils.run("service tgtd restart")
        for image in [src_emulated_image, dest_emulated_image]:
            if image:
                image = os.path.join(test.tmpdir, image)
                if os.path.exists(image):
                    utils.run("rm -f %s" % image)

    def pre_pool(pool_name, pool_type, pool_target, emulated_image):
        """
        Preapare the specific type pool
        Note:
        1. For scsi type pool, it only could be created from xml file
        2. Other type pools can be created by pool_creat_as function
        """

        extra = ""
        if pool_type == "dir":
            logging.info(test.tmpdir)
            pool_target = os.path.join(test.tmpdir, pool_target)
            if not os.path.exists(pool_target):
                os.mkdir(pool_target)

        elif pool_type == "disk":
            device_name = login_iscsi(emulated_image, "1G")
            mk_part(device_name)
            extra = " --source-dev %s" % device_name

        elif pool_type == "fs":
            device_name = login_iscsi(emulated_image, "1G")
            cmd = "mkfs.ext4 -F %s" % device_name
            pool_target = os.path.join(test.tmpdir, pool_target)
            if not os.path.exists(pool_target):
                os.mkdir(pool_target)
            extra = " --source-dev %s" % device_name
            utils.run(cmd)

        elif pool_type == "logical":
            logical_device = login_iscsi(emulated_image, "1G")
            cmd_pv = "pvcreate %s" % logical_device
            vg_name = "vg_%s" % pool_type
            cmd_vg = "vgcreate %s %s" % (vg_name, logical_device)
            extra = "--source-name %s" % vg_name
            utils.run(cmd_pv)
            utils.run(cmd_vg)

        elif pool_type == "netfs":
            nfs_path = os.path.join(test.tmpdir, nfs_server_dir)
            if not os.path.exists(nfs_path):
                os.mkdir(nfs_path)
            pool_target = os.path.join(test.tmpdir, pool_target)
            if not os.path.exists(pool_target):
                os.mkdir(pool_target)
            set_nfs_server("%s *(rw,async,no_root_squash)" % nfs_path)
            extra = "--source-host %s --source-path %s" % (source_host, nfs_path)

        elif pool_type == "iscsi":
            logical_device = login_iscsi(emulated_image, "100M")
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
            scsi_xml_file = params.get("scsi_xml_file")
            if not os.path.exists(scsi_xml_file):
                scsi_xml_file = os.path.join(test.tmpdir, scsi_xml_file)
                logical_device = login_iscsi(emulated_image, "100M")
                cmd = "iscsiadm -m session -P 3 |grep -B3 %s| \
                       grep Host|awk '{print $3}'" % logical_device.split('/')[2]
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
            re_v = virsh.pool_create_as(pool_name, pool_type, pool_target, extra)
        if not re_v:
            raise error.TestFail("Create pool failed.")
        # Check the created pool
        if not check_pool(pool_name):
            raise error.TestFail("Can't find active pool: %s", pool_name)

    def pre_vol(vol_name, vol_format, vol_size, pool_name):
        """
        Preapare the specific type volume in pool
        """

        result = virsh.vol_create_as(vol_name, pool_name, vol_size,
                                     vol_size, vol_format, ignore_status=True)
        if result.exit_status != 0:
            raise error.TestFail("Command virsh vol-create-as failed:\n%s" %
                                 result.stderr)
        if not check_vol(vol_name, pool_name):
            raise error.TestFail("Can't find volume: %s", vol_name)

    # Create the src/dest pool
    src_pool_name = "virt-%s-pool" % src_pool_type
    dest_pool_name = "virt-%s-pool" % dest_pool_type
    pre_pool(src_pool_name, src_pool_type, src_pool_target, src_emulated_image)
    if src_pool_type != dest_pool_type:
        pre_pool(dest_pool_name, dest_pool_type, dest_pool_target, dest_emulated_image)

    # Create the src vol
    vol_size = "1048576"
    if src_pool_type in ["dir", "logical", "netfs", "fs"]:
        src_vol_name = "src_vol"
        pre_vol(src_vol_name, src_vol_format, vol_size, src_pool_name)
    else:
        src_vols = get_vol_list(src_pool_name)
        if src_vols:
            src_vol_name = src_vols[0]
        else:
            raise error.TestFail("No volume in pool: %s", src_pool_name)
    # Prepare vol xml file
    dest_vol_name = "dest_vol"
    if dest_pool_type == "disk":
        dest_vol_format = ""
        prealloc_option = ""
    vol_xml = """
<volume>
  <name>%s</name>
  <capacity unit='bytes'>%s</capacity>
  <target>
    <format type='%s'/>
  </target>
</volume>
""" % (dest_vol_name, vol_size, dest_vol_format)
    logging.debug("Prepare the volume xml: %s", vol_xml)
    vol_file = os.path.join(test.tmpdir, "dest_vol.xml")
    xml_object = open(vol_file, 'w')
    xml_object.write(vol_xml)
    xml_object.close()

    # iSCSI and SCSI type pool can't create vols via virsh
    if dest_pool_type in ["iscsi", "scsi"]:
        raise error.TestFail("Unsupport create vol for %s type pool",
                             dest_pool_type)
    # Metadata preallocation is not supported for block volumes
    if dest_pool_type in ["disk", "logical"]:
        prealloc_option = ""
    # Run run_virsh_vol_create_from to create dest vol
    cmd_result = virsh.vol_create_from(dest_pool_name, vol_file, src_vol_name,
                                       src_pool_name, prealloc_option,
                                       ignore_status=True, debug=True)
    status = cmd_result.exit_status
    try:
        # Check result
        if status_error == "no":
            if status == 0:
                if not check_vol(dest_vol_name, dest_pool_name):
                    raise error.TestFail("Can't find volume: % from pool: %s",
                                         dest_vol_name, dest_pool_name)
            else:
                raise error.TestFail(cmd_result.stderr)
        else:
            if status:
                logging.debug("Expect error: %s", cmd_result.stderr)
            else:
                raise error.TestFail("Expect fail, but run successfully!")
    finally:
        # Cleanup
        cleanup_pool(src_pool_name, src_pool_type, src_pool_target)
        if src_pool_type != dest_pool_type:
            cleanup_pool(dest_pool_name, dest_pool_type, dest_pool_target)
        if src_pool_type or dest_pool_type in ["disk", "logical", "fs", "iscsi",
                                               "scsi"]:
            cleanup_iscsi()
