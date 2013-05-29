import logging, os, commands, re, time
from autotest.client.shared import error
from virttest import libvirt_vm, virsh, libvirt_xml

def xml_check(xml, dest_path, level):
    """
    Check the domain XML for blockcopy job

    @param copy_xml: XML file of the domain
    @param: level: domain XML check level
            level = 1, XMl has <mirror> , dest_path, and ready='yes'
            level = 2, XML don't have <mirror> but can find dest_path
            level = 3, XMl don't have <mirror> and can't find dest_path
    """
    xml_content = open(xml, "r").read()
    logging.debug("Domain XML:\n %s", xml_content)
    if re.search("<mirror", xml_content):
        re1 = 1
        logging.debug("Find <mirror> elemnt in domain xml.")
    else:
        re1 = 0
        logging.debug("Can't find <mirror> elemnt in domain xml.")
    if re.search(dest_path, xml_content):
        re2 = 1
        logging.debug("Find %s in domain xml.", dest_path)
    else:
        re2 = 0
        logging.debug("Can' find %s in domain xml.", dest_path)
    if re.search("ready=\'yes\'", xml_content):
        re3 = 1
        logging.debug("Find ready='yes' in domain xml.")
    else:
        re3 = 0
        logging.debug("Can't find ready='yes' in domain xml.")

    if level == 1:
        if re1 + re2 + re3 == 3:
            return True
    elif level == 2:
        if re1 + re3 == 0  and re2 == 1:
            return True
    elif level == 3:
        if re1 + re2 + re3 == 0:
            return True
    else:
        logging.error("level must in [1, 2, 3]")

    return False

def format_check(dest_path, expect):
    """
    Check the image format

    @param dest_path: path of the copy to create
    @param expect: expect format
    """
    logging.debug("Run qemu-img info comamnd on %s", dest_path)
    cmd = "qemu-img info %s | awk '/file format/'" % dest_path
    if os.path.exists(dest_path):
        (status, output) = commands.getstatusoutput(cmd)
        if status == 0:
            logging.debug(dest_path + " " + output)
            if re.search(expect, output):
                return True
        else:
            logging.error("Fail to get format for %s", dest_path)
    else:
        logging.error("Image file %s not found", dest_path)
    return False

def blockjob_check(vm_name, target, check_point, value):
    """
    Run blookjob command to check block copy progress, bandwidth

    @param vm_name: domain name
    @param target: domian disk target dev
    @param check_point: check progrss, bandwidth or timeout
    @param value: value of progress, bandwidth or timeout
    """
    if check_point not in ["progress", "bandwidth", "timeout"]:
        logging.error("check_point must be: progress, bandwidth or timeout")

    if not len(value) and not value.isdigit():
        raise error.TestFail("Invalid value")

    try:
        options = "--info"
        cmd_result = virsh.blockjob(vm_name, target, options,
                                    ignore_status=True, debug=True)
        output = cmd_result.stdout.strip()
        err = cmd_result.stderr.strip()
        status = cmd_result.exit_status

    except Exception, detail:
        exception = True
        logging.error("%s: %s", detail.__class__, detail)

    if status == 0:
        if len(err):
            if check_point == "progress":
                progress = value+" %"
                if re.search(progress, err):
                    return True
            if check_point == "bandwidth":
                bandwidth = value + " MiB/s"
                if bandwidth == output.split(':')[1].strip():
                    logging.debug("Pass, bandwidth = %s", bandwidth)
                    return True
                else:
                    logging.error("Fail, bandwidth != %s", bandwidth)
            if check_point == "timeout":
                logging.error("Block copy job desen't timeout in %s sec, but "
                              "expect timeout", value)
        elif check_point == "timeout":
            logging.debug("Block copy job timeout in %s sec", value)
            return True
        else:
            logging.error("Doesn't find block copy job for %s on %s", vm_name,
                           target)
    else:
        logging.error("Run blockjob %s %s fail", vm_name, target,)
    return False

