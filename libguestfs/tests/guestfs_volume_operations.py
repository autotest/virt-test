import re
import os
import logging
from autotest.client.shared import error, utils
from virttest import virt_vm, data_dir, remote, aexpect
from virttest import utils_test


def prepare_attached_device(guestfs, device):
    """
    Prepare attached device for block test.

    :param guestfs: instance of GuestfishTools
    :param device: attached device
    """
    # List devices
    list_dev_result = guestfs.list_devices()
    logging.debug(list_dev_result)
    if list_dev_result.exit_status:
        guestfs.close_session()
        raise error.TestFail("List devices failed")
    else:
        if not re.search(device, list_dev_result.stdout):
            guestfs.close_session()
            raise error.TestFail("Did not find additional device.")
    logging.info("List devices successfully.")

    creates, createo = guestfs.create_msdos_part(device)
    if creates is False:
        guestfs.close_session()
        raise error.TestFail(createo)
    logging.info("Create partition successfully.")
    return "%s%s" % (device, createo)


def test_create_vol_group(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-add
    4) Create a volume group
    5) Check volume group in guestfish with vgs
    6) Login vm to check whether volume group is ok
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_gf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                             ignore_status=True).stdout.strip()

    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    part_name = prepare_attached_device(gf, device_in_gf)

    groupname = params.get("gf_volume_group_name", "VolGroupTest")
    vgcreate_result = gf.vgcreate(groupname, part_name)
    logging.info(vgcreate_result)
    if vgcreate_result.exit_status:
        gf.close_session()
        raise error.TestFail("Create volume group failed.")
    logging.info("Create volume group successfully.")

    vgs_result = gf.vgs()
    gf.close_session()
    logging.info(vgs_result)
    if vgs_result.exit_status:
        raise error.TestFail("List volume groups failed.")
    else:
        if not re.search(groupname, vgs_result.stdout):
            raise error.TestFail("Can't get volume group %s." % groupname)
    logging.info("Got volume group %s", groupname)

    attached_vm = vt.newvm
    try:
        attached_vm.start()
        session = attached_vm.wait_for_login()
        if session.cmd_status("which vgs"):
            logging.error("Did not find command 'vgs' in guest, SKIP...")
            attached_vm.destroy()
            attached_vm.wait_for_shutdown()
            return
    except (virt_vm.VMError, remote.LoginError), detail:
        attached_vm.destroy()
        raise error.TestFail(str(detail))

    try:
        vgs = session.cmd_output("vgs --all", timeout=5)
        logging.debug(vgs)
        attached_vm.destroy()
        attached_vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError), detail:
        if attached_vm.is_alive():
            attached_vm.destroy()
        raise error.TestFail(str(detail))

    if not re.search("\s%s\s" % groupname, vgs):
        raise error.TestFail("Get volume group %s in vm failed" % groupname)
    logging.info("Get volume group %s in guest.", groupname)


def test_rename_vol_group(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-add
    4) Create a volume group
    5) Check volume group in guestfish with vgs
    6) Rename volume group
    7) Login vm to check whether volume group is ok
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_gf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                             ignore_status=True).stdout.strip()

    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    part_name = prepare_attached_device(gf, device_in_gf)

    groupname = params.get("gf_volume_group_name", "VolGroupTest")
    vgcreate_result = gf.vgcreate(groupname, part_name)
    logging.info(vgcreate_result)
    if vgcreate_result.exit_status:
        gf.close_session()
        raise error.TestFail("Create volume group failed.")
    logging.info("Create volume group successfully.")

    vgs_result = gf.vgs()
    logging.info(vgs_result)
    if vgs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List volume groups failed.")
    else:
        if not re.search(groupname, vgs_result.stdout):
            gf.close_session()
            raise error.TestFail("Can't get volume group %s." % groupname)
    logging.info("Got volume group %s", groupname)

    newgroupname = "%sRename" % groupname
    vgrename_result = gf.vgrename(groupname, newgroupname)
    gf.close_session()
    logging.info(vgrename_result)
    if vgrename_result.exit_status:
        raise error.TestFail("Rename volume group failed.")
    logging.info("Rename volume group %s successfully", groupname)

    attached_vm = vt.newvm
    try:
        attached_vm.start()
        session = attached_vm.wait_for_login()
        if session.cmd_status("which vgs"):
            logging.error("Did not find command 'vgs' in guest, SKIP...")
            attached_vm.destroy()
            attached_vm.wait_for_shutdown()
            return
    except (virt_vm.VMError, remote.LoginError), detail:
        attached_vm.destroy()
        raise error.TestFail(str(detail))

    try:
        vgs = session.cmd_output("vgs --all", timeout=5)
        logging.debug(vgs)
        attached_vm.destroy()
        attached_vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError), detail:
        if attached_vm.is_alive():
            attached_vm.destroy()
        raise error.TestFail(str(detail))

    if not re.search("\s%s\s" % newgroupname, str(vgs)):
        raise error.TestFail("Get volume group %s in vm failed" % newgroupname)
    logging.info("Get volume group %s in guest.", newgroupname)


