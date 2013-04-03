import os
from autotest.client.shared import error
from virttest import virsh
from xml.dom.minidom import parseString


def run_virsh_cpu_compare(test, params, env):
    """
    Test command: virsh cpu-compare.

    Compare host CPU with a CPU described by an XML file.
    1.Get all parameters from configuration.
    2.Prepare temp file saves of CPU infomation.
    3.Perform virsh net-compare operation.
    4.Confirm the result.
    """
    def get_cpu_xml(mode, tmp_file):
        """
        Get CPU infomation and put it into a file.

        @param: mode: Test mode, decides file's detail.
        @param: tmp_file: File saves CPU infomation.
        """
        cpu_xml_file = open(tmp_file, 'wb')
        domxml = virsh.capabilities()
        dom = parseString(domxml)
        cpu_node = dom.getElementsByTagName('cpu')[0]
        if mode == "modify":
            vendor = cpu_node.getElementsByTagName('vendor')[0]
            for node in vendor.childNodes:
                if node.nodeType == node.TEXT_NODE:
                    vendor.removeChild(node)
                    break
            text_node = dom.createTextNode('test_vendor')
            vendor.appendChild(text_node)
            cpu_node.writexml(cpu_xml_file)
        elif mode == "clear":
            # Clear up file detail
            cpu_xml_file.truncate(0)
        else:
            cpu_node.writexml(cpu_xml_file)
        cpu_xml_file.close()
        dom.unlink()

    # Get all parameters.
    ref = params["cpu_compare_ref"]
    mode = params.get("cpu_compare_mode", "")
    status_error = params.get("status_error", "no")
    extra = params.get("cpu_compare_extra", "")
    file_name = params.get("cpu_compare_file_name", "cpu.xml")
    tmp_file = os.path.join(test.tmpdir, file_name)

    # Prepare temp file.
    get_cpu_xml(mode, tmp_file)

    if ref == "file":
        ref = tmp_file
    ref = "%s %s" % (ref, extra)

    # Perform virsh cpu-compare operation.
    status = virsh.cpu_compare(ref, ignore_status=True, debug=True).exit_status

    # Check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
