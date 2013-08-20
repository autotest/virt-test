import logging
import re
from autotest.client.shared import error
from virttest import utils_libguestfs as lgf


class GuestfishTools(lgf.GuestfishPersistent):

    """Useful Tools for Guestfish class."""

    __slots__ = ['params']

    def __init__(self, params):
        """
        Init a persistent guestfish shellsession.
        """
        self.params = params
        disk_img = params.get("disk_img")
        ro_mode = bool(params.get("ro_mode", False))
        libvirt_domain = params.get("libvirt_domain")
        inspector = bool(params.get("inspector", False))
        mount_options = params.get("mount_options")
        super(GuestfishTools, self).__init__(disk_img, ro_mode,
                                             libvirt_domain, inspector,
                                             mount_options=mount_options)

    def get_root(self):
        """
        Get root filesystem w/ guestfish
        """
        getroot_result = self.inspect_os()
        roots_list = getroot_result.stdout.splitlines()
        if getroot_result.exit_status or not len(roots_list):
            logging.error("Get root failed:%s", getroot_result)
            return (False, getroot_result)
        return (True, roots_list[0].strip())


def test_list_with_mount(vm, params):
    """
    1) Fall into guestfish session w/o inspector
    2) Do some necessary check
    3) Try to mount root filesystem to /
    """
    params['libvirt_domain'] = vm.name
    params['inspector'] = False

    gf = GuestfishTools(params)

    # Launch
    run_result = gf.run()
    if run_result.exit_status:
        gf.close_session()
        raise error.TestFail("Can not launch:%s" % run_result)
    logging.info("Launch successfully.")

    # List filesystems
    list_fs_result = gf.list_filesystems()
    if list_fs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List filesystems failed:%s" % list_fs_result)
    logging.info("List filesystems successfully.")

    # List partitions
    list_part_result = gf.list_partitions()
    if list_part_result.exit_status:
        gf.close_session()
        raise error.TestFail("List partitions failed:%s" % list_part_result)
    logging.info("List partitions successfully.")

    # List devices
    list_dev_result = gf.list_devices()
    if list_dev_result.exit_status:
        gf.close_session()
        raise error.TestFail("List devices failed:%s" % list_dev_result)
    logging.info("List devices successfully.")

    # Mount root filesystem
    roots, rooto = gf.get_root()
    if roots is False:
        gf.close_session()
        raise error.TestFail("Can not get root filesystem in guestfish.")
    mount_result = gf.mount(rooto.strip(), "/")
    if mount_result.exit_status:
        gf.close_session()
        raise error.TestFail("Mount filesystem failed:%s" % mount_result)
    logging.debug("Mount filesystem successfully.")

    # List mounts
    list_df_result = gf.df()
    if list_df_result.exit_status:
        gf.close_session()
        raise error.TestFail("Df failed:%s" % list_df_result)
    logging.info("Df successfully.")

    logging.info("###############PASS##############")


def test_list_without_mount(vm, params):
    """
    1) Fall into guestfish session w/o inspector
    2) Do some necessary check
    3) Try to list umounted partitions
    """
    params['libvirt_domain'] = vm.name
    params['inspector'] = False
    gf = GuestfishTools(params)

    # Launch
    run_result = gf.run()
    if run_result.exit_status:
        gf.close_session()
        raise error.TestFail("Can not launch:%s" % run_result)
    logging.info("Launch successfully.")

    # List filesystems
    list_fs_result = gf.list_filesystems()
    if list_fs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List filesystems failed:%s" % list_fs_result)
    logging.info("List filesystems successfully.")

    # List partitions
    list_part_result = gf.list_partitions()
    if list_part_result.exit_status:
        gf.close_session()
        raise error.TestFail("List partitions failed:%s" % list_part_result)
    logging.info("List partitions successfully.")

    # List devices
    list_dev_result = gf.list_devices()
    if list_dev_result.exit_status:
        gf.close_session()
        raise error.TestFail("List devices failed:%s" % list_dev_result)
    logging.info("List devices successfully.")

    # List mounts
    list_df_result = gf.df()
    gf.close_session()
    logging.debug(list_df_result)
    if list_df_result.exit_status == 0:
        raise error.TestFail("Df successfully unexpected.")
    else:
        if not re.search("call.*mount.*first", list_df_result.stdout):
            raise error.TestFail("Unknown error.")
    logging.info("Df failed as expected.")

    logging.info("Test end as expected.")
    logging.info("###############PASS##############")


