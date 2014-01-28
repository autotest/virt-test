import time
import logging
from autotest.client.shared import error
from virttest import virsh, libvirt_xml, aexpect


def edit_filter_xml(filter_name, edit_cmd):
    """
    Edit network filter xml

    :param filter_name: filter name or uuid
    :param edit_cmd: edit command list in interactive mode
    """
    session = aexpect.ShellSession("sudo -s")
    try:
        session.sendline("virsh nwfilter-edit %s" % filter_name)
        for i in edit_cmd:
            session.sendline(i)
        # Press ESC
        session.send('\x1b')
        # Save and quit
        session.send('ZZ')
        # use sleep(1) to make sure the modify has been completed.
        time.sleep(1)
        session.close()
        logging.info("Succeed to do nwfilter edit")
    except (aexpect.ShellError, aexpect.ExpectError), details:
        log = session.get_output()
        session.close()
        raise error.TestFail("Failed to do nwfilter-edit: %s\n%s"
                             % (details, log))


def run(test, params, env):
    """
    Test command: virsh nwfilter-edit.

    1) Prepare parameters.
    2) Run nwfilter-edit command.
    3) Check result.
    4) Clean env
    """
    # Prepare parameters
    filter_name = params.get("edit_filter_name", "")
    filter_ref = params.get("edit_filter_ref", "")
    edit_priority = params.get("edit_priority", "")
    extra_option = params.get("edit_extra_option", "")
    status_error = params.get("status_error", "no")
    status = True
    edit_cmd = []
    edit_cmd.append(":1s/priority=.*$/priority='" + edit_priority + "'>")

    # Backup filter xml
    if filter_name and filter_ref.find("invalid") == -1:
        new_filter = libvirt_xml.NwfilterXML()
        filterxml = new_filter.new_from_filter_dumpxml(filter_name)
        logging.debug("the filter xml is: %s" % filterxml.xmltreefile)
        filter_xml = filterxml.xmltreefile.name
        uuid = filterxml.uuid
        pre_priority = filterxml.filter_priority

    # Run command
    if status_error == "no":
        if filter_ref == "name":
            edit_filter_xml(filter_name, edit_cmd)
        elif filter_ref == "uuid":
            edit_filter_xml(uuid, edit_cmd)
        else:
            raise error.TestNAError("For positive test, edit_filter_ref cloud"
                                    " be either 'name' or 'uuid'.")
    else:
        if filter_ref.find("invalid") == 0:
            if extra_option == "":
                filter_name = filter_ref
            edit_result = virsh.nwfilter_edit(filter_name, extra_option,
                                              ignore_statu=True, debug=True)
            if edit_result.exit_status == 0:
                raise error.TestFail("nwfilter-edit should fail but succeed")
            else:
                logging.info("Run command failed as expected")
                status = False
        else:
            raise error.TestNAError("For negative test, string 'invalid' is"
                                    " required in edit_filter_ref.")

    # no check and clean env if command fail
    if status:
        # Check result
        if filter_name and filter_ref.find("invalid") == -1:
            post_filter = libvirt_xml.NwfilterXML()
            postxml = post_filter.new_from_filter_dumpxml(filter_name)
            logging.debug("the filter xml after edit is: %s" %
                          postxml.xmltreefile)
            post_priority = postxml.filter_priority
            if pre_priority == edit_priority:
                if post_priority != pre_priority:
                    raise error.TestFail("nwfilter-edit fail to update filter"
                                         " priority")
            else:
                if post_priority == pre_priority:
                    raise error.TestFail("nwfilter-edit fail to update filter"
                                         " priority")

            # Clean env
            if post_priority != pre_priority:
                virsh.nwfilter_define(filter_xml, options="",
                                      ignore_status=True, debug=True)
