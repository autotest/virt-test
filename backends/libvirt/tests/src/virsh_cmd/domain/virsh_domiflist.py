import re
import logging
from autotest.client.shared import error
from virttest import virsh, utils_libvirtd, utils_net
from virttest.libvirt_xml import vm_xml

driver_dict = {'virtio': 'virtio_net', '-': '8139cp', 'e1000': 'e1000',
               'rtl8139': '8139cp'}

# Regular expression for the below output
#      vnet0      bridge     virbr0     virtio      52:54:00:b2:b3:b4
rg = re.compile(r"^(\w+)\s+(\w+)\s+(\w+)\s+(\S+)\s+(([a-fA-F0-9]{2}:?){6})")


def run(test, params, env):
    """
    Step 1: Get the virsh domiflist value.
    Step 2: Check for interface in xml file.
    Step 3: Check for type in xml file.
    Step 4: Check for model inside the guest and xml file.
    Step 5: Check for mac id inside the guest and xml file
    """

    def parse_interface_details(output):
        """
        To parse the interface details from virsh command output
        """
        iface_cmd = {}
        ifaces_cmd = []
        for line in output.split('\n'):
            match_obj = rg.search(line)
            # Due to the extra space in the list
            if match_obj is not None:
                iface_cmd['interface'] = match_obj.group(1)
                iface_cmd['type'] = match_obj.group(2)
                iface_cmd['source'] = match_obj.group(3)
                iface_cmd['model'] = match_obj.group(4)
                iface_cmd['mac'] = match_obj.group(5)
                ifaces_cmd.append(iface_cmd)
                iface_cmd = {}
        return ifaces_cmd

    def check_output(output, vm):
        """
        1. Get the interface details of the command output
        2. Get the interface details from xml file
        3. Check command output agaist xml and guest output
        """
        vm_name = vm.name

        try:
            session = vm.wait_for_login()
        except Exception, detail:
            raise error.TestFail("Unable to login to VM:%s" % detail)
        ifaces_actual = parse_interface_details(output)
        iface_xml = {}
        error_count = 0
        # Check for the interface values
        for item in ifaces_actual:
            # Check for mac and model
            model = item['model']
            iname = utils_net.get_linux_ifname(session, item['mac'])
            if iname is not None:
                cmd = 'ethtool -i %s | grep driver | awk \'{print $2}\'' % iname
                drive = session.cmd_output(cmd).strip()
                if driver_dict[model] != drive:
                    error_count += 1
                    logging.error("Mismatch in the model for the interface %s\n"
                                  "Expected Model:%s\nActual Model:%s",
                                  item['interface'], driver_dict[model],
                                  item['model'])
            else:
                error_count += 1
                logging.error("Mismatch in the mac for the interface %s\n",
                              item['interface'])
            iface_xml = vm_xml.VMXML.get_iface_by_mac(vm_name, item['mac'])
            if iface_xml is not None:
                if iface_xml['type'] != item['type']:
                    error_count += 1
                    logging.error("Mismatch in the network type for the "
                                  "interface %s \n Type in command output: %s\n"
                                  "Type in xml file: %s",
                                  item['interface'],
                                  item['type'],
                                  iface_xml['type'])
                if iface_xml['source'] != item['source']:
                    error_count += 1
                    logging.error("Mismatch in the network source for the"
                                  " interface %s \n Source in command output:"
                                  "%s\nSource in xml file: %s",
                                  item['interface'],
                                  item['source'],
                                  iface_xml['source'])

            else:
                error_count += 1
                logging.error("There is no interface in the xml file "
                              "with the below specified mac address\n"
                              "Mac:%s", item['mac'])
            iface_xml = {}
        if error_count > 0:
            raise error.TestFail("The test failed, consult previous error logs")

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    domid = vm.get_id()
    domuuid = vm.get_uuid()

    # Get the virsh domiflist
    options = params.get("domiflist_domname_options", "id")
    additional_options = params.get("domiflist_extra_options", "")
    status_error = params.get("status_error", "no")

    if options == "id":
        options = domid
    elif options == "uuid":
        options = domuuid
    elif options == "name":
        options = vm_name

    result = virsh.domiflist(options, additional_options, ignore_status=True)

    if status_error == "yes":
        if result.exit_status == 0:
            raise error.TestFail("Run passed for incorrect command \nCommand: "
                                 "virsh domiflist %s\nOutput Status:%s\n"
                                 % (options, result.exit_status))
    else:
        check_output(result.stdout, vm)
