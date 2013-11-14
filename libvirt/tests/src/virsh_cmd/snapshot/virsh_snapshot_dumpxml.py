import re
import os
import time
import logging
from autotest.client.shared import error
from virttest import virsh, utils_test
from virttest.libvirt_xml import vm_xml


def get_snap_createtime(vm_name, snap_name):
    """
    Get the snap_name's create time from snap_list

    :param snap_list: output of snapshot list
    :param snap_name: name of snapshot you want to get
    :return: snapshot create time
    """

    result = virsh.command("snapshot-list %s" % vm_name)
    logging.debug("result is %s", result.stdout)
    data = re.search(snap_name + r"\s+\d+-\d+-\d+\s+\d+:\d+:\d+",
                     result.stdout).group()

    return data.split("%s " % snap_name)[1].strip()


def snapshot_dumpxml_check(output, opt_dict):
    """
    Check the snapshot dumpxml info, including
    1. snaphot name
    2. description
    3. createTime
    4. domstate
    5. domname
    6. passwd if have --security-info

    :param output: snapshot dumpxml info
    :param opt_dict: compare info including passwd, snapname, createtime,
                     domain state, description and domain name
    """

    sname_snip = "<name>%s</name>" % opt_dict['snap_name']
    desc_snip = "<description>%s</description>" % opt_dict['desc_opt']
    dname_snip = "<name>%s</name>" % opt_dict['vm_name']
    ctime = opt_dict['ctime']
    timestamp = int(time.mktime(time.strptime(ctime, "%Y-%m-%d %H:%M:%S")))
    time_snip = "<creationTime>%s</creationTime>" % timestamp

    dom_state = "".join(opt_dict['dom_state'].split())
    if opt_dict.has_key('disk_opt') and dom_state != "shutoff":
        dstate_snip = "<state>disk-snapshot</state>"
    else:
        dstate_snip = "<state>%s</state>" % dom_state

    # Check all options in xml at one time
    var_match = locals()
    for var in ["sname_snip", "desc_snip", "dname_snip", "time_snip",
                "dstate_snip"]:
        if not re.search(var_match[var], output):
            raise error.TestFail("Fail to match %s in xml %s" %
                                 (var_match[var], output))
        else:
            logging.info("XML check for %s success", var_match[var])

    if opt_dict.has_key('passwd'):
        passwd_match = "<graphic.*passwd='%s'.*>" % opt_dict['passwd']
        if not re.search(passwd_match, output):
            raise error.TestFail("Fail to match passwd in xml %s" % output)
        else:
            logging.info("XML check for %s success",
                         re.search(passwd_match, output).group())
    else:
        passwd_match = "<graphic.*passwd=.*>"
        if re.search(passwd_match, output):
            raise error.TestFail("Have no --security-info option but find "
                                 "passwd in xml")
        else:
            logging.info("Do not have --security-info option and can not find "
                         "passwd in xml")


def run(test, params, env):
    """
    Test snapshot-dumpxml command, make sure that the xml you get is correct

    Test scenaries:
    1. live snapshot dump
    2. shutoff snapshot dump
    3. dumpxml with security info
    4. readonly mode
    """

    if not virsh.has_help_command('snapshot-dumpxml'):
        raise error.TestNAError("This version of libvirt does not support "
                                "the snapshot-dumpxml test")

    vm_name = params.get("main_vm")
    status_error = params.get("status_error", "no")
    passwd = params.get("snapshot_passwd")
    secu_opt = params.get("snapshot_secure_option")
    desc_opt = params.get("snapshot_desc_option")
    mem_opt = params.get("snapshot_mem_option")
    disk_opt = params.get("disk_only_snap")
    snap_name = params.get("snapshot_name", "snap_test")
    readonly = params.get("readonly", False)

    try:
        snap_opt = ""
        opt_dict = {}
        # collect all the parameters at one time
        opt_name = locals()
        for opt in ["snap_name", "desc_opt", "mem_opt", "disk_opt"]:
            if opt_name[opt] is not None:
                # Integrate snapshot create options
                snap_opt = snap_opt + " " + opt_name[opt]

        # Do xml backup for final recovery
        vmxml_backup = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)
        # Add passwd in guest graphics
        if passwd is not None:
            vm = env.get_vm(vm_name)
            if vm.is_alive():
                vm.destroy()
            vm_xml.VMXML.add_security_info(
                vm_xml.VMXML.new_from_dumpxml(vm_name), passwd)
            vm.start()
            if secu_opt is not None:
                opt_dict['passwd'] = passwd

        logging.debug("snapshot create options are %s", snap_opt)

        # Get state to do snapshot xml state check
        dom_state = virsh.domstate(vm_name).stdout.strip()

        # Create disk snapshot before all to make the origin image clean
        virsh.snapshot_create_as(vm_name, "--disk-only")

        # Create snapshot with options
        snapshot_result = virsh.snapshot_create_as(vm_name, snap_opt,
                                                   readonly=readonly)
        if snapshot_result.exit_status:
            if status_error == "no":
                raise error.TestFail("Failed to create snapshot. Error:%s."
                                     % snapshot_result.stderr.strip())
            elif status_error == "yes":
                logging.info("Create snapshot failed as expected, Error:%s.",
                             snapshot_result.stderr.strip())
                return

        ctime = get_snap_createtime(vm_name, snap_name)

        # Run virsh command for snapshot-dumpxml
        dumpxml_result = virsh.snapshot_dumpxml(vm_name, snap_name, secu_opt)
        if dumpxml_result.exit_status:
            if status_error == "no":
                raise error.TestFail("Failed to dump snapshot xml. Error:%s."
                                     % dumpxml_result.stderr.strip())
            elif status_error == "yes":
                logging.info("Dumpxml snapshot failed as expected, Error:%s.",
                             dumpxml_result.stderr.strip())
                return

        # Record all the parameters in dict at one time
        check_name = locals()
        for var in ["vm_name", "snap_name", "desc_opt", "dom_state", "ctime",
                    "disk_opt"]:
            if check_name[var] is not None:
                opt_dict[var] = check_name[var]

        logging.debug("opt_dict is %s", opt_dict)
        output = dumpxml_result.stdout.strip()
        snapshot_dumpxml_check(output, opt_dict)

    finally:
        # Recovery
        utils_test.libvirt.clean_up_snapshots(vm_name)
        vmxml_backup.sync("--snapshots-metadata")
