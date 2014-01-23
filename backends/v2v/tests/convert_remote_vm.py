import os
import logging
import re
from autotest.client import lv_utils
from autotest.client.shared import ssh_key, error
from virttest import utils_v2v, libvirt_storage, libvirt_vm, virsh
from virttest import virt_vm, remote, data_dir


def create_dir_pool(spool, pool_name, target_path):
    """
    Create a persistent dir pool.
    """
    # Check pool before creating
    if spool.pool_exists(pool_name):
        logging.debug("Pool '%s' already exists.", pool_name)
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
        logging.debug("Pool '%s' already exists.", pool_name)
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
        logging.debug("Pool '%s' already exists.", pool_name)
        return False

    if not spool.define_lvm_pool(pool_name, block_device, vg_name=vg_name,
                                 target_path=target_path):
        return False

    vgroups = lv_utils.vg_list()
    if vg_name not in vgroups.keys() and not spool.build_pool(pool_name):
        return False

    # To verify if volume group has been set.
    try:
        lv_utils.lv_create(vg_name, "v2v_sample", "10M", True)
        lv_utils.lv_remove(vg_name, "v2v_sample")
    except (error.TestError, error.CmdError), detail:
        logging.error("Check volume group failed:\n%s", str(detail))
        return False

    if not spool.start_pool(pool_name):
        return False

    if not spool.set_pool_autostart(pool_name):
        return False
    return True


def prepare_remote_sp(rsp, rvm, pool_name="v2v_test"):
    """
    v2v need remote vm's disk stored in a pool.

    :param rsp: remote storage pool's instance
    :param rvm: remote vm instance
    """
    # Get remote vms' disk path
    disks = rvm.get_disk_devices()
    target_path = ''
    for target in ['hda', 'sda', 'vda', 'xvda']:
        try:
            target_path = disks[target]["source"]
            logging.debug("System Disk:%s", target_path)
            target_path = os.path.dirname(target_path)
        except KeyError:
            continue
    if target_path:
        return create_dir_pool(rsp, pool_name, target_path)
    return False


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
    Convert a remote vm to local libvirt(KVM).
    """
    # VM info
    vm_name = params.get("v2v_vm")

    # Remote host parameters
    remote_hostname = params.get("remote_hostname")
    username = params.get("username", "root")
    password = params.get("password")
    remote_hypervisor = params.get("remote_hypervisor")

    # Local pool parameters
    pool_type = params.get("pool_type", "dir")
    pool_name = params.get("pool_name", "v2v_test")
    target_path = params.get("target_path", "pool_path")
    block_device = params.get("block_device", "/dev/BLOCK/EXAMPLE")
    vg_name = params.get("volume_group_name", "vg_v2v")

    # Confirm parameters have been set correctly.
    if (pool_type in ['partition', 'lvm'] and
            re.search("EXAMPLE", block_device)):
        raise error.TestNAError("Please set correct block device.")

    # If target_path is not an abs path, join it to data_dir.tmpdir
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

    # Create autologin to remote host
    esx_netrc = params.get("esx_netrc") % (remote_hostname, username, password)
    params['netrc'] = esx_netrc
    if remote_hypervisor == "esx":
        utils_v2v.build_esx_no_verify(params)
    else:
        ssh_key.setup_ssh_key(remote_hostname, user=username, port=22,
                              password=password)

    # Create remote uri for remote host
    # Remote virt-v2v uri's instance
    ruri = utils_v2v.Uri(remote_hypervisor)
    remote_uri = ruri.get_uri(remote_hostname)

    # Check remote vms
    rvirsh_dargs = {'uri': remote_uri, 'remote_ip': remote_hostname,
                    'remote_user': username, 'remote_pwd': password}
    rvirsh = virsh.VirshPersistent(**rvirsh_dargs)
    if not rvirsh.domain_exists(vm_name):
        rvirsh.close_session()
        raise error.TestFail("Couldn't find vm '%s' to be converted "
                             "on remote uri '%s'." % (vm_name, remote_uri))

    if remote_hypervisor != "esx":
        remote_vm = libvirt_vm.VM(vm_name, params, test.bindir,
                                  env.get("address_cache"))
        remote_vm.connect_uri = remote_uri
        # Remote storage pool's instance
        rsp = libvirt_storage.StoragePool(rvirsh)
        # Put remote vm's disk into a directory storage pool
        prepare_remote_sp(rsp, remote_vm, pool_name)

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
                raise error.TestFail("Preapre lvm storage pool for "
                                     "virt-v2v failed.")

        # Maintain a single params for v2v to avoid duplicate parameters
        v2v_params = {"hostname": remote_hostname, "username": username,
                      "password": password, "hypervisor": remote_hypervisor,
                      "storage": pool_name, "network": network,
                      "target": "libvirt", "vms": vm_name, "netrc": esx_netrc,
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
        if remote_hypervisor != "esx":
            rsp.delete_pool(pool_name)
