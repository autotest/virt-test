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
from virttest import utils_misc, utils_spice, aexpect
from qemu.tests import rv_clearx, rv_input


def connect_to_vm(vm_name, env, params):
    """
    Connects to VM and powers it on and gets session information

    @param vm_name: name of VM to connect to
    @param params: Dictionary with test parameters.
    @param env: Test environment.
    """

    vm = env.get_vm(params[vm_name + "_vm"])
    vm.verify_alive()
    vm_root_session = vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)),
        username="root", password="123456")
    logging.info("VM %s is up and running" % vm_name)
    return (vm, vm_root_session)


def install_rpms(rpms_to_install, vm_root_session):
    """
    Fetches rpm and installs it

    @params rpms_to_install: List of rpms to install
    @params vm_root_session: Session object of VM
    """

    for rpm in rpms_to_install:
        logging.info("Installing %s" % rpm)
        ret, output = vm_root_session.cmd_status_output("wget %s" % rpm)
        if ret != 0:
            logging.debug(output)
        ret, output = vm_root_session.cmd_status_output("rpm -i %s" % rpm.split("/")[-1])
        if ret != 0:
            logging.debug(output)


def build_install_qxl(vm_root_session, vm_script_path, params):
    """
    Build and install QXL in the VM

    @param vm_root_session:  VM Session object.
    @param vm_script_path: path where to find build_install.py script
    @param params: Dictionary with test parameters.
    """

    # Remove older versions of qxl driver if they exist
    output = vm_root_session.cmd("rm -rf /var/lib/xorg/modules/drivers/qxl_drv.so")
    if output:
        logging.debug(output)

    rpms_to_install = []

    # Checking to see if required rpms exist and if not, install them
    ret, output = vm_root_session.cmd_status_output("rpm -q libpciaccess-devel")
    if ret != 0:
        logging.debug(output)
        libpciaccess_devel_url = params.get("libpciaccess_devel_url")
        rpms_to_install.append(libpciaccess_devel_url)

    ret, output = vm_root_session.cmd_status_output("rpm -q xorg-x11-util-macros")
    if ret != 0:
        logging.debug(output)
        xorg_x11_util_macros_url = params.get("xorg_x11_util_macros_url")
        rpms_to_install.append(xorg_x11_util_macros_url)

    ret, output = vm_root_session.cmd_status_output("rpm -q xorg-x11-server-devel")
    if ret != 0:
        logging.debug(output)
        xorg_x11_server_devel_url = params.get("xorg_x11_server_devel_url")
        rpms_to_install.append(xorg_x11_server_devel_url)

    install_rpms(rpms_to_install, vm_root_session)

    # latest spice-protocol is required to build qxl
    output = vm_root_session.cmd("%s -p spice-protocol" % (vm_script_path))
    logging.info(output)
    if re.search("Return code", output):
        raise error.TestFail("spice-protocol was not installed properly")

    ret, output = vm_root_session.cmd_status_output("%s -p xf86-video-qxl" % (vm_script_path))
    logging.info(ret)
    logging.info(output)
    if re.search("Return code", output):
        raise error.TestFail("qxl was not installed properly")


def build_install_spicegtk(vm_root_session, vm_script_path, params):
    """
    Build and install spice-gtk in the VM

    @param vm_root_session:  VM Session object.
    @param vm_script_path: path where to find build_install.py script
    @param params: Dictionary with test parameters.
    """

    # Get version of spice-gtk before install
    ret, output = vm_root_session.cmd_status_output("LD_LIBRARY_PATH=/usr/local/lib remote-viewer --spice-gtk-version")
    if ret != 0:
        logging.error(output)
    else:
        logging.info(output)

    rpms_to_install = []

    # Checking to see if required rpms exist and if not, install them
    ret, output = vm_root_session.cmd_status_output("rpm -q libogg-devel")
    if ret != 0:
        logging.debug(output)
        libogg_devel_url = params.get("libogg_devel_url")
        rpms_to_install.append(libogg_devel_url)

    ret, output = vm_root_session.cmd_status_output("rpm -q celt051-devel")
    if ret != 0:
        logging.debug(output)
        celt051_devel_url = params.get("celt051_devel_url")
        rpms_to_install.append(celt051_devel_url)

    ret, output = vm_root_session.cmd_status_output("rpm -q libcacard-devel")
    if ret != 0:
        logging.debug(output)
        libcacard_devel_url = params.get("libcacard_devel_url")
        rpms_to_install.append(libcacard_devel_url)

    install_rpms(rpms_to_install, vm_root_session)

    rv_input.deploy_epel_repo(vm_root_session, params)

    ret, output = vm_root_session.cmd_status_output("yum -y install perl-Text-CSV pyparsing", timeout=300)
    logging.info(output)

    # latest spice-protocol is required to build qxl
    output = vm_root_session.cmd("%s -p spice-protocol" % (vm_script_path))
    logging.info(output)
    if re.search("Return code", output):
        raise error.TestFail("spice-protocol was not installed properly")

    ret, output = vm_root_session.cmd_status_output("%s -p spice-gtk" % (vm_script_path), timeout=300)
    logging.info(ret)
    logging.info(output)
    if re.search("Return code", output):
        raise error.TestFail("spice-gtk was not installed properly")

    # Get version of spice-gtk after install
    ret, output = vm_root_session.cmd_status_output("LD_LIBRARY_PATH=/usr/local/lib remote-viewer --spice-gtk-version")
    if ret != 0:
        logging.error(output)
    else:
        logging.info(output)


def build_install_vdagent(vm_root_session, vm_script_path, params):
    """
    Build and install spice-vdagent in the VM

    @param vm_root_session:  VM Session object.
    @param vm_script_path: path where to find build_install.py script
    @param params: Dictionary with test parameters.
    """

    # Get current version of spice-vdagent
    output = vm_root_session.cmd_output("spice-vdagent -h")
    logging.info(output)

    # Install required rpms
    rpms_to_install = []
    ret, output = vm_root_session.cmd_status_output("rpm -q libpciaccess-devel")
    if ret != 0:
        logging.debug(output)
        libpciaccess_devel_url = params.get("libpciaccess_devel_url")
        rpms_to_install.append(libpciaccess_devel_url)

    install_rpms(rpms_to_install, vm_root_session)

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
    output = vm_root_session.cmd("service spice-vdagentd restart")
    logging.info(output)
    if re.search("fail", output, re.IGNORECASE):
        raise error.TestFail("spice-vd-agent was not started properly")

    # Get version number of spice-vdagent
    output = vm_root_session.cmd_output("spice-vdagent -h")
    logging.info(output)


def run_rv_build_install(test, params, env):
    """
    Build and install packages from git on the client or guest VM

    Supported configurations:
    build_install_pkg: name of the package to get from git, build and install

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
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
        ret = build_install_qxl(vm_root_session, vm_script_path, params)
    elif pkgName == "spice-vd-agent":
        ret = build_install_vdagent(vm_root_session, vm_script_path, params)
    elif pkgName == "spice-gtk":
        ret = build_install_spicegtk(vm_root_session, vm_script_path, params)
    else:
        logging.info("Not supported right now")
        raise error.TestFail("Incorrect Test_Setup")

    rv_clearx.run_rv_clearx(test, params, env)
