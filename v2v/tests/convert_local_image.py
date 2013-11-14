import os
import logging
import re
from autotest.client import lv_utils
from autotest.client.shared import ssh_key, error
from virttest import utils_v2v, libvirt_storage, libvirt_vm
from virttest import virt_vm, virsh, remote, data_dir


def create_dir_pool(spool, pool_name, target_path):
    """
    Create a persistent dir pool.
    """
    # Check pool before creating
    if spool.pool_exists(pool_name):
        logging.debug("Pool '%s' exists on uri '%s'", pool_name,
                      spool.connect_uri)
        return False

    if not spool.define_dir_pool(pool_name, target_path):
        return False

    if not spool.build_pool(pool_name):
        return False

    if not spool.start_pool(pool_name):
        return False

    if not spool.set_pool_autostart(pool_name):
        return False
    return True


def create_partition_pool(spool, pool_name, block_device,
                          target_path="/dev/v2v_test"):
    """
    Create a persistent partition pool.
    """
    # Check pool before creating
    if spool.pool_exists(pool_name):
        logging.debug("Pool '%s' exists on uri '%s'", pool_name,
                      spool.connect_uri)
        return False

    if not spool.define_fs_pool(pool_name, block_device,
                                target_path=target_path):
        return False

    if not spool.build_pool(pool_name):
        return False

    if not spool.start_pool(pool_name):
        return False

    if not spool.set_pool_autostart(pool_name):
        return False
    return True


def create_disk_pool(spool, pool_name, block_device,
                     target_path="/dev/"):
    """
    Create a persistent partition pool.
    """
    # Check pool before creating
    if spool.pool_exists(pool_name):
        logging.debug("Pool '%s' exists on uri '%s'", pool_name,
                      spool.connect_uri)
        return False

    if not spool.define_fs_pool(pool_name, block_device,
                                target_path=target_path):
        return False

    if not spool.build_pool(pool_name):
        return False

    if not spool.start_pool(pool_name):
        return False

    if not spool.set_pool_autostart(pool_name):
        return False
    return True


def create_lvm_pool(spool, pool_name, block_device, vg_name="vg_v2v",
                    target_path="/dev/vg_v2v"):
    """
    Create a persistent lvm pool.
    """
    # Check pool before creating
    if spool.pool_exists(pool_name):
        logging.debug("Pool '%s' exists on uri '%s'", pool_name,
                      spool.connect_uri)
        return False

    if not spool.define_lvm_pool(pool_name, block_device, vg_name=vg_name,
                                 target_path=target_path):
        return False

    vgroups = lv_utils.vg_list()
    if vg_name not in vgroups.keys() and not spool.build_pool(pool_name):
        return False

    if not spool.start_pool(pool_name):
        return False

    if not spool.set_pool_autostart(pool_name):
        return False
    return True


def get_remote_vm_disk(rvm):
    """
    Local v2v need remote vm's disk to copy.

    :param rvm: remote vm instance
    """
    # Get remote vms' disk path
    disks = rvm.get_disk_devices()
    target_path = ''
    for target in ['hda', 'sda', 'vda', 'xvda']:
        try:
            target_path = disks[target]["source"]
            logging.debug("System Disk:%s", target_path)
        except KeyError:
            continue
    return target_path


def copy_remote_vm(rvm, local_path, remote_host,
                   username, password, timeout=1200):
    """
    Copy remote vm's disk to local path.

    :param local_path: Where should we put the disk
    :return: fixed XML file path
    """
    remote_disk_path = get_remote_vm_disk(rvm)
    disk_name = os.path.basename(remote_disk_path)
    local_tmp_disk = os.path.join(local_path, disk_name)
    local_tmp_xml = os.path.join(local_path, "%s.xml" % rvm.name)
    try:
        remote.scp_from_remote(remote_host, 22, username, password,
                               remote_disk_path, local_tmp_disk,
                               timeout=timeout)
    except Exception, detail:
        logging.error(str(detail))
        return None
    rvm_xml = rvm.get_xml()
    tmp_xml = re.sub(remote_disk_path, local_tmp_disk, rvm_xml)
    f_xml = open(local_tmp_xml, 'w')
    f_xml.write(tmp_xml)
    f_xml.close()
    return local_tmp_xml


def cleanup_vm(vm_name=None, disk=None):
    """
    Cleanup the vm with its disk deleted.
    """
    try:
        if vm_name is not None:
            virsh.undefine(vm_name)
    except error.CmdError:
        pass
    try:
        if disk is not None:
            os.remove(disk)
    except IOError:
        pass


