import logging
import re
from autotest.client.shared import utils, error
from virttest import libvirt_vm, utils_libvirtd
import virttest.utils_libguestfs as lgf


def login_to_check_foo_line(vm, file_ref, foo_line):
    """
    Login to check whether the foo line has been added to file.
    """

    if not vm.is_alive():
        vm.start()

    backup = "%s.bak" % file_ref

    try:
        session = vm.wait_for_login()
        cat_file = session.cmd_output("cat %s" % file_ref)
        logging.info("\n%s", cat_file)
        session.cmd("cp -f %s %s" % (file_ref, backup))
        session.cmd("sed -e \'s/%s$//g\' %s > %s" %
                    (foo_line, backup, file_ref))
        session.cmd('rm -f %s' % backup)
        session.close()
    except Exception, detail:
        raise error.TestError("Cleanup failed:\n%s" % detail)

    vm.destroy(gracefully=True)
    if not re.search(foo_line, cat_file):
        logging.info("Can not find %s in %s.", foo_line, file_ref)
        return False
    return True


def run(test, params, env):
    """
    Test of virt-edit.

    1) Get and init parameters for test.
    2) Prepare environment.
    3) Run virt-edit command and get result.
    5) Recover environment.
    6) Check result.
    """

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    uri = libvirt_vm.normalize_connect_uri(params.get("connect_uri",
                                                      "default"))
    start_vm = params.get("start_vm", "no")
    vm_ref = params.get("virt_edit_vm_ref", vm_name)
    file_ref = params.get("virt_edit_file_ref", "/etc/hosts")
    created_img = params.get("virt_edit_created_img", "/tmp/foo.img")
    foo_line = params.get("foo_line", "")
    options = params.get("virt_edit_options")
    options_suffix = params.get("virt_edit_options_suffix")
    status_error = params.get("status_error", "no")

    # virt-edit should not be used when vm is running.
    # (for normal test)
    if vm.is_alive() and start_vm == "no":
        vm.destroy(gracefully=True)

    dom_disk_dict = vm.get_disk_devices()  # TODO
    dom_uuid = vm.get_uuid()

    if vm_ref == "domdisk":
        if len(dom_disk_dict) != 1:
            raise error.TestError("Only one disk device should exist on "
                                  "%s:\n%s." % (vm_name, dom_disk_dict))
        disk_detail = dom_disk_dict.values()[0]
        vm_ref = disk_detail['source']
        logging.info("disk to be edit:%s", vm_ref)
    elif vm_ref == "domname":
        vm_ref = vm_name
    elif vm_ref == "domuuid":
        vm_ref = dom_uuid
    elif vm_ref == "createdimg":
        vm_ref = created_img
        utils.run("dd if=/dev/zero of=%s bs=256M count=1" % created_img)

    # Decide whether pass a exprt for virt-edit command.
    if foo_line != "":
        expr = "s/$/%s/" % foo_line
    else:
        expr = ""

    # Stop libvirtd if test need.
    libvirtd = params.get("libvirtd", "on")
    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    # Run test
    virsh_dargs = {'ignore_status': True, 'debug': True, 'uri': uri}
    result = lgf.virt_edit_cmd(vm_ref, file_ref, options,
                               options_suffix, expr, **virsh_dargs)
    status = result.exit_status

    # Recover libvirtd.
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    utils.run("rm -f %s" % created_img)

    status_error = (status_error == "yes")
    if status != 0:
        if not status_error:
            raise error.TestFail("Command executed failed.")
    else:
        if (expr != "" and
           (not login_to_check_foo_line(vm, file_ref, foo_line))):
            raise error.TestFail("Virt-edit to add %s in %s failed."
                                 "Test failed." % (foo_line, file_ref))
