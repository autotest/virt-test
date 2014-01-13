import re
import os
import commands
import logging
from autotest.client.shared import error
from virttest import virsh, utils_misc, xml_utils, libvirt_xml
from virttest.libvirt_xml import vm_xml, xcepts


def xml_recover(vmxml):
    """
    Recover older xml config with backup vmxml.

    :params: vmxml: VMXML object
    """
    try:
        options = "--snapshots-metadata"
        vmxml.undefine(options)
        vmxml.define()
        return True

    except xcepts.LibvirtXMLError, detail:
        logging.error("Recover older xml failed:%s.", detail)
        return False


def check_snap_in_image(vm_name, snap_name):
    """
    check the snapshot info in image

    :params: vm_name: VM name
    :params: snap_name: Snapshot name
    """

    domxml = virsh.dumpxml(vm_name).stdout.strip()
    xtf_dom = xml_utils.XMLTreeFile(domxml)

    cmd = "qemu-img info " + xtf_dom.find("devices/disk/source").get("file")
    img_info = commands.getoutput(cmd).strip()

    if re.search(snap_name, img_info):
        logging.info("Find snapshot info in image")
        return True
    else:
        return False


def compose_disk_options(test, params, opt_names):
    """
    Compose the {disk,mem}spec options

    The diskspec file need to add suitable dir with the name which is configed
    individually, The 'value' after 'file=' is a parameter which also need to
    get from cfg

    :params: test & params: system parameters
    :params: opt_names: params get from cfg of {disk,mem}spec options
    """
    if opt_names.find("file=") >= 0:
        opt_disk = opt_names.split("file=")
        opt_list = opt_disk[1].split(",")

        if len(opt_list) > 1:
            left_opt = opt_list[1]
        else:
            left_opt = ""

        if params.get("bad_disk") is not None or \
           params.get("external_disk") is not None:
            spec_disk = os.path.join(test.virtdir, params.get(opt_list[0]))
        else:
            spec_disk = os.path.join(test.virtdir, opt_list[0])

        return opt_disk[0] + "file=" + spec_disk + left_opt