def test_remove_vol_group(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-add
    4) Create a volume group
    5) Check volume group exist in guestfish with vgs
    6) Remove created volume group
    7) Check volume group not exist in guestfish with vgs
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_gf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                             ignore_status=True).stdout.strip()

    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    part_name = prepare_attached_device(gf, device_in_gf)

    groupname = params.get("gf_volume_group_name", "VolGroupTest")
    vgcreate_result = gf.vgcreate(groupname, part_name)
    logging.info(vgcreate_result)
    if vgcreate_result.exit_status:
        gf.close_session()
        raise error.TestFail("Create volume group failed.")
    logging.info("Create volume group successfully.")

    vgs_result = gf.vgs()
    logging.info(vgs_result)
    if vgs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List volume groups failed.")
    else:
        if not re.search(groupname, vgs_result.stdout):
            gf.close_session()
            raise error.TestFail("Can't get volume group %s." % groupname)
    logging.info("Got volume group %s", groupname)

    vgremove_result = gf.vgremove(groupname)
    logging.info(vgremove_result)
    if vgremove_result.exit_status:
        gf.close_session()
        raise error.TestFail("Remove volume group failed.")
    logging.info("Remove volume group %s successfully", groupname)

    vgs_result = gf.vgs()
    logging.info(vgs_result)
    gf.close_session()
    if vgs_result.exit_status:
        raise error.TestFail("List volume groups failed.")
    else:
        if re.search(groupname, vgs_result.stdout):
            raise error.TestFail("Are you sure volume group %s deleted "
                                 "successfully?" % groupname)
    logging.info("Volume group %s did not deleted as expected!", groupname)


def test_create_volume(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-add
    4) Create a volume group
    5) Create a volume in created volume group
    6) Get volume infomation with lvxxx commands
    7) Login vm to check whether volume is ok
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_gf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                             ignore_status=True).stdout.strip()

    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    part_name = prepare_attached_device(gf, device_in_gf)

    groupname = params.get("gf_volume_group_name", "VolGroupTest")
    vgcreate_result = gf.vgcreate(groupname, part_name)
    logging.info(vgcreate_result)
    if vgcreate_result.exit_status:
        gf.close_session()
        raise error.TestFail("Create volume group failed.")
    logging.info("Create volume group successfully.")

    vgs_result = gf.vgs()
    logging.info(vgs_result)
    if vgs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List volume groups failed.")
    else:
        if not re.search(groupname, vgs_result.stdout):
            gf.close_session()
            raise error.TestFail("Can't get volume group %s." % groupname)
    logging.info("Got volume group %s", groupname)

    volumename = params.get("gf_volume_name", "VolTest")
    lv_device = "/dev/%s/%s" % (groupname, volumename)
    volumesize = params.get("gf_volume_size", "40")
    lvcreate_result = gf.lvcreate(volumename, groupname, volumesize)
    logging.info(lvcreate_result)
    if lvcreate_result.exit_status:
        gf.close_session()
        raise error.TestFail("Create volume failed.")
    logging.info("Create volume successfully.")

    lvs_result = gf.lvs()
    logging.info(lvs_result)
    if lvs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List volume groups failed.")
    else:
        if not re.search(volumename, lvs_result.stdout):
            gf.close_session()
            raise error.TestFail("Can't get volume %s." % volumename)
    logging.info("Got volume %s", volumename)

    lvuuid_result = gf.lvuuid(lv_device)
    logging.debug(lvuuid_result)
    if lvuuid_result.exit_status:
        gf.close_session()
        raise error.TestFail("Get volume uuid failed.")
    logging.info("Get volume uuid successfully.")

    canon_lv_name_result = gf.lvm_canonical_lv_name(lv_device)
    logging.debug(canon_lv_name_result)
    gf.close_session()
    if canon_lv_name_result.exit_status:
        raise error.TestFail("Get canonical volume name failed.")
    logging.info("Get canonical volume name successfully.")

    attached_vm = vt.newvm
    try:
        attached_vm.start()
        session = attached_vm.wait_for_login()
        if session.cmd_status("which lvs"):
            logging.error("Did not find command 'lvs' in guest, SKIP...")
            attached_vm.destroy()
            attached_vm.wait_for_shutdown()
            return
    except (virt_vm.VMError, remote.LoginError), detail:
        attached_vm.destroy()
        raise error.TestFail(str(detail))

    try:
        lvs = session.cmd_output("lvs --all", timeout=5)
        logging.debug(lvs)
        attached_vm.destroy()
        attached_vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError), detail:
        if attached_vm.is_alive():
            attached_vm.destroy()
        raise error.TestFail(str(detail))

    if not re.search("\s%s\s" % volumename, lvs):
        raise error.TestFail("Get volume %s in vm failed" % volumename)
    logging.info("Get volume %s in guest.", volumename)


