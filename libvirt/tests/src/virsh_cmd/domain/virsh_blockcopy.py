import logging, os, commands, re, time
from autotest.client.shared import error
from virttest import utils_libvirtd, virsh
from virttest.libvirt_xml import vm_xml

class JobTimeout(Exception):
    """
    Blockjob timeout in given time.
    """
    def __init__(self, timeout):
        Exception.__init__(self)
        self.timeout = timeout
    def __str__(self):
        return "Block job timeout in %s seconds" % self.timeout

def disk_check(vm_name, disk_src):
    """
    Check if the src_disk exist in given vm
    """
    disk_count = vm_xml.VMXML.get_disk_count(vm_name)
    if disk_count == 0:
        raise error.TestFail("Domain %s has no disk", vm_name)
    disk_list = vm_xml.VMXML.get_disk_source(vm_name)
    src_list = []
    for src in disk_list:
        src_list.append(src.find('source').get('file'))
    blk_list =  vm_xml.VMXML.get_disk_blk(vm_name)
    if disk_src in src_list or disk_src in blk_list:
        logging.debug("Find %s in domain %s", disk_src, vm_name)
    else:
        raise error.TestFail("Can't find %s in domain %s",
                             disk_src, vm_name)

def xml_check(vm_name, target, dest_path, blk_options):
    """
    Check the domain XML for blockcopy job

    @param: vm_name: domain name
    @param: target: domain target dev
    @param: dest_path: path of the copy to create
    @blk_options: block job options
    """
    re1 = 0
    re2 = 0
    #set expect result
    if blk_options.count("--finish"):
    #no <mirror> element and can't find dest_path in vm xml
        expect_re = 0
    elif blk_options.count("--pivot"):
    #no <mirror> element, but can find dest_path in vm xml
        expect_re = 1
    else:
    #find <mirror> element and dest_path in vm xml
        expect_re = 2

    blk_list = vm_xml.VMXML.get_disk_blk(vm_name)
    disk_list = vm_xml.VMXML.get_disk_source(vm_name)
    dev_index = 0
    try:
        try:
            dev_index = blk_list.index(target)
            disk_src = disk_list[dev_index].find('source').get('file')
            if disk_src == dest_path:
                logging.debug("Disk source change to %s", dest_path)
                re1 = 1
            disk_mirror = disk_list[dev_index].find('mirror')
            if disk_mirror is not None:
                disk_mirror_src = disk_mirror.get('file')
                if disk_mirror_src == dest_path:
                    logging.debug("Find %s in <mirror> element", dest_path)
                    re2 = 2
        except Exception, detail:
            logging.error(detail)
    finally:
        if re1 + re2 == expect_re:
            logging.debug("Domain XML check pass")
        else:
            raise error.TestFail("Domain XML check fail")

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
                logging.debug("%s format is %s", dest_path, expect)
            else:
                raise error.TestFail("%s format is not %s",
                                     dest_path, expect)
        else:
            logging.error("Fail to get format for %s", dest_path)
    else:
        logging.error("Image file %s not found", dest_path)

def blockjob_check(vm_name, target, check_point, value):
    """
    Run blookjob command to check block copy progress, bandwidth

    @param vm_name: domain name
    @param target: domian disk target dev
    @param check_point: check progrss, bandwidth, timeout or no_job
    @param value: value of progress, bandwidth, timeout or 0(no_job)
    """
    if check_point not in ["progress", "bandwidth", "no_job"]:
        logging.error("Check point must be: progress, bandwidth, no_job")

    if not len(value) and not value.isdigit():
        raise error.TestFail("Invalid value")

    options = "--info"
    cmd_result = virsh.blockjob(vm_name, target, options,
                                ignore_status=True, debug=True)
    output = cmd_result.stdout.strip()
    err = cmd_result.stderr.strip()
    status = cmd_result.exit_status

    if status == 0:
        if len(err) == 0:
            logging.debug("No block job find")
            if check_point == "no_job":
                return True
        if len(err):
            if check_point == "no_job":
                logging.error("Expect no job but find block job %s", err)
            if check_point == "progress":
                progress = value+" %"
                if re.search(progress, err):
                    return True
            if check_point == "bandwidth":
                bandwidth = value + " MiB/s"
                if bandwidth == output.split(':')[1].strip():
                    logging.debug("Pass as bandwidth = %s", bandwidth)
                    return True
                else:
                    raise error.TestFail("Fail as bandwidth != %s", bandwidth)
    else:
        logging.error("Run blockjob command fail")
    return False

