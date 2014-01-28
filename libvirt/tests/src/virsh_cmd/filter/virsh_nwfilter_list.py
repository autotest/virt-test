import os
import logging
from autotest.client.shared import error
from virttest import virsh


NWFILTER_ETC_DIR = "/etc/libvirt/nwfilter"


def run(test, params, env):
    """
    Test command: virsh nwfilter-list.

    1) Prepare parameters.
    2) Run nwfilter-list command.
    3) Check result.
    """
    # Prepare parameters
    options_ref = params.get("list_options_ref", "")
    status_error = params.get("status_error", "no")
    filter_name = []

    # Run command
    cmd_result = virsh.nwfilter_list(options=options_ref,
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

        # Retrieve filter name from output and check the cfg file
        output_list = output.split('\n')
        for i in range(2, len(output_list)):
            filter_name.append(output_list[i].split()[1])
        for i in range(len(filter_name)):
            xml_path = "%s/%s.xml" % (NWFILTER_ETC_DIR, filter_name[i])
            if not os.path.exists(xml_path):
                raise error.TestFail("Can't find list filter %s xml under %s"
                                     % (filter_name[i], NWFILTER_ETC_DIR))
            else:
                logging.debug("list filter %s xml found under %s" %
                              (filter_name[i], NWFILTER_ETC_DIR))
