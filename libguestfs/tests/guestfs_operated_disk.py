import logging
from autotest.client.shared import error, utils
from virttest import utils_test
from virttest import virt_vm, aexpect, remote
from virttest.libvirt_xml import vm_xml


def truncate_from_file(ref_file, new_file, resize=0):
    """
    Truncate a new file reference given file's size.
    Then change its size if resize is not zero.

    @param resize: it can be +x or -x.
    """
    cmd = "truncate -r %s %s" % (ref_file, new_file)
    result = utils.run(cmd, ignore_status=True, timeout=15)
    logging.debug(result)
    if result.exit_status:
        return False
    if resize:
        cmd = "truncate -s %s %s" % (resize, new_file)
        result = utils.run(cmd, ignore_status=True, timeout=15)
        logging.debug(result)
        if result.exit_status:
            logging.error(result)
            return False
    return True


def test_cloned_vm(vm, params):
    """
    1) Clone a new vm with virt-clone
    2) Use guestfish to set new vm's network(accroding mac)
    3) Start new vm to check its network
    """
    new_vm_name = "%s_vtclone" % vm.name
    vt = utils_test.libguestfs.VirtTools(vm, params)
    clones, cloneo = vt.clone_vm_filesystem(new_vm_name)
    if clones is False:
       # Clean up:remove newvm and its storage
        utils_test.libguestfs.cleanup_vm(new_vm_name, vt.outdisk)
        raise error.TestFail(cloneo)
    new_vm = vt.newvm

    params['libvirt_domain'] = new_vm_name
    params['gf_inspector'] = True
    new_vm_mac = vm_xml.VMXML.get_first_mac_by_name(new_vm_name)
    if new_vm_mac is None:
        utils_test.libguestfs.cleanup_vm(new_vm_name, vt.outdisk)
        raise error.TestFail("Can not get new vm's mac address.")
    gf = utils_test.libguestfs.GuestfishTools(params)
    gf.reset_interface(new_vm_mac)
    gf.close_session()

    # This step for this reason:
    # virt-clone will move ifcfg-xxx to a file with suffix ".bak"
    # So we need start vm then shutdown it to copy it back
    new_vm = None
    try:
        try:
            new_vm.start()
            new_vm.wait_for_login(timeout=120)
        except (virt_vm.VMStartError, aexpect.ShellError, remote.LoginError):
            pass
    finally:
        if new_vm is not None:
            new_vm.destroy()
    gf.new_session()
    gf.copy_ifcfg_back()
    gf.close_session()

    logging.info("Checking cloned vm' IP...")
    try:
        new_vm.start()
        new_vm.wait_for_login()
    except (virt_vm.VMStartError, aexpect.ShellError,
            remote.LoginError), detail:
        new_vm.destroy(gracefully=False)
        utils_test.libguestfs.cleanup_vm(new_vm_name, vt.outdisk)
        raise error.TestFail("Check cloned vm's network failed:%s" % detail)

    new_vm.destroy()
    utils_test.libguestfs.cleanup_vm(new_vm_name, vt.outdisk)


def test_sparsified_vm(vm, params):
    """
    1) Write a file to oldvm
    2) Sparsify the oldvm to a newvm
    3) Check file's md5 in newvm
    """
    # Create a file to oldvm with guestfish
    content = "This is file for sparsified vm."
    path = params.get("temp_file", "/home/test_sparsified_vm")
    vt = utils_test.libguestfs.VirtTools(vm, params)

    params['libvirt_domain'] = vt.oldvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    if gf.write_file(path, content) is False:
        gf.close_session()
        raise error.TestFail("Create file failed.")

    md5s, md5o = gf.get_md5(path)
    if md5s is False:
        gf.close_session()
        raise error.TestFail(md5o)
    gf.close_session()
    md5_old = md5o.strip()
    logging.debug("%s's md5 in oldvm is:%s", path, md5_old)

    sparsifys, sparsifyo = vt.sparsify_disk()
    if sparsifys is False:
        utils_test.libguestfs.cleanup_vm(disk=vt.outdisk)
        raise error.TestFail(sparsifyo)

    defines, defineo = vt.define_vm_with_newdisk()
    if defines is False:
        utils_test.libguestfs.cleanup_vm(disk=vt.outdisk)
        raise error.TestFail(defineo)

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    md5s, md5o = gf.get_md5(path)
    if md5s is False:
        gf.close_session()
        raise error.TestFail(md5o)
    gf.close_session()
    md5_new = md5o.strip()
    logging.debug("%s's md5 in newvm is:%s", path, md5_new)

    if md5_old != md5_new:
        utils_test.libguestfs.cleanup_vm(vt.newvm.name, vt.outdisk)
        raise error.TestFail("Md5 of new vm is not match with old one.")

    utils_test.libguestfs.cleanup_vm(vt.newvm.name, vt.outdisk)


