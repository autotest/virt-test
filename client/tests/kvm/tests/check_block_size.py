import logging, re
from autotest_lib.client.common_lib import error
from autotest_lib.client.tests.kvm.tests import unattended_install
from autotest_lib.client.virt import virt_vm


@error.context_aware
def run_check_block_size(test, params, env):
    """
    Check physical block size and logical block size for virtio block device:
    1) Install guest with a new image.
    2) Verify whether physical/logical block size in guest is same as qemu
       parameters.
    TODO: This test only works on Linux guest, should make it work in windows
          guest. (Is there any windows tools to check block size?)

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    if params.get("need_install") == "yes":
        unattended_install.run_unattended_install(test, params, env)

    params["cdroms"] = ""
    params["unattended_file"] = ""
    params["cdrom_unattended"] = ""
    params["kernel"] = ""
    params["initrd"] = ""
    extra_params = params.get("extra_params", "")
    params["extra_params"] = re.sub(" --append '.*?'", "", extra_params)
    params["boot_once"] = "c"

    vm = env.get_vm(params["main_vm"])
    try:
        vm.verify_alive()
    except virt_vm.VMDeadError:
        logging.info("VM is dead, creating...")
        vm.create(params=params)

    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    # Get virtio block devices in guest.
    dev_list = session.cmd_output(params.get("get_dev_list_cmd", '')).split()
    if dev_list:
        expect_phyciscal = int(params.get("physical_block_size_stg", 0))
        expect_logical = int(params.get("logical_block_size_stg", 0))

        #FIXME: seems we don't have a method to check which virtio
        # device matches device file in guest. So we just check the
        # last device file in guest. Hope it will work correctly.
        # Yep, we need improvement here.
        cmd = params.get("chk_phy_blk_cmd") % dev_list[-1]
        error.context("Checking physical block size with cmd '%s'" % cmd)
        out_physical = int(session.cmd_output(cmd))
        logging.debug("Physical block size in guest: %s, expect: %s" % \
                      (out_physical, expect_phyciscal))

        cmd = params.get("chk_log_blk_cmd") % dev_list[-1]
        error.context("Checking logical block size with cmd '%s'" % cmd)
        out_logical = int(session.cmd_output(cmd))
        logging.debug("Logical block size in guest: %s, expect: %s" % \
                      (out_logical, expect_logical))

        session.close()
        if (out_physical != expect_phyciscal) or \
           (out_logical != expect_logical):
               raise error.TestFail("Physical/Logical block size in guest"
                                    " doesn't match with qemu parameter.")
    else:
        session.close()
        raise error.TestError("Could not find any virtio block device.")