def test_list_without_launch(vm, params):
    """
    1) Fall into guestfish session w/o inspector
    2) Do some necessary check w/o launch
    3) Try to mount root filesystem to /
    """
    # Get root filesystem before test
    params['libvirt_domain'] = vm.name
    params['inspector'] = True
    gf = GuestfishTools(params)
    roots, rootfs = gf.get_root()
    gf.close_session()
    if roots is False:
        raise error.TestError("Can not get root filesystem "
                              "in guestfish before test")

    params['inspector'] = False
    gf = GuestfishTools(params)

    # Do not launch

    # List filesystems
    list_fs_result = gf.list_filesystems()
    logging.debug(list_fs_result)
    if list_fs_result.exit_status == 0:
        gf.close_session()
        raise error.TestFail("List filesystems successfully")
    else:
        if not re.search("call\slaunch\sbefore", list_fs_result.stdout):
            gf.close_session()
            raise error.TestFail("Unknown error.")

    # List partitions
    list_part_result = gf.list_partitions()
    logging.debug(list_part_result)
    if list_part_result.exit_status == 0:
        gf.close_session()
        raise error.TestFail("List partitions successfully")
    else:
        if not re.search("call\slaunch\sbefore", list_part_result.stdout):
            gf.close_session()
            raise error.TestFail("Unknown error.")

    # List devices
    list_dev_result = gf.list_devices()
    logging.debug(list_dev_result)
    if list_dev_result.exit_status == 0:
        gf.close_session()
        raise error.TestFail("List devices successfully")
    else:
        if not re.search("call\slaunch\sbefore", list_dev_result.stdout):
            gf.close_session()
            raise error.TestFail("Unknown error.")

    # Mount root filesystem
    mount_result = gf.mount(rootfs, "/")
    logging.debug(mount_result)
    gf.close_session()
    if mount_result.exit_status == 0:
        raise error.TestFail("Mount filesystem successfully")
    else:
        if not re.search("call\slaunch\sbefore", mount_result.stdout):
            raise error.TestFail("Unknown error.")

    logging.info("Test end as expected.")
    logging.info("###############PASS##############")


def test_list_with_inspector(vm, params):
    """
    1) Fall into guestfish session w/ mounting root filesystem
    2) Do some necessary check
    """
    # Get root filesystem before test
    params['libvirt_domain'] = vm.name
    params['inspector'] = True
    gf = GuestfishTools(params)
    roots, rootfs = gf.get_root()
    gf.close_session()
    if roots is False:
        raise error.TestError("Can not get root filesystem "
                              "in guestfish before test")

    params['inspector'] = False
    params['mount_options'] = "%s:/" % rootfs
    gf = GuestfishTools(params)

    # List filesystems
    list_fs_result = gf.list_filesystems()
    logging.debug(list_fs_result)
    if list_fs_result.exit_status:
        gf.close_session()
        raise error.TestFail("List filesystems failed")
    logging.info("List filesystems successfully.")

    # List partitions
    list_part_result = gf.list_partitions()
    logging.debug(list_part_result)
    if list_part_result.exit_status:
        gf.close_session()
        raise error.TestFail("List partitions failed")
    logging.info("List partitions successfully.")

    # List devices
    list_dev_result = gf.list_devices()
    logging.debug(list_dev_result)
    if list_dev_result.exit_status:
        gf.close_session()
        raise error.TestFail("List devices failed")
    logging.info("List devices successfully.")

    # List mounts
    list_df_result = gf.df()
    gf.close_session()
    logging.debug(list_df_result)
    if list_df_result.exit_status:
        raise error.TestFail("Df failed")
    logging.info("Df successfully.")

    logging.info("###############PASS##############")


def run_guestfs_list_operations(test, params, env):
    """
    Test guestfs with list commands: list-partitions, list-filesystems
                                     list-devices
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    operation = params.get("list_operation")
    eval("test_%s(vm, params)" % operation)
