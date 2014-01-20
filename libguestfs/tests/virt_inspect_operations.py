import logging
import re
from autotest.client.shared import error
from virttest import virt_vm, remote, utils_test


def test_inspect_get(vm, params):
    """
    Inspect os information with virt-inspector,virt-df,virt-cat...

    1) Get release info with virt-cat
    2) Get filesystems info
    3) Get root, arch, distro, version and mountpoints with virt-inspector
    4) Login to check release info
    """
    vt = utils_test.libguestfs.VirtTools(vm, params)
    is_redhat = "yes" == params.get("is_redhat", "yes")

    # Collect error information
    fail_info = []
    # Cat release info
    release_result = vt.cat("/etc/redhat-release")
    logging.debug(release_result)
    if is_redhat:
        if release_result.exit_status:
            fail_info.append("Get release info failed.")
        else:
            logging.info("Get release info successfully.")

    # List filesystems
    list_fs_result = vt.get_filesystems_info()
    if list_fs_result.exit_status:
        fail_info.append("List filesystems failed")
    else:
        logging.info("List filesystems successfully.")

    # List mountpoints
    df_result = vt.list_df()
    if df_result.exit_status:
        fail_info.append("List mountpoints Failed")
    else:
        logging.info("List mountpoints successfully.")

    # Compare vm information
    # This is a dict include many vm information
    vm_info = vt.get_vm_info_with_inspector()

    # release info
    if is_redhat:
        vm_release = vm_info.get("release")
        if vm_release is None:
            fail_info.append("Get release with inspector failed.")
        elif not release_result.stdout.strip() == vm_release:
            fail_info.append("release do not match.")
        else:
            logging.info("Compare release info successfully.")

    # arch
    vm_arch = vm_info.get("arch")
    if vm_arch is None:
        fail_info.append("Get arch with inspector failed.")
    else:
        logging.info("Get arch successfully:%s", vm_arch)

    # distro
    vm_distro = vm_info.get("distro")
    if vm_distro is None:
        fail_info.append("Get distro with inspector failed.")
    else:
        logging.info("Get distro successfully:%s", vm_distro)

    # filesystems
    vm_filesystems = vm_info.get("filesystems")
    if len(vm_filesystems) == 0:
        fail_info.append("Get filesystems with inspector failed.")
    else:
        list_fs_lines = list_fs_result.stdout.splitlines()
        # kick non-filesystem line out
        for line in list_fs_lines:
            if re.search("filesystem", line):
                list_fs_lines.remove(line)
        for key in vm_filesystems:
            if re.search("mapper", key):
                key = key.split('-')[-1]
            if not re.search(key, str(list_fs_lines)):
                fail_info.append("Listed filesystem %s can not be found."
                                 % key)

    # root
    vm_root = vm_info.get("root")
    if vm_root is None:
        fail_info.append("Get root with inspector failed.")
    else:
        logging.info("Get root successfully:%s", vm_root)

    # hostname
    vm_hostname = vm_info.get("hostname")
    if vm_hostname is None:
        vm_hostname = "unknown"
        fail_info.append("Get hostname with inspector failed.")
    else:
        logging.info("Get hostname successfully:%s", vm_hostname)

    # version
    vm_major_version = vm_info.get("major_version")
    vm_minor_version = vm_info.get("minor_version")
    if vm_major_version is None or vm_minor_version is None:
        fail_info.append("Get version with inspector failed.")
    else:
        if is_redhat:
            vm_version = "%s.%s" % (vm_major_version, vm_minor_version)
        else:
            vm_version = vm_major_version
        if not re.search(vm_version, release_result.stdout):
            fail_info.append("Version do not match:%s" % vm_version)
        logging.info("Get version successfully")

    # mountpoints
    vm_mountpoints = vm_info.get("mountpoints")
    if len(vm_mountpoints) == 0:
        fail_info.append("Get mountpoints with inspector failed.")
    else:
        for mountpoint in vm_mountpoints:
            if re.search("mapper", mountpoint):
                mountpoint = mountpoint.split('-')[-1]
            if not re.search(mountpoint, df_result.stdout):
                fail_info.append("Mountpoint %s do not match." % mountpoint)
        logging.info("Get mountpoints successfully:%s", vm_mountpoints)

    try:
        vm.start()
        session = vm.wait_for_login()
    except (virt_vm.VMError, remote.LoginError), detail:
        vm.destroy()
        raise error.TestFail(str(detail))

    try:
        if is_redhat:
            release_output = session.cmd_output("cat /etc/redhat-release")
            logging.debug(release_output)
            if release_output.strip() != release_result.stdout.strip():
                fail_info.append("release in vm do not match.")
        hostname_output = session.cmd_output("hostname")
        logging.debug("VM hostname:%s", hostname_output)
        if not re.search(hostname_output.strip(), vm_hostname):
            fail_info.append("hostname in vm do not match.")
        df_output = session.cmd_output("df")
        logging.debug("VM mountpoints:%s", df_output)
        for mountpoint in vm_mountpoints:
            # libguestfs will convert all vdx|hdx|sdx to sdx
            if re.search("/dev/sd", mountpoint):
                mountpoint = re.sub(r"/dev/sd", r"/dev/.d", mountpoint)
            if not re.search(mountpoint, df_output):
                fail_info.append("mountpoints %s in vm do not match."
                                 % mountpoint)
        vm.destroy()
        vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError), detail:
        if vm.is_alive():
            vm.destroy()

    if len(fail_info):
        raise error.TestFail(fail_info)


def run_virt_inspect_operations(test, params, env):
    """
    Test libguestfs with virt-inspect command.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    operation = params.get("vt_inspect_operation")
    testcase = globals()["test_%s" % operation]
    testcase(vm, params)
