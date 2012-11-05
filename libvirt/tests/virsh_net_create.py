import re, logging, commands
from autotest.client.shared import utils, error
from virttest import virsh, libvirt_vm, libvirt_xml


def run_virsh_net_create(test, params, env):
    """
    Test command: virsh net-create.

    1) Create a new network's config file from a source file.
    2) Prepare current environment for new network.
    3) Run test.
    4) Recover libvirtd and network.
    5) Check result.
    """

    #Create network's xml file
    source_file = params.get("net_source_file",
                         "/etc/libvirt/qemu/networks/default.xml")
    net_name = params.get("network_name", "")
    net_uuid = params.get("network_uuid", "")
    options_ref = params.get("net_create_options_ref", "default")
    extra = params.get("net_create_options_extra", "")

    network_xml = libvirt_xml.NetworkXML()
    network_xml.new_from_file(source_file)
    if net_name:
        network_xml.set_network_name(net_name)
    if net_uuid:
        network_xml.set_network_name(net_uuid)
    #TODO:other configuration
    print network_xml.xml
    xml_info = commands.getoutput("cat %s" % network_xml.xml)
    logging.info("XMLInfo:\n%s", xml_info)

    #Prepare network environment
    list_output = virsh.net_list("", print_info=True).stdout.strip()
    if re.search(net_name, list_output):
        virsh.net_destroy(net_name, print_info=True)

    #Run test case
    if options_ref == "exist_file":
        options_ref = network_xml.xml + extra

    #Prepare libvirtd status
    libvirtd = params.get("libvirtd", "on")
    if libvirtd == "off":
        libvirt_vm.service_libvirtd_control("stop")

    result = virsh.net_create(options_ref, extra, ignore_status=True, print_info=True)
    status = result.exit_status
    output = result.stdout.strip()

    #Recover libvirtd service start
    if libvirtd == "off":
        libvirt_vm.service_libvirtd_control("start")

    #Recover network
    #Remove added network(not 'default') during test.
    list_output = virsh.net_list("", print_info=True).stdout.strip()
    if re.search(net_name, list_output) and net_name != "default":
        virsh.net_destroy(net_name, print_info=True)

    #Keep default network exist for test's need.
    list_output = virsh.net_list("", print_info=True).stdout.strip()
    if not re.search("default", list_output):
        virsh.net_create(source_file, print_info=True)

    #Check Result
    status_error = params.get("status_error", "no")
    addition_status_error = params.get("addition_status_error", "no")
    status_error = (status_error == "no") and (addition_status_error == "no")
    if not status_error:
        if status == 0:
            raise error.TestFail("Run successful with wrong command!")
    else:
        if status != 0:
            raise error.TestFail("Run failed with right command.")
        if not re.search(net_name, output):
            raise error.TestFail("Run successful but result is not expected.")