def test_delete_volume(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-add
    4) Create a volume group
    5) Create a volume in created volume group
    6) Delete created volume
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_gf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                             ignore_status=True).stdout.strip()

    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    part_name = prepare_attached_device(gf, device_in_gf)

    groupname = params.get("gf_volume_group_name", "VolGroupTest")
    vgcreate_result = gf.vgcreate(groupname, part_name)
    logging.info(vgcreate_result)
    if vgcreate_result.exit_status:
        gf.close_session()
        raise error.TestFail("Create volume group failed.")
    logging.info("Create volume group successfully.")

    vgs_result = gf.vgs()
    logging.info(vgs_result)
    if vgs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List volume groups failed.")
    else:
        if not re.search(groupname, vgs_result.stdout):
            gf.close_session()
            raise error.TestFail("Can't get volume group %s." % groupname)
    logging.info("Got volume group %s", groupname)

    volumename = params.get("gf_volume_name", "VolTest")
    lv_device = "/dev/%s/%s" % (groupname, volumename)
    volumesize = params.get("gf_volume_size", "40")
    lvcreate_result = gf.lvcreate(volumename, groupname, volumesize)
    logging.info(lvcreate_result)
    if lvcreate_result.exit_status:
        gf.close_session()
        raise error.TestFail("Create volume failed.")
    logging.info("Create volume successfully.")

    lvs_result = gf.lvs()
    logging.info(lvs_result)
    if lvs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List volume groups failed.")
    else:
        if not re.search(volumename, lvs_result.stdout):
            gf.close_session()
            raise error.TestFail("Can't get volume %s." % volumename)
    logging.info("Got volume %s", volumename)

    lvremove_result = gf.lvremove(lv_device)
    logging.info(lvremove_result)
    if lvremove_result.exit_status:
        gf.close_session()
        raise error.TestFail("Remove volume failed.")
    logging.info("Remove volume successfully.")

    lvs_result = gf.lvs()
    logging.info(lvs_result)
    gf.close_session()
    if lvs_result.exit_status:
        raise error.TestFail("List volume groups failed.")
    else:
        if re.search(volumename, lvs_result.stdout):
            raise error.TestFail("Are you sure volume %s removed as "
                                 "expected?" % volumename)