def check_snapslist(vm_name, options, option_dict, output,
                    snaps_before, snaps_list):
    no_metadata = options.find("--no-metadata")
    fdisks = "disks"

    # command with print-xml will not really create snapshot
    if options.find("print-xml") >= 0:
        xtf = xml_utils.XMLTreeFile(output)

        # With --print-xml there isn't new snapshot created
        if len(snaps_before) != len(snaps_list):
            raise error.TestFail("--print-xml create new snapshot")

    else:
        # The following does not check with print-xml
        get_sname = output.split()[2]

        # check domain/snapshot xml depends on if have metadata
        if no_metadata < 0:
            output_dump = virsh.snapshot_dumpxml(vm_name,
                                                 get_sname).stdout.strip()
        else:
            output_dump = virsh.dumpxml(vm_name).stdout.strip()
            fdisks = "devices"

        xtf = xml_utils.XMLTreeFile(output_dump)

        find = 0
        for snap in snaps_list:
            if snap == get_sname:
                find = 1
                break

        # Should find snap in snaplist without --no-metadata
        if (find == 0 and no_metadata < 0):
            raise error.TestFail("Can not find snapshot %s!"
                                 % get_sname)
        # Should not find snap in list without metadata
        elif (find == 1 and no_metadata >= 0):
            raise error.TestFail("Can find snapshot metadata even "
                                 "if have --no-metadata")
        elif (find == 0 and no_metadata >= 0):
            logging.info("Can not find snapshot %s as no-metadata "
                         "is given" % get_sname)

            # Check snapshot only in qemu-img
            if (options.find("--disk-only") < 0 and
                    options.find("--memspec") < 0):
                ret = check_snap_in_image(vm_name, get_sname)

                if ret is False:
                    raise error.TestFail("No snap info in image")

        else:
            logging.info("Find snapshot %s in snapshot list."
                         % get_sname)

        # Check if the disk file exist when disk-only is given
        if options.find("disk-only") >= 0:
            for disk in xtf.find(fdisks).findall('disk'):
                diskpath = disk.find('source').get('file')
                if os.path.isfile(diskpath):
                    logging.info("disk file %s exist" % diskpath)
                    os.remove(diskpath)
                else:
                    # Didn't find <source file="path to disk"/>
                    # in output - this could leave a file around
                    # wherever the main OS image file is found
                    logging.debug("output_dump=%s", output_dump)
                    raise error.TestFail("Can not find disk %s"
                                         % diskpath)

        # Check if the guest is halted when 'halt' is given
        if options.find("halt") >= 0:
            domstate = virsh.domstate(vm_name)
            if re.match("shut off", domstate.stdout):
                logging.info("Domain is halted after create "
                             "snapshot")
            else:
                raise error.TestFail("Domain is not halted after "
                                     "snapshot created")

    # Check the snapshot xml regardless of having print-xml or not
    if (options.find("name") >= 0 and no_metadata < 0):
        if xtf.findtext('name') == option_dict["name"]:
            logging.info("get snapshot name same as set")
        else:
            raise error.TestFail("Get wrong snapshot name %s" %
                                 xtf.findtext('name'))

    if (options.find("description") >= 0 and no_metadata < 0):
        desc = xtf.findtext('description')
        if desc == option_dict["description"]:
            logging.info("get snapshot description same as set")
        else:
            raise error.TestFail("Get wrong description on xml")

    if options.find("diskspec") >= 0:
        if isinstance(option_dict['diskspec'], list):
            index = len(option_dict['diskspec'])
        else:
            index = 1

        disks = xtf.find(fdisks).findall('disk')

        for num in range(index):
            if isinstance(option_dict['diskspec'], list):
                option_disk = option_dict['diskspec'][num]
            else:
                option_disk = option_dict['diskspec']

            option_disk = "name=" + option_disk
            disk_dict = utils_misc.valued_option_dict(option_disk,
                                                      ",", 0, "=")
            logging.debug("disk_dict is %s", disk_dict)

            # For no metadata snapshot do not check name and
            # snapshot
            if no_metadata < 0:
                dname = disks[num].get('name')
                logging.debug("dname is %s", dname)
                if dname == disk_dict['name']:
                    logging.info("get disk%d name same as set in "
                                 "diskspec", num)
                else:
                    raise error.TestFail("Get wrong disk%d name %s"
                                         % num, dname)

                if option_disk.find('snapshot=') >= 0:
                    dsnap = disks[num].get('snapshot')
                    logging.debug("dsnap is %s", dsnap)
                    if dsnap == disk_dict['snapshot']:
                        logging.info("get disk%d snapshot type same"
                                     " as set in diskspec", num)
                    else:
                        raise error.TestFail("Get wrong disk%d "
                                             "snapshot type %s" %
                                             num, dsnap)

            if option_disk.find('driver=') >= 0:
                dtype = disks[num].find('driver').get('type')
                if dtype == disk_dict['driver']:
                    logging.info("get disk%d driver type same as "
                                 "set in diskspec", num)
                else:
                    raise error.TestFail("Get wrong disk%d driver "
                                         "type %s" % num, dtype)

            if option_disk.find('file=') >= 0:
                sfile = disks[num].find('source').get('file')
                if sfile == disk_dict['file']:
                    logging.info("get disk%d source file same as "
                                 "set in diskspec", num)
                else:
                    raise error.TestFail("Get wrong disk%d source "
                                         "file %s" % num, sfile)

    # For memspec check if the xml is same as setting
    # Also check if the mem file exists
    if options.find("memspec") >= 0:
        memspec = option_dict['memspec']
        if re.search('file=', option_dict['memspec']) < 0:
            memspec = 'file=' + option_dict['memspec']

        mem_dict = utils_misc.valued_option_dict(memspec, ",", 0,
                                                 "=")
        logging.debug("mem_dict is %s", mem_dict)

        if no_metadata < 0:
            if memspec.find('snapshot=') >= 0:
                snap = xtf.find('memory').get('snapshot')
                if snap == mem_dict['snapshot']:
                    logging.info("get memory snapshot type same as"
                                 " set in diskspec")
                else:
                    raise error.TestFail("Get wrong memory snapshot"
                                         " type on print xml")

            memfile = xtf.find('memory').get('file')
            if memfile == mem_dict['file']:
                logging.info("get memory file same as set in "
                             "diskspec")
            else:
                raise error.TestFail("Get wrong memory file on "
                                     "print xml %s", memfile)

        if options.find("print-xml") < 0:
            if os.path.isfile(mem_dict['file']):
                logging.info("memory file generated")
                os.remove(mem_dict['file'])
            else:
                raise error.TestFail("Fail to generate memory file"
                                     " %s", mem_dict['file'])


