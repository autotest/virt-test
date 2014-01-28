import logging
from autotest.client.shared import error
from virttest import virsh, libvirt_xml


def check_list(uuid, name):
    """
    Return True if filter found in nwfilter-list

    :param uuid: filter uuid
    :param name: filter name
    :return: True if found, False if not found
    """
    cmd_result = virsh.nwfilter_list(options="",
                                     ignore_status=True, debug=True)
    output = cmd_result.stdout.strip().split('\n')
    for i in range(2, len(output)):
        if output[i].split() == [uuid, name]:
            return True
    return False


def run(test, params, env):
    """
    Test command: virsh nwfilter-dumpxml.

    1) Prepare parameters.
    2) Run dumpxml command.
    3) Check result.
    """
    # Prepare parameters
    filter_name = params.get("dumpxml_filter_name", "")
    options_ref = params.get("dumpxml_options_ref", "")
    status_error = params.get("status_error", "no")

    # Run command
    cmd_result = virsh.nwfilter_dumpxml(filter_name, options=options_ref,
                                        ignore_status=True, debug=True)
    output = cmd_result.stdout.strip()
    status = cmd_result.exit_status

    # Check result
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command.")
    elif status_error == "no":
        if status:
            raise error.TestFail("Run failed with right command.")
        # Get uuid and name from output xml and compare with nwfilter-list
        # output
        new_filter = libvirt_xml.NwfilterXML()
        new_filter['xml'] = output
        uuid = new_filter.uuid
        name = new_filter.filter_name
        if check_list(uuid, name):
            logging.debug("The filter with uuid %s and name %s" % (uuid, name)
                          + " from nwfilter-dumpxml was found in" +
                          " nwfilter-list output")
        else:
            raise error.TestFail("The uuid %s with name %s from" % (uuid, name)
                                 + " nwfilter-dumpxml did not match with" +
                                 " nwfilter-list output")

        # Run command second time with uuid
        cmd_result = virsh.nwfilter_dumpxml(uuid, options=options_ref,
                                            ignore_status=True, debug=True)
        output1 = cmd_result.stdout.strip()
        status1 = cmd_result.exit_status
        if status_error == "yes":
            if status1 == 0:
                raise error.TestFail("Run successfully with wrong command.")
        elif status_error == "no":
            if status1:
                raise error.TestFail("Run failed with right command.")
        if output1 != output:
            raise error.TestFail("nwfilter dumpxml output was different" +
                                 " between using filter uuid and name")