def run_virsh_blockcopy(test, params, env):
    """
    Test command: virsh blockcopy.

    This command can copy a disk backing image chain to dest.
    1. Positive testing
        1.1 Copy a disk to a new image file.
        1.2 Reuse existing destination copy.
        1.3 Valid timeout and bandwidth test.
    2. Negative testing
        2.1 Copy a disk to a non-exist directory.
        2.2 Copy a disk with invalid options.
        2.3 Do blcok copy for a persistent domain.
    """

    vm_name = params.get("main_vm", "vm1")
    vm = env.get_vm(params["main_vm"])

    dest_path = params.get("dest_path")
    if len(dest_path) == 0:
        tmp_file = time.strftime("%Y-%m-%d-%H.%M.%S.img")
        dest_path = os.path.join("/tmp", tmp_file)
    options = params.get("blockcopy_options", "")
    dest_format = params.get("dest_format", "")
    bandwidth = params.get("bandwidth", "")
    timeout = params.get("timeout", "no")
    reuse_external = params.get("reuse_external", "no")
    persistent_vm = params.get("persistent_vm", "no")
    status_error = params.get("status_error", "no")
    rerun_flag = 0

    # Prepare transient/persistent vm
    original_xml = vm.backup_xml()
    if persistent_vm == "no" and vm.is_persistent():
        vm.undefine()
    elif persistent_vm == "yes" and not vm.is_persistent():
        vm.define(original_xml)

    # Get a source disk
    try:
        blklist = libvirt_xml.VMXML.get_disk_blk(vm_name)
        if blklist == None:
            raise error.TestFail("Cannot find disk in domain %s" % vm_name)
        # Select the first block device from disks
        target = blklist[0]
    except Exception, detail:
        logging.error("Fail to get first block device.\n%s", detail)

    # Prepare for --reuse-external option
    rename_dest = 0
    dest_bk = ""
    if reuse_external == "yes":
        # Set rerun_flag=1 to do blockcopy twice, and the first time created
        # file can be reused in the second time, if no dest_path given
        if dest_path == "/tmp/non-exist.img":
            if os.path.exists(dest_path):
                dest_bk = dest_path + ".blcokcopy.rename"
                if os.rename(dest_path, dest_bk):
                    logging.error("Rename %s to %s failed", dest_path, dest_bk)
                else:
                    rename_dest = 1
        elif not os.path.exists(dest_path):
            rerun_flag = 1
        options += "--reuse-external"

    # Prepare other options
    if dest_format == "raw":
        options += "--raw"
    if len(bandwidth):
        options += "--bandwidth %s" % bandwidth
    if timeout != "no":
        status_error = "yes"
        if timeout == "yes":
        #set minmal value(=1) to make sure copy job will timeout
            timeout = "1"
        if "--wait" not in options:
            options += "--wait --timeout %s" % timeout
        else:
            options += "--timeout %s" % timeout

    # Before raise TestFail, need recover the env
    def cleanup(xml, dest_path, rename_dest):
        """
        Re-define the domain and recover the dest file
        """
        try:
            if not vm.is_alive():
                raise error.TestFail("Domain is dead.")
            else:
                vm.destroy()
                virsh.define(xml)
            if os.path.exists(dest_path):
                os.remove(dest_path)
            if rename_dest == 1:
                if os.rename(dest_bk, dest_path):
                    logging.error("Rename %s to %s failed", dest_bk, dest_path)
        except Exception, detail:
            logging.error("Cleaning up fail.\n%s", detail)

    def finish_job(vm_name, target, limit_time):
        """
        Make sure the block copy job finish.
        """
        timeout = 0
        while timeout < limit_time:
            if blockjob_check(vm_name, target, "progress", "100"):
                logging.debug("Blockcopy job progress up to 100%")
                break
            else:
                timeout += 2
                time.sleep(2)

    # Run virsh command
    exception = False
    try:
        if rerun_flag == 1:
            options1 = "--wait --raw --finish --verbose"
            cmd_result = virsh.blockcopy(vm_name, target, dest_path, options1,
                                         ignore_status=True, debug=True)
            status = cmd_result.exit_status
            if status != 0:
                exception = True
                raise error.TestFail("Run blockcopy fail!")
            elif not os.path.exists(dest_path):
                exception = True
                raise error.TestFail("Can't find the dest file!")

        cmd_result = virsh.blockcopy(vm_name, target, dest_path, options,
                                     ignore_status=True, debug=True)
        output = cmd_result.stdout.strip()
        status = cmd_result.exit_status

    except Exception, detail:
        exception = True
        logging.error("%s: %s", detail.__class__, detail)

    # Check result
    if not libvirt_vm.service_libvirtd_control("status"):
        raise error.TestFail("Libvirtd service is dead.")

    if status_error == "no":
        if status == 0:
            if not os.path.exists(dest_path):
                exception = True
                raise error.TestFail("Can't find the dest file!")
            elif re.search("--raw", options):
                if (not re.search("--pivot", options) and
                   not re.search("--finish", options)):
                    finish_job(vm_name, target, 120)
                    copy_xml = vm.backup_xml()
                    if (xml_check(copy_xml, dest_path, 1) and
                        format_check(dest_path, "raw")):
                        logging.info("Blockcopy --raw test pass!")
                    else:
                        exception = True
                        raise error.TestFail("Blockcopy --raw test check fail!")
                elif format_check(dest_path, "raw"):
                    exception = True
                    raise error.TestFail("Image format is not raw!")
            elif re.search("--bandwidth", options):
                if (not re.search("--pivot", options) and
                   not re.search("--finish", options)):
                    finish_job(vm_name, target, 120)
                    copy_xml = vm.backup_xml()
                    if (xml_check(copy_xml, dest_path, 1) and
                        blockjob_check(vm_name, target, "bandwidth", bandwidth)):
                        logging.info("Blockcopy --bandwidth test check pass!")
                    else:
                        exception = True
                        raise error.TestFail("Blockcopy --bandwidth test "
                                             "check fail!")
                else:
                    logging.info("Skip bandwidth check!")
            elif re.search("--pivot", options):
                copy_xml = vm.backup_xml()
                if xml_check(copy_xml, dest_path, 2):
                    logging.info("Blockcopy --pivot test check pass!")
                else:
                    exception = True
                    raise error.TestFail("Blockcopy --pivot test check fail!")
            elif re.search("--finish", options):
                copy_xml = vm.backup_xml()
                if xml_check(copy_xml, dest_path, 3):
                    logging.info("Blockcopy --finish test check pass!")
                else:
                    exception = True
                    raise error.TestFail("Blockcopy --finish test check fail!")
            else:
                finish_job(vm_name, target, 120)
                copy_xml = vm.backup_xml()
                if (xml_check(copy_xml, dest_path, 1) and
                    blockjob_check(vm_name, target, "progress", "100")):
                    logging.info("Blockcopy test check pass!")
                else:
                    exception = True
                    raise error.TestFail("Blockcopy test check fail!")

        else:
            exception = True
            raise error.TestFail("Expect succeed, but run fail!")

    elif status_error == "yes":
        if status == 0:
            exception = True
            raise error.TestFail("Expect fail, but run successfully!")
        elif re.search("--timeout", options):
            finish_job(vm_name, target, 1)
            copy_xml = vm.backup_xml()
            if (xml_check(copy_xml, dest_path, 3) and
                blockjob_check(vm_name, target, "timeout", timeout)):
                logging.info("Block copy timeout test check pass!")
            else:
                exception = True
                raise error.TestFail("Block copy timeout test check fail!")
    else:
        exception = True
        raise error.TestFail("The status_error must be 'yes' or 'no'!")

    # Cleanup
    cleanup(original_xml, dest_path, rename_dest)

    if exception:
        raise error.TestError("Error occurred. \n%s: %s" % (detail.__class__, detail))
