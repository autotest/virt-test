"""
rv_build_install.py - Builds and installs packages specified
                      using the build_install.py script

Requires: connected binaries remote-viewer, Xorg, gnome session, git

"""
import logging
import os
import time
import re
from autotest.client.shared import error
from virttest.aexpect import ShellCmdError
from virttest import utils_misc, utils_spice


def connect_to_vm(vm_name, env, params):
    """
    Connects to VM and powers it on and gets session information

    :param vm_name: name of VM to connect to
    :param params: Dictionary with test parameters.
    :param env: Test environment.
    """

    vm = env.get_vm(params[vm_name + "_vm"])
    vm.verify_alive()
    vm_root_session = vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)),
        username="root", password="123456")
    logging.info("VM %s is up and running" % vm_name)
    return (vm, vm_root_session)

def install_req_pkgs(pkgsRequired, vm_root_session, params):
    """
    Checks to see if packages are installed and if not, installs the package

    :params rpms_to_install: List of packages to check
    :params vm_root_session: Session object of VM
    :param params: Dictionary with test parameters.
    """

    for pkgName in pkgsRequired:
        logging.info("Checking to see if %s is installed" % pkgName)
        try:
            vm_root_session.cmd("rpm -q %s" % pkgName)
        except ShellCmdError:
            rpm = params.get(re.sub("-", "_", pkgName) + "_url")
            logging.info("Installing %s" % pkgName)
            try:
                vm_root_session.cmd("yum -y localinstall %s" % rpm, timeout=300)
            except ShellCmdError:
                logging.info("Could not install %s" % pkgName)

def build_install_qxl(vm_root_session, vm_script_path, params):
    """
    Build and install QXL in the VM

    :param vm_root_session:  VM Session object.
    :param vm_script_path: path where to find build_install.py script
    :param params: Dictionary with test parameters.
    """

    # Checking to see if required packages exist and if not, install them
    pkgsRequired = ["libpciaccess-devel", "xorg-x11-util-macros",
                    "xorg-x11-server-devel"]
    install_req_pkgs(pkgsRequired, vm_root_session, params)

    # latest spice-protocol is required to build qxl
    output = vm_root_session.cmd("%s -p spice-protocol" % (vm_script_path))
    logging.info(output)
    if re.search("Return code", output):
        raise error.TestFail("spice-protocol was not installed properly")

    output = vm_root_session.cmd("%s -p xf86-video-qxl" % (vm_script_path))
    logging.info(output)
    if re.search("Return code", output):
        raise error.TestFail("qxl was not installed properly")

def build_install_spicegtk(vm_root_session, vm_script_path, params):
    """
    Build and install spice-gtk in the VM

    :param vm_root_session:  VM Session object.
    :param vm_script_path: path where to find build_install.py script
    :param params: Dictionary with test parameters.
    """

    # Get version of spice-gtk before install
    try:
        output = vm_root_session.cmd("LD_LIBRARY_PATH=/usr/local/lib"
                                     " remote-viewer --spice-gtk-version")
        logging.info(output)
    except ShellCmdError:
        logging.error(output)

    pkgsRequired = ["libogg-devel", "celt051-devel", "libcacard-devel"]
    install_req_pkgs(pkgsRequired, vm_root_session, params)

    utils_spice.deploy_epel_repo(vm_root_session, params)

    try:
        output = vm_root_session.cmd("yum -y install perl-Text-CSV pyparsing",
                                     timeout=300)
        logging.info(output)
    except ShellCmdError:
        logging.error(output)

    # latest spice-protocol is required to build qxl
    output = vm_root_session.cmd("%s -p spice-protocol" % (vm_script_path))
    logging.info(output)
    if re.search("Return code", output):
        raise error.TestFail("spice-protocol was not installed properly")

    output = vm_root_session.cmd("%s -p spice-gtk" % (vm_script_path),
                                 timeout=300)
    logging.info(output)
    if re.search("Return code", output):
        raise error.TestFail("spice-gtk was not installed properly")

    # Get version of spice-gtk after install
    try:
        output = vm_root_session.cmd("LD_LIBRARY_PATH=/usr/local/lib"
                                     " remote-viewer --spice-gtk-version")
        logging.info(output)
    except ShellCmdError:
        logging.error(output)

def build_install_vdagent(vm_root_session, vm_script_path, params):
    """
    Build and install spice-vdagent in the VM

    :param vm_root_session: VM Session object.
    :param vm_script_path: path where to find build_install.py script
    :param params: Dictionary with test parameters.
    """

    # Get current version of spice-vdagent
    try:
        output = vm_root_session.cmd("spice-vdagent -h")
        logging.info(output)
    except ShellCmdError:
        logging.error(output)

    pkgsRequired = ["libpciaccess-devel"]
    install_req_pkgs(pkgsRequired, vm_root_session, params)

    # latest spice-protocol is required to build vdagent
    output = vm_root_session.cmd("%s -p spice-protocol" % (vm_script_path))
    logging.info(output)
    if re.search("Return code", output):
        raise error.TestFail("spice-protocol was not installed properly")

    output = vm_root_session.cmd("%s -p spice-vd-agent" % (vm_script_path))
    logging.info(output)
    if re.search("Return code", output):
        raise error.TestFail("spice-vd-agent was not installed properly")

    # Restart vdagent
    try:
        output = vm_root_session.cmd("service spice-vdagentd restart")
        logging.info(output)
        if re.search("fail", output, re.IGNORECASE):
            raise error.TestFail("spice-vd-agent was not started properly")
    except ShellCmdError:
        raise error.TestFail("spice-vd-agent was not started properly")

    # Get version number of spice-vdagent
    try:
        output = vm_root_session.cmd("spice-vdagent -h")
        logging.info(output)
    except ShellCmdError:
        logging.error(output)

def run_rv_build_install(test, params, env):
    """
    Build and install packages from git on the client or guest VM

    Supported configurations:
    build_install_pkg: name of the package to get from git, build and install

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    # Collect test parameters
    pkgName = params.get("build_install_pkg")
    script = params.get("script")
    vm_name = params.get("vm_name")
    dst_dir = params.get("dst_dir")

    # Path of the script on the VM
    vm_script_path = os.path.join(dst_dir, script)

    # Get root session for the VM
    (vm, vm_root_session) = connect_to_vm(vm_name, env, params)

    # The following is to copy build_install.py script to the VM and do the test
    scriptdir = os.path.join("deps", script)

    # location of the script on the host
    host_script_path = utils_misc.get_path(test.virtdir, scriptdir)

    logging.info("Transferring the script to %s,"
                 "destination directory: %s, source script location: %s",
                 vm_name, vm_script_path, host_script_path)

    vm.copy_files_to(host_script_path, vm_script_path, timeout=60)
    time.sleep(5)

    # Run build_install.py script
    if pkgName == "xf86-video-qxl":
        build_install_qxl(vm_root_session, vm_script_path, params)
    elif pkgName == "spice-vd-agent":
        build_install_vdagent(vm_root_session, vm_script_path, params)
    elif pkgName == "spice-gtk":
        build_install_spicegtk(vm_root_session, vm_script_path, params)
    else:
        logging.info("Not supported right now")
        raise error.TestFail("Incorrect Test_Setup")

    utils_spice.clear_interface(vm)
