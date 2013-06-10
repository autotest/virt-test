import os, logging
from autotest.client.shared import ssh_key, error
from virttest import utils_v2v, libvirt_storage, libvirt_vm


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


def run_convert_remote_vm(test, params, env):
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
    target_path = params.get("target_path", "v2v_path")
    # If target_path is not an abs path, join it to test.tmpdir
    if os.path.dirname(target_path) is "":
        target_path = os.path.join(test.tmpdir, target_path)
    if not os.path.exists(target_path):
        os.mkdir(target_path)

    # Network parameters
    network = params.get("network", "default")

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

    # Remote storage pool's instance
    # rsp = libvirt_storage.StoragePool(remote_uri)
    # TODO: Check whether remote vm's disk stored in a storage pool
    # If not, create one

    # Local storage pool's instance
    lsp = libvirt_storage.StoragePool()
    try:
        # Create storage pool for test
        if not create_dir_pool(lsp, pool_name, target_path):
            raise error.TestFail("Prepare storage pool for virt-v2v failed.")

        v2v_params = {"hostname": remote_hostname, "username": username,
                      "password": password, "hypervisor": remote_hypervisor,
                      "storage": pool_name, "network": network,
                      "target": "libvirt", "vms": vm_name}
        try:
            result = utils_v2v.v2v_cmd(v2v_params)
        except error.CmdError:
            raise error.TestFail("Virt v2v failed.")
    finally:
        lsp.delete_pool(pool_name)
