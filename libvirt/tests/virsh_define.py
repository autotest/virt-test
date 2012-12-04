import logging
from autotest.client.shared import error
from virttest import libvirt_xml, virsh

def run_virsh_define(test, params, env):
    """
    Test defining/undefining domain by dumping xml, changing it, and re-adding.

    (1) Get name and uuid of existing vm
    (2) Extract XML, undefine domain
    (3) Change name & uuid in XML
    (4) Define domain
    (5) Verify domain start
    (6) Change name & uuid back to original
    """

    def do_rename(vm, new_name, uuid=None):
        if vm.is_alive():
            vm.destroy(gracefully=True)

        vmxml = libvirt_xml.VMXML(virsh)
        vmxml.new_from_dumpxml(vm.name, virsh)
        backup = vmxml.copy()
        # can't do in-place rename, must operate on XML
        try:
            vmxml.undefine()
            # All failures trip a single exception
        except libvirt_xml.LibvirtXMLError, detail:
            del vmxml # clean up temporary files
            raise error.TestFail("Error reported while undefining VM:" + detail)
        # Alter the XML
        vmxml.vm_name = new_name
        if uuid is None:
            # invalidate uuid so libvirt will regenerate
            del vmxml.uuid
            vm.uuid = None
        else:
            vmxml.uuid = uuid
            vm.uuid = uuid
        # Re-define XML to libvirt
        logging.info("Test rename %s to %s.", vm.name, new_name)
        try:
            vmxml.define()
        except libvirt_xml.LibvirtXMLError:
            del vmxml # clean up temporary files
            # Allow exceptions thrown here since state will be undefined
            backup.define()
        # Keep names uniform
        vm.name = new_name
        # Exercize the defined XML
        if vm.start():
            logging.info("Start new guest %s succeed.", new_name)
        vm.destroy()
        # vmxml and backup go out of scope, tmp files auto-removed

    # Run test
    vm_name = params.get("main_vm")
    vm = env.get_vm(params["main_vm"])
    new_name = params.get("new_name", "test")
    uuid = vm.get_uuid()
    logging.info("Original uuid: %s", vm.get_uuid())
    assert uuid is not None
    do_rename(vm, new_name) # give it a new uuid
    logging.info("Generated uuid: %s", vm.get_uuid())
    assert vm.uuid != uuid
    # Rename back to original to maintain known-state
    do_rename(vm, vm_name, uuid) # restore original uuid
    logging.info("Final uuid: %s", vm.get_uuid())
