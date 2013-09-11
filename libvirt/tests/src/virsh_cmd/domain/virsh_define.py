import logging
from autotest.client.shared import error
from virttest.libvirt_xml import VMXML, LibvirtXMLError
from virttest import virt_vm


def run_virsh_define(test, params, env):
    """
    Test defining/undefining domain by dumping xml, changing it, and re-adding.

    (1) Get name and uuid of existing vm
    (2) Rename domain and verify domain start
    (3) Get uuid of new vm
    (4) Change name&uuid back to original
    (5) Verify domain start
    """

    def do_rename(vm, new_name, uuid=None, fail_info=[]):
        # Change name in XML
        logging.info("Rename %s to %s.", vm.name, new_name)
        try:
            vm = VMXML.vm_rename(vm, new_name, uuid)  # give it a new uuid
        except LibvirtXMLError, detail:
            raise error.TestFail("Rename %s to %s failed:\n%s"
                                 % (vm.name, new_name, detail))

        # Exercize the defined XML
        try:
            vm.start()
        except virt_vm.VMStartError, detail:
            # Do not raise TestFail because vm should be restored
            fail_info.append("Start guest %s failed:%s" % (vm.name, detail))
        vm.destroy()
        return fail_info

    # Run test
    vm_name = params.get("main_vm")
    vm = env.get_vm(params["main_vm"])
    new_name = params.get("new_name", "test")
    uuid = vm.get_uuid()
    logging.info("Original uuid: %s", vm.get_uuid())

    assert uuid is not None
    # Rename to a new name
    fail_info = do_rename(vm, new_name)
    logging.info("Generated uuid: %s", vm.get_uuid())

    # Rename back to original to maintain known-state
    fail_info = do_rename(vm, vm_name, uuid, fail_info)
    logging.info("Final uuid: %s", vm.get_uuid())

    if len(fail_info):
        raise error.TestFail(fail_info)