def run(test, params, env):
    """
    Convert a local vm disk to local libvirt(KVM).
    """
    # VM info
    vm_name = params.get("v2v_vm")

    # Remote host parameters
    remote_hostname = params.get("remote_hostname")
    username = params.get("remote_username", "root")
    password = params.get("remote_passwd")
    remote_hypervisor = params.get("remote_hypervisor")

    # Local pool parameters
    pool_type = params.get("pool_type", "dir")
    block_device = params.get("block_device", "/dev/BLOCK/EXAMPLE")
    if pool_type in ['disk', 'partition', 'lvm'] and \
            re.search("EXAMPLE", block_device):
        raise error.TestNAError("Please set correct block device.")
    pool_name = params.get("pool_name", "v2v_test")
    target_path = params.get("target_path", "pool_path")
    vg_name = params.get("volume_group_name", "vg_v2v")
    local_tmp_path = params.get("local_tmp_path", data_dir.get_tmp_dir())
    # If target_path is not an abs path, join it to data_dir.TMPDIR
    if os.path.dirname(target_path) is "":
        target_path = os.path.join(data_dir.get_tmp_dir(), target_path)

    # dir pool need an exist path
    if pool_type == "dir":
        if not os.path.exists(target_path):
            os.mkdir(target_path)

    # V2V parameters
    input = params.get("input_method")
    files = params.get("config_files")
    network = params.get("network", "default")

    # Result check about
    ignore_virtio = "yes" == params.get("ignore_virtio", "no")

    # Create remote uri for remote host
    # Remote virt-v2v uri's instance
    ruri = utils_v2v.Uri(remote_hypervisor)
    remote_uri = ruri.get_uri(remote_hostname)

    ssh_key.setup_ssh_key(remote_hostname, user=username, port=22,
                          password=password)

    # Check remote vms
    remote_vm = libvirt_vm.VM(vm_name, params, test.bindir,
                              env.get("address_cache"))
    remote_vm.connect_uri = remote_uri
    if not remote_vm.exists():
        raise error.TestFail("Couldn't find vm '%s' to be converted "
                             "on remote uri '%s'." % (vm_name, remote_uri))

    # Copy remote vm's disk to local and create xml file for it
    tmp_xml_file = copy_remote_vm(remote_vm, local_tmp_path, remote_hostname,
                                  username, password)

    # Local storage pool's instance
    lsp = libvirt_storage.StoragePool()
    try:
        # Create storage pool for test
        if pool_type == "dir":
            if not create_dir_pool(lsp, pool_name, target_path):
                raise error.TestFail("Prepare directory storage pool for "
                                     "virt-v2v failed.")
        elif pool_type == "partition":
            if not create_partition_pool(lsp, pool_name, block_device,
                                         target_path):
                raise error.TestFail("Prepare partition storage pool for "
                                     "virt-v2v failed.")
        elif pool_type == "lvm":
            if not create_lvm_pool(lsp, pool_name, block_device, vg_name,
                                   target_path):
                raise error.TestFail("Prepare lvm storage pool for "
                                     "virt-v2v failed.")
        elif pool_type == "disk":
            if not create_disk_pool(lsp, pool_name, block_device, target_path):
                raise error.TestFail("Prepare disk storage pool for "
                                     "virt-v2v failed.")

        # Maintain a single params for v2v to avoid duplicate parameters
        v2v_params = {"hostname": remote_hostname, "username": username,
                      "password": password, "hypervisor": remote_hypervisor,
                      "storage": pool_name, "network": network,
                      "target": "libvirtxml", "vms": tmp_xml_file,
                      "input": input, "files": files}
        try:
            result = utils_v2v.v2v_cmd(v2v_params)
            logging.debug(result)
        except error.CmdError, detail:
            raise error.TestFail("Virt v2v failed:\n%s" % str(detail))

        # v2v may be successful, but devices' driver may be not virtio
        error_info = []
        # Check v2v vm on local host
        # Update parameters for local hypervisor and vm
        params['vms'] = vm_name
        params['target'] = "libvirt"
        vm_check = utils_v2v.LinuxVMCheck(test, params, env)
        try:
            if not vm_check.is_disk_virtio():
                error_info.append("Error:disk type was not converted to "
                                  "virtio.")
            if not vm_check.is_net_virtio():
                error_info.append("Error:nic type was not converted to "
                                  "virtio.")
        except (remote.LoginError, virt_vm.VMError), detail:
            error_info.append(str(detail))

        # Close vm for cleanup
        if vm_check.vm is not None and vm_check.vm.is_alive():
            vm_check.vm.destroy()

        if not ignore_virtio and len(error_info):
            raise error.TestFail(error_info)
    finally:
        cleanup_vm(vm_name)
        lsp.delete_pool(pool_name)