def run(test, params, env):
    """
    Test snapshot-create-as command
    Make sure that the clean repo can be used because qemu-guest-agent need to
    be installed in guest

    The command create a snapshot (disk and RAM) from arguments which including
    the following point
    * virsh snapshot-create-as --print-xml --diskspec --name --description
    * virsh snapshot-create-as --print-xml with multi --diskspec
    * virsh snapshot-create-as --print-xml --memspec
    * virsh snapshot-create-as --description
    * virsh snapshot-create-as --no-metadata
    * virsh snapshot-create-as --no-metadata --print-xml (negative test)
    * virsh snapshot-create-as --atomic --disk-only
    * virsh snapshot-create-as --quiesce --disk-only (positive and negative)
    * virsh snapshot-create-as --reuse-external
    * virsh snapshot-create-as --disk-only --diskspec
    * virsh snapshot-create-as --memspec --reuse-external --atomic(negative)
    * virsh snapshot-create-as --disk-only and --memspec (negative)
    * Create multi snapshots with snapshot-create-as
    * Create snapshot with name a--a a--a--snap1
    """

    if not virsh.has_help_command('snapshot-create-as'):
        raise error.TestNAError("This version of libvirt does not support "
                                "the snapshot-create-as test")

    vm_name = params.get("main_vm")
    status_error = params.get("status_error", "no")
    options = params.get("snap_createas_opts")
    multi_num = params.get("multi_num", "1")
    diskspec_num = params.get("diskspec_num", "1")
    bad_disk = params.get("bad_disk")
    external_disk = params.get("external_disk")
    start_ga = params.get("start_ga", "yes")
    domain_state = params.get("domain_state")
    memspec_opts = params.get("memspec_opts")
    diskspec_opts = params.get("diskspec_opts")

    opt_names = locals()
    if memspec_opts is not None:
        mem_options = compose_disk_options(test, params, memspec_opts)
        # if the parameters have the disk without "file=" then we only need to
        # add testdir for it.
        if mem_options is None:
            mem_options = os.path.join(test.virtdir, memspec_opts)
        options += " --memspec " + mem_options

    tag_diskspec = 0
    dnum = int(diskspec_num)
    if diskspec_opts is not None:
        tag_diskspec = 1
        opt_names['diskopts_1'] = diskspec_opts

    # diskspec_opts[n] is used in cfg when more than 1 --diskspec is used
    if dnum > 1:
        tag_diskspec = 1
        for i in range(1, dnum + 1):
            opt_names["diskopts_%s" % i] = params.get("diskspec_opts%s" % i)

    if tag_diskspec == 1:
        for i in range(1, dnum + 1):
            disk_options = compose_disk_options(test, params,
                                                opt_names["diskopts_%s" % i])
            options += " --diskspec " + disk_options

    logging.debug("options are %s", options)

    vm = env.get_vm(vm_name)
    option_dict = {}
    option_dict = utils_misc.valued_option_dict(options, r' --(?!-)')
    logging.debug("option_dict is %s", option_dict)

    # A backup of original vm
    vmxml_backup = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)
    logging.debug("original xml is %s", vmxml_backup)

    # Generate empty image for negative test
    if bad_disk is not None:
        bad_disk = os.path.join(test.virtdir, bad_disk)
        os.open(bad_disk, os.O_RDWR | os.O_CREAT)

    # Generate external disk
    if external_disk is not None:
        external_disk = os.path.join(test.virtdir, external_disk)
        commands.getoutput("qemu-img create -f qcow2 %s 1G" % external_disk)

    try:
        # Start qemu-ga on guest if have --quiesce
        if options.find("quiesce") >= 0:
            if vm.is_alive():
                vm.destroy()
            virt_xml_obj = libvirt_xml.VMXML(virsh_instance=virsh)
            virt_xml_obj.set_agent_channel(vm_name)
            vm.start()
            if start_ga == "yes":
                session = vm.wait_for_login()

                # Check if qemu-ga already started automatically
                cmd = "rpm -q qemu-guest-agent || yum install -y qemu-guest-agent"
                stat_install = session.cmd_status(cmd, 300)
                if stat_install != 0:
                    raise error.TestFail("Fail to install qemu-guest-agent, make"
                                         "sure that you have usable repo in guest")

                # Check if qemu-ga already started
                stat_ps = session.cmd_status("ps aux |grep [q]emu-ga")
                if stat_ps != 0:
                    session.cmd("qemu-ga -d")
                    # Check if the qemu-ga really started
                    stat_ps = session.cmd_status("ps aux |grep [q]emu-ga")
                    if stat_ps != 0:
                        raise error.TestFail("Fail to run qemu-ga in guest")

            if domain_state == "paused":
                virsh.suspend(vm_name)

        # Record the previous snapshot-list
        snaps_before = virsh.snapshot_list(vm_name)

        # Run virsh command
        # May create several snapshots, according to configuration
        for count in range(int(multi_num)):
            cmd_result = virsh.snapshot_create_as(vm_name, options,
                                                  ignore_status=True, debug=True)
            output = cmd_result.stdout.strip()
            status = cmd_result.exit_status

            # check status_error
            if status_error == "yes":
                if status == 0:
                    raise error.TestFail("Run successfully with wrong command!")
                else:
                    # Check memspec file should be removed if failed
                    if (options.find("memspec") >= 0
                            and options.find("atomic") >= 0):
                        if os.path.isfile(option_dict['memspec']):
                            os.remove(option_dict['memspec'])
                            raise error.TestFail("Run failed but file %s exist"
                                                 % option_dict['memspec'])
                        else:
                            logging.info("Run failed as expected and memspec file"
                                         " already beed removed")
                    else:
                        logging.info("Run failed as expected")

            elif status_error == "no":
                if status != 0:
                    raise error.TestFail("Run failed with right command: %s"
                                         % output)
                else:
                    # Check the special options
                    snaps_list = virsh.snapshot_list(vm_name)
                    logging.debug("snaps_list is %s", snaps_list)

                    check_snapslist(vm_name, options, option_dict, output,
                                        snaps_before, snaps_list)

    finally:
        # Environment clean
        if options.find("quiesce") >= 0 and start_ga == "yes":
            session.cmd("rpm -e qemu-guest-agent")

        # recover domain xml
        xml_recover(vmxml_backup)
        path = "/var/lib/libvirt/qemu/snapshot/" + vm_name
        if os.path.isfile(path):
            raise error.TestFail("Still can find snapshot metadata")

        # rm bad disks
        if bad_disk is not None:
            os.remove(bad_disk)
