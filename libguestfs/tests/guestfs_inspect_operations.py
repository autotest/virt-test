import logging
import re
from autotest.client.shared import error
from virttest import virt_vm, remote
from virttest import utils_libguestfs as lgf


class GuestfishTools(lgf.GuestfishPersistent):

    """Useful Tools for Guestfish class."""

    __slots__ = lgf.GuestfishPersistent.__slots__ + ('params', )

    def __init__(self, params):
        """
        Init a persistent guestfish shellsession.
        """
        self.params = params
        disk_img = params.get("disk_img")
        ro_mode = bool(params.get("gf_ro_mode", False))
        libvirt_domain = params.get("libvirt_domain")
        inspector = bool(params.get("gf_inspector", False))
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

    def analyse_release(self):
        """
        Analyse /etc/redhat-release
        """
        logging.info("Analysing /etc/redhat-release...")
        release_result = self.cat("/etc/redhat-release")
        logging.debug(release_result)
        if release_result.exit_status:
            logging.error("Cat /etc/redhat-release failed")
            return (False, release_result)

        release_type = {'rhel': "Red Hat Enterprise Linux",
                        'fedora': "Fedora"}
        for key in release_type:
            if re.search(release_type[key], release_result.stdout):
                return (True, key)


def test_inspect_get(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Get release info
    3) Get filesystems info
    4) Get root, arch, distro, version and mountpoints
    5) Login to get release info
    """
    is_redhat = "yes" == params.get("is_redhat", "yes")

    params['libvirt_domain'] = vm.name
    params['gf_inspector'] = True
    gf = GuestfishTools(params)
    roots, rootfs = gf.get_root()
    logging.debug("Root filesystem:%s", rootfs)
    # inspect-os will umount filesystems,reopen it later
    gf.close_session()
    if roots is False:
        raise error.TestError("Can not get root filesystem "
                              "in guestfish before test")

    fail_info = []
    gf = GuestfishTools(params)

    # List filesystems
    list_fs_result = gf.list_filesystems()
    logging.debug(list_fs_result)
    if list_fs_result.exit_status:
        fail_info.append("List filesystems failed")
    else:
        logging.info("List filesystems successfully.")

    # List mountpoints
    mp_result = gf.mountpoints()
    logging.debug(mp_result)
    if mp_result.exit_status:
        fail_info.append("List mountpoints Failed")
    else:
        logging.info("List mountpoints successfully.")

    if is_redhat:
        releases, releaseo = gf.analyse_release()
        if releases is False:
            fail_info.append("Get release info failed.")
        else:
            logging.info("Get release info successfully.")

    # Get root partition and compare with got rootfs
    getroot_result = gf.inspect_get_roots()
    logging.debug(getroot_result)
    if getroot_result.exit_status:
        fail_info.append("Get root with inspect-get-roots failed.")
    elif not re.search(rootfs, str(getroot_result.stdout)):
        fail_info.append("Something wrong with got roots.")
    else:
        logging.info("Get root successfully.")

    # Get arch
    arch_result = gf.inspect_get_arch(rootfs)
    logging.debug(arch_result)
    if arch_result.exit_status:
        fail_info.append("Get arch of %s failed." % rootfs)
    else:
        logging.info("Get arch successfully.")

    # Get distro
    distro_result = gf.inspect_get_distro(rootfs)
    logging.debug(distro_result)
    if distro_result.exit_status:
        fail_info.append("Get distro of %s failed." % rootfs)
    elif is_redhat:
        if str(releaseo) != distro_result.stdout.strip():
            fail_info.append("Got distro do not match.")
    else:
        logging.info("Get distro successfully.")

    # Get filesystems
    fs_result = gf.inspect_get_filesystems(rootfs)
    logging.debug(fs_result)
    if fs_result.exit_status:
        fail_info.append("Get filesystems of %s failed." % rootfs)
    else:
        logging.info("Get filesystems successfully.")

    # Get hostname
    hn_result = gf.inspect_get_hostname(rootfs)
    logging.debug(hn_result)
    if hn_result.exit_status:
        fail_info.append("Get hostname of %s failed." % rootfs)
    else:
        logging.info("Get hostname successfully")

    # Get os version
    majorv_result = gf.inspect_get_major_version(rootfs)
    logging.debug(majorv_result)
    if majorv_result.exit_status:
        fail_info.append("Get major version of %s failed." % rootfs)
    else:
        logging.info("Get major version successfully")

    minorv_result = gf.inspect_get_minor_version(rootfs)
    logging.debug(minorv_result)
    if minorv_result.exit_status:
        fail_info.append("Get minor version of %s failed." % rootfs)
    else:
        logging.info("Get minor version successfully.")

    # Get rootfs mountpoints
    rmp_result = gf.inspect_get_mountpoints(rootfs)
    logging.debug(rmp_result)
    if rmp_result.exit_status:
        fail_info.append("Get mountpoints of %s failed." % rootfs)
    else:
        logging.info("Get mountpoints successfully.")

    gf.close_session()

    try:
        vm.start()
        session = vm.wait_for_login()
    except (virt_vm.VMError, remote.LoginError), detail:
        vm.destroy()
        raise error.TestFail(str(detail))

    try:
        uname2 = session.cmd_output("uname -a")
        logging.debug(uname2)
        vm.destroy()
        vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError), detail:
        if vm.is_alive():
            vm.destroy()

    if not re.search(arch_result.stdout.strip(), uname2):
        fail_info.append("Got arch do not match.")

    if len(fail_info):
        raise error.TestFail(fail_info)

    logging.info("###############PASS##############")


def run_guestfs_inspect_operations(test, params, env):
    """
    Test guestfs with inspect commands: inspect-*
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    operation = params.get("gf_inspect_operation")
    testcase = globals()["test_%s" % operation]
    testcase(vm, params)