def test_shrink_volume(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-add
    4) Create a volume group
    5) Create a volume in created volume group
    6) Format volume device
    7) Login vm to dd a image file and get md5 value
    8) Refall into guestfish session w/ inspector
    9) Shrink volume size
    10) Try to get md5 again
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_gf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                             ignore_status=True).stdout.strip()

    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    part_name = prepare_attached_device(gf, device_in_gf)

    groupname = params.get("gf_volume_group_name", "VolGroupTest")
    vgcreate_result = gf.vgcreate(groupname, part_name)
    logging.info(vgcreate_result)
    if vgcreate_result.exit_status:
        gf.close_session()
        raise error.TestFail("Create volume group failed.")
    logging.info("Create volume group successfully.")

    vgs_result = gf.vgs()
    logging.info(vgs_result)
    if vgs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List volume groups failed.")
    else:
        if not re.search(groupname, vgs_result.stdout):
            gf.close_session()
            raise error.TestFail("Can't get volume group %s." % groupname)
    logging.info("Got volume group %s", groupname)

    volumename = params.get("gf_volume_name", "VolTest")
    lv_device = "/dev/%s/%s" % (groupname, volumename)
    volumesize = params.get("gf_volume_size", "40")
    lvcreate_result = gf.lvcreate(volumename, groupname, volumesize)
    logging.info(lvcreate_result)
    if lvcreate_result.exit_status:
        gf.close_session()
        raise error.TestFail("Create volume failed.")
    logging.info("Create volume successfully.")

    lvs_result = gf.lvs()
    logging.info(lvs_result)
    if lvs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List volume groups failed.")
    else:
        if not re.search(volumename, lvs_result.stdout):
            gf.close_session()
            raise error.TestFail("Can't get volume %s." % volumename)
    logging.info("Got volume %s", volumename)

    mkfs_result = gf.mkfs("ext3", lv_device)
    logging.debug(mkfs_result)
    gf.close_session()
    if mkfs_result.exit_status:
        raise error.TestFail("Format %s Failed" % lv_device)
    logging.info("Format %s successfully.", lv_device)

    attached_vm = vt.newvm
    try:
        attached_vm.start()
        session = attached_vm.wait_for_login()
        if session.cmd_status("which vgs"):
            attached_vm.destroy()
            attached_vm.wait_for_shutdown()
            raise error.TestNAError("Can not use volume group in guest,"
                                    "SKIP THIS CASE...")
    except (virt_vm.VMError, remote.LoginError), detail:
        attached_vm.destroy()
        raise error.TestFail(str(detail))

    mountpoint = params.get("gf_mountpoint", "/mnt")
    file_path = "%s/test_shrink_volume.img" % mountpoint
    try:
        dd_size1 = int(volumesize)/2
        logging.debug(session.cmd_output("ls /dev/"))
        status, output = session.cmd_status_output("mount %s %s" % (lv_device,
                                                   mountpoint), timeout=10)
        if status:
            raise utils_test.libguestfs.VTMountError("", output)
        else:
            output = session.cmd_output("df", timeout=10)
            logging.debug(output)
            if not re.search(mountpoint, str(output)):
                raise utils_test.libguestfs.VTMountError("df", output)
        output = session.cmd_output("dd if=/dev/zero of=%s bs=1M "
                                    "count=%s" % (file_path, dd_size1),
                                    timeout=5)
        logging.debug(output)
        md51 = session.cmd_output("md5sum %s" % file_path)
        logging.debug(md51)
        attached_vm.destroy()
        attached_vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError,
            utils_test.libguestfs.VTMountError), detail:
        if attached_vm.is_alive():
            attached_vm.destroy()
        raise error.TestFail(str(detail))

    gf = utils_test.libguestfs.GuestfishTools(params)

    size2 = int(volumesize)/2 - 5
    lvresize_result = gf.lvresize(lv_device, size2)
    logging.debug(lvresize_result)
    if lvresize_result.exit_status:
        gf.close_session()
        raise error.TestFail("Resize volume %s failed." % lv_device)
    logging.info("Resize %s successfully", lv_device)

    mount_result = gf.mount(lv_device, mountpoint)
    logging.debug(mount_result)
    if mount_result.exit_status:
        gf.close_session()
        raise error.TestFail("Mount %s Failed" % lv_device)
    logging.info("Mount %s successfully.", lv_device)

    # List mounts
    list_df_result = gf.df()
    logging.debug(list_df_result)
    if list_df_result.exit_status:
        gf.close_session()
        raise error.TestFail("Df failed")
    else:
        if not re.search(volumename, list_df_result.stdout):
            gf.close_session()
            raise error.TestFail("Did not find mounted device.")
    logging.info("Df successfully.")

    md5s, md5o = gf.get_md5(file_path)
    logging.debug(md5o)
    gf.close_session()
    if md5s is True:
        if re.search(md5o, md51):
            raise error.TestFail("Got same md5 after shrinking volume.")
        raise error.TestFail("Get md5 successfully, but not expected.")
    logging.info("Did not get md5 as expected.")