def run_virsh_blockcopy(test, params, env):
    """
    Test command: virsh blockcopy.

    This command can copy a disk backing image chain to dest.
    1. Positive testing
        1.1 Copy a disk to a new image file.
        1.2 Reuse existing destination copy.
        1.3 Valid blockcopy timeout and bandwidth test.
    2. Negative testing
        2.1 Copy a disk to a non-exist directory.
        2.2 Copy a disk with invalid options.
        2.3 Do blcok copy for a persistent domain.
    """

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    target = params.get("target_disk", "")
    # check the source disk
    if len(target) == 0:
        raise error.TestFail("Need target disk to copy")
    else:
        disk_check(vm_name, target)
    dest_path = params.get("dest_path")
    if len(dest_path) == 0:
        tmp_file = time.strftime("%Y-%m-%d-%H.%M.%S.img")
        dest_path = os.path.join(test.tmpdir, tmp_file)
    options = params.get("blockcopy_options", "")
    dest_format = params.get("dest_format", "")
    bandwidth = params.get("blockcopy_bandwidth", "")
    blockcopy_timeout = "yes" == params.get("blockcopy_timeout", "no")
    reuse_external = "yes" == params.get("reuse_external", "no")
    persistent_vm = params.get("persistent_vm", "no")
    status_error = params.get("status_error", "no")
    rerun_flag = 0

    # Prepare transient/persistent vm
    original_xml = vm.backup_xml()
    if persistent_vm == "no" and vm.is_persistent():
        vm.undefine()
    elif persistent_vm == "yes" and not vm.is_persistent():
        vm.define(original_xml)

    # Prepare for --reuse-external option
    if reuse_external:
        options += "--reuse-external"
        # Set rerun_flag=1 to do blockcopy twice, and the first time created
        # file can be reused in the second time, if no dest_path given
        if dest_path == "/path/non-exist":
            if os.path.exists(dest_path) and not os.path.isdir(dest_path):
                os.remove(dest_path)
        else:
            rerun_flag = 1

    # Prepare other options
    if dest_format == "raw":
        options += "--raw"
    if len(bandwidth):
        options += "--bandwidth %s" % bandwidth
    #Set default blockcopy timeout to 300 sec
    timeout = 300
    if blockcopy_timeout:
        status_error = "yes"
        #set minmal value(=1) to make sure copy job will timeout indeed
        timeout = "1"
        if "--wait" not in options:
            options += "--wait --timeout %s" % timeout
        else:
            options += "--timeout %s" % timeout

    # Before raise TestFail, need recover the env
    def cleanup(xml, dest_path):
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
        except Exception, detail:
            logging.error("Cleaning up fail.\n%s", detail)

    def finish_job(vm_name, target, timeout):
        """
        Make sure the block copy job finish.
        """
        job_time = 0
        while job_time < timeout:
            if blockjob_check(vm_name, target, "progress", "100"):
                logging.debug("Block job progress up to 100%")
                break
            else:
                job_time += 2
                time.sleep(2)
        if job_time >= timeout:
            raise JobTimeout(timeout)

    # Run virsh command
    try:
        if rerun_flag == 1:
            options1 = "--wait --raw --finish --verbose"
            cmd_result = virsh.blockcopy(vm_name, target, dest_path, options1,
                                         ignore_status=True, debug=True)
            status = cmd_result.exit_status
            if status != 0:
                raise error.TestFail("Run blockcopy command fail!")
            elif not os.path.exists(dest_path):
                raise error.TestFail("Can't find the created copy!")

        cmd_result = virsh.blockcopy(vm_name, target, dest_path, options,
                                     ignore_status=True, debug=True)
        status = cmd_result.exit_status
    except Exception, detail:
        logging.error(detail)

    if not utils_libvirtd.libvirtd_is_running():
        raise error.TestFail("Libvirtd service is dead.")
    #check_result
    try:
        try:
            if status_error == "no":
                if status == 0:
                    xml_check(vm_name, target, dest_path, options)
                    if options.count("--bandwidth"):
                        blockjob_check(vm_name, target, "bandwidth",
                                       bandwidth)
                    if options.count("pivot") + options.count("finish") == 0:
                        finish_job(vm_name, target, timeout)
                    if options.count("--raw"):
                        format_check(dest_path, "raw")
                else:
                    raise error.TestFail(cmd_result.stderr)
            if status_error == "yes":
                if status:
                    logging.debug("Expect error: %s", cmd_result.stderr)
                else:
                    raise error.TestFail("Expect fail, but run successfully!")
        except JobTimeout, excpt:
            if status_error == "no":
                raise error.TestFail("Run failed with right command: %s", excpt)
    finally:
        cleanup(original_xml, dest_path)
