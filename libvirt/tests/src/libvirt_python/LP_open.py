import logging
import os

try:
    import libvirt
except ImportError:
    libvirt = None

from autotest.client.shared import error
from virttest import utils_libvirtd, virsh, utils_misc


def run_LP_open(test, params, env):
    """
    Test for libvirt bindings for python.

    Test function of libvirt.open().

    This function open a uri of libvirt. 
    1). Check environment
    2). libvirt.open() to get a virConnect object conn.
    3). call conn.getURI() to get the uri after libvirt.open()
    4). Verify the result with virsh.uri().
    """
    if not libvirt:
        raise error.TestNAError("Can not import libvirt. Please make sure "
                                "libvirt-python is installed.")
    # get the params from subtests.
    # params for general.
    libvirt_python_open_name = params.get("libvirt_python_open_name", "")
    status_error = params.get("status_error", "no")
    libvirtd = "on" == params.get("libvirtd", "on")

    # check the config
    if (libvirt_python_open_name.count("lxc") and
       (not os.path.exists("/usr/libexec/libvirt_lxc"))):
        raise error.TestNAError("Connect test of lxc:/// is not suggested on "
                                "the host with no lxc driver.")
    if (libvirt_python_open_name.count("xen") and
       (not os.path.exists("/var/run/xend"))):
        raise error.TestNAError("Connect test of xen:/// is not suggested on "
                                "the host with no xen driver.")
    if libvirt_python_open_name.count("qemu"):
        try:
            utils_misc.find_command("qemu-kvm")
        except ValueError:
            raise error.TestNAError("Connect test of qemu:/// is not suggested "
                                    "on the host with no qemu driver.")

    conn = None
    if not libvirtd:
        utils_libvirtd.libvirtd_stop()

    try:
        try:
            conn = libvirt.open(libvirt_python_open_name)
            # connect successfully
            if status_error == "yes":
                raise error.TestFail("Connect successfully in the "
                                     "case expected to fail.")
            # get the expect uri when connect argument is ""
            if libvirt_python_open_name == "":
                libvirt_python_open_name = virsh.canonical_uri().split()[-1]

            uri = conn.getURI()

            logging.debug("expected uri is: %s", libvirt_python_open_name)
            logging.debug("actual uri after connect is: %s", uri)
            if not uri == libvirt_python_open_name:
                raise error.TestFail("Command exit normally but the uri is "
                                     "not set as expected.")
        except libvirt.libvirtError, detail:
            if status_error == "no":
                raise error.TestFail("Connect failed in the case expected "
                                     "to succeed.\n"
                                     "Error: %s" % detail)
    finally:
        if conn is not None:
            conn.close()
        if not libvirtd:
            utils_libvirtd.libvirtd_start()