def test_expand_volume(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-add
    4) Create a volume group
    5) Create a volume in created volume group
    6) Format volume device
    7) Login vm to dd a image file and get md5 value
    8) Refall into guestfish session w/ inspector
    9) Expand volume size
    10) Try to get md5 again
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_gf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                             ignore_status=True).stdout.strip()

    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    part_name = prepare_attached_device(gf, device_in_gf)

    groupname = params.get("gf_volume_group_name", "VolGroupTest")
    vgcreate_result = gf.vgcreate(groupname, part_name)
    logging.info(vgcreate_result)
    if vgcreate_result.exit_status:
        gf.close_session()
        raise error.TestFail("Create volume group failed.")
    logging.info("Create volume group successfully.")

    vgs_result = gf.vgs()
    logging.info(vgs_result)
    if vgs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List volume groups failed.")
    else:
        if not re.search(groupname, vgs_result.stdout):
            gf.close_session()
            raise error.TestFail("Can't get volume group %s." % groupname)
    logging.info("Got volume group %s", groupname)

    volumename = params.get("gf_volume_name", "VolTest")
    lv_device = "/dev/%s/%s" % (groupname, volumename)
    volumesize = params.get("gf_volume_size", "40")
    lvcreate_result = gf.lvcreate(volumename, groupname, volumesize)
    logging.info(lvcreate_result)
    if lvcreate_result.exit_status:
        gf.close_session()
        raise error.TestFail("Create volume failed.")
    logging.info("Create volume successfully.")

    lvs_result = gf.lvs()
    logging.info(lvs_result)
    if lvs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List volume groups failed.")
    else:
        if not re.search(volumename, lvs_result.stdout):
            gf.close_session()
            raise error.TestFail("Can't get volume %s." % volumename)
    logging.info("Got volume %s", volumename)

    mkfs_result = gf.mkfs("ext3", lv_device)
    logging.debug(mkfs_result)
    gf.close_session()
    if mkfs_result.exit_status:
        raise error.TestFail("Format %s Failed" % lv_device)
    logging.info("Format %s successfully.", lv_device)

    attached_vm = vt.newvm
    try:
        attached_vm.start()
        session = attached_vm.wait_for_login()
        if session.cmd_status("which vgs"):
            attached_vm.destroy()
            attached_vm.wait_for_shutdown()
            raise error.TestNAError("Can not use volume group in guest,"
                                    "SKIP THIS CASE...")
    except (virt_vm.VMError, remote.LoginError), detail:
        attached_vm.destroy()
        raise error.TestFail(str(detail))

    mountpoint = params.get("gf_mountpoint", "/mnt")
    file_path = "%s/test_expand_volume.img" % mountpoint
    try:
        dd_size1 = int(volumesize)/2
        status, output = session.cmd_status_output("mount %s %s" % (lv_device,
                                                   mountpoint), timeout=20)
        if status:
            raise utils_test.libguestfs.VTMountError("", output)
        else:
            output = session.cmd_output("df", timeout=10)
            logging.debug(output)
            if not re.search(mountpoint, str(output)):
                raise utils_test.libguestfs.VTMountError("df", output)
        output = session.cmd_output("dd if=/dev/zero of=%s bs=1M "
                                    "count=%s" % (file_path, dd_size1),
                                    timeout=5)
        logging.debug(output)
        md51 = session.cmd_output("md5sum %s" % file_path)
        logging.debug("Original md5:%s", md51)
        attached_vm.destroy()
        attached_vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError,
            utils_test.libguestfs.VTMountError), detail:
        if attached_vm.is_alive():
            attached_vm.destroy()
        raise error.TestFail(str(detail))

    gf = utils_test.libguestfs.GuestfishTools(params)

    size2 = int(volumesize) + 5
    lvresize_result = gf.lvresize(lv_device, size2)
    logging.debug(lvresize_result)
    if lvresize_result.exit_status:
        gf.close_session()
        raise error.TestFail("Resize volume %s failed." % lv_device)
    logging.info("Resize %s successfully", lv_device)

    mount_result = gf.mount(lv_device, mountpoint)
    logging.debug(mount_result)
    if mount_result.exit_status:
        gf.close_session()
        raise error.TestFail("Mount %s Failed" % lv_device)
    logging.info("Mount %s successfully.", lv_device)

    # List mounts
    list_df_result = gf.df()
    logging.debug(list_df_result)
    if list_df_result.exit_status:
        gf.close_session()
        raise error.TestFail("Df failed")
    else:
        if not re.search(volumename, list_df_result.stdout):
            gf.close_session()
            raise error.TestFail("Did not find mounted device.")
    logging.info("Df successfully.")

    md5s, md5o = gf.get_md5(file_path)
    logging.debug("Current md5:%s", md5o)
    gf.close_session()
    if md5s is False:
        raise error.TestFail("Get md5 failed.")
    else:
        if not re.search(md5o, md51):
            raise error.TestFail("Got different md5 after expanding volume.")
    logging.info("Get correct md5 as expected.")


def run(test, params, env):
    """
    Test guestfs with volume commands.
    """
    vm_name = params.get("main_vm")
    new_vm_name = params.get("gf_updated_new_vm")
    vm = env.get_vm(vm_name)

    # To make sure old vm is down
    if vm.is_alive():
        vm.destroy()

    operation = params.get("gf_volume_operation")
    testcase = globals()["test_%s" % operation]
    try:
        # Create a new vm for editing and easier cleanup :)
        utils_test.libguestfs.define_new_vm(vm_name, new_vm_name)
        testcase(vm, params)
    finally:
        # Delete created image file
        disk_path = os.path.join(data_dir.get_tmp_dir(),
                                 params.get("gf_updated_target_dev", "vdb"))
        utils_test.libguestfs.cleanup_vm(new_vm_name, disk_path)
