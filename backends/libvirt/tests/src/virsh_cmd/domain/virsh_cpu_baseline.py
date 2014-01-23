import re
import os
from autotest.client.shared import error
from virttest import virsh
from xml.dom.minidom import parseString


def run(test, params, env):
    """
    Test command: virsh cpu-baseline.

    Compute baseline CPU for a set of given CPUs.
    1.Get all parameters from configuration.
    2.Prepare a xml containing XML CPU descriptions.
    3.Perform virsh cpu-baseline operation.
    4.Confirm the test result.
    """

    def create_attach_xml(cpu_xmlfile, test_feature):
        """
        Prepare a xml containing XML CPU descriptions.

        :param cpu_xmlfile: XML file contains XML CPU descriptions.
        :param test_feature: test feature element.
        """
        content = """
<host>
 <cpu>
  <arch>x86_64</arch>
  <model>pentium3</model>
  <vendor>Intel</vendor>
  <feature name="ds"/>
  <feature name="%s"/>
 </cpu>
 <cpu>
  <arch>x86_64</arch>
  <model>pentium3</model>
  <vendor>Intel</vendor>
  <feature name="sse2"/>
  <feature name="%s"/>
  </cpu>
</host>
""" % (test_feature, test_feature)
        xmlfile = open(cpu_xmlfile, 'w')
        xmlfile.write(content)
        xmlfile.close()

    def check_xml(xml_output, test_feature):
        """
        Check if result output contains tested feature.

        :param xml_output: virsh cpu-baseline command's result.
        :param test_feature: Test feature element.
        """
        feature_name = ""
        dom = parseString(xml_output)
        feature = dom.getElementsByTagName("feature")
        for names in feature:
            feature_name += names.getAttribute("name")
        dom.unlink()
        if not re.search(test_feature, feature_name):
            raise error.TestFail("Cannot see '%s' feature", test_feature)

    # Get all parameters.
    file_name = params.get("cpu_baseline_cpu_file", "cpu.xml")
    cpu_ref = params.get("cpu_baseline_cpu_ref", "file")
    extra = params.get("cpu_baseline_extra", "")
    test_feature = params.get("cpu_baseline_test_feature", "acpi")
    status_error = params.get("status_error", "no")
    cpu_xmlfile = os.path.join(test.tmpdir, file_name)

    # Prepare a xml file.
    create_attach_xml(cpu_xmlfile, test_feature)

    if cpu_ref == "file":
        cpu_ref = cpu_xmlfile
    cpu_ref = "%s %s" % (cpu_ref, extra)

    # Test.
    result = virsh.cpu_baseline(cpu_ref, ignore_status=True, debug=True)
    status = result.exit_status
    output = result.stdout.strip()
    err = result.stderr.strip()

    # Check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
        if err == "":
            raise error.TestFail("The wrong command has no error outputed!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
        check_xml(output, test_feature)
    else:
        raise error.TestError("The status_error must be 'yes' or 'no'!")