def test_resized_vm(vm, params):
    """
    1) Write a file to oldvm
    2) Resize the olddisk to a newdisk
    3) Check file's md5 in newvm
    """
    # Create a file to oldvm with guestfish
    content = "This is file for resized vm."
    path = params.get("temp_file", "/home/test_resized_vm")
    resize_part_num = params.get("resize_part_num", "2")
    resized_size = params.get("resized_size", "+1G")
    increased_size = params.get("increased_size", "+10G")
    vt = utils_test.libguestfs.VirtTools(vm, params)

    params['libvirt_domain'] = vt.oldvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    old_disk_size = gf.get_part_size(resize_part_num)
    if old_disk_size is None:
        gf.close_session()
        raise error.TestFail("Get part %s size failed." % resize_part_num)
    else:
        old_disk_size = int(old_disk_size)
    if gf.write_file(path, content) is False:
        gf.close_session()
        raise error.TestFail("Create file failed.")
    md5s, md5o = gf.get_md5(path)
    if md5s is False:
        gf.close_session()
        raise error.TestFail(md5o)
    gf.close_session()
    md5_old = md5o.strip()
    logging.debug("%s's md5 in oldvm is:%s", path, md5_old)

    # Create a new file with 2G bigger than old vm's disk
    if vt.indisk is None:
        raise error.TestFail("No disk found for %s" % vt.oldvm.name)
    vt.outdisk = "%s-resize" % vt.indisk
    truncate_from_file(vt.indisk, vt.outdisk, increased_size)

    resizes, resizeo = vt.expand_vm_filesystem(resize_part_num,
                                               resized_size)
    if resizes is False:
        utils_test.libguestfs.cleanup_vm(disk=vt.outdisk)
        raise error.TestFail(resizeo)

    params['disk_img'] = vt.outdisk
    params['libvirt_domain'] = None
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)

    # Check disk's size
    new_disk_size = gf.get_part_size(resize_part_num)
    if new_disk_size is None:
        gf.close_session()
        utils_test.libguestfs.cleanup_vm(disk=vt.outdisk)
        raise error.TestFail("Get part %s size failed." % resize_part_num)
    else:
        new_disk_size = int(new_disk_size)

    real_increased_size = abs(new_disk_size - old_disk_size)
    delta = (real_increased_size - 2147483648) / 2147483648
    if delta > 0.1:
        gf.close_session()
        utils_test.libguestfs.cleanup_vm(disk=vt.outdisk)
        raise error.TestFail("Disk size is not increased to expected value:\n"
                             "Original:%s\n"
                             "New:%s" % (old_disk_size, new_disk_size))

    # Check file's md5 after resize
    md5s, md5o = gf.get_md5(path)
    if md5s is False:
        gf.close_session()
        utils_test.libguestfs.cleanup_vm(disk=vt.outdisk)
        raise error.TestFail(md5o)
    gf.close_session()
    md5_new = md5o.strip()
    logging.debug("%s's md5 in newvm is:%s", path, md5_new)

    if md5_old != md5_new:
        utils_test.libguestfs.cleanup_vm(disk=vt.outdisk)
        raise error.TestFail("Md5 of new vm is not match with old one.")

    utils_test.libguestfs.cleanup_vm(disk=vt.outdisk)


def run_guestfs_operated_disk(test, params, env):
    """
    Test guestfs with operated disk: cloned, spasified, resized
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    operation = params.get("disk_operation")
    eval("test_%s(vm, params)" % operation)
