import os
import logging
import commands
import thread
import time
from autotest.client.shared import error
from virttest import virsh, utils_libvirtd


def check_flag(file_flag):
    """
    Check if file flag include O_DIRECT.

    Note, O_DIRECT is defined as:
    #define O_DIRECT        00040000        /* direct disk access hint */
    """

    if int(file_flag) == 4:
        logging.info("File flags include O_DIRECT")
        return True
    else:
        logging.error("File flags doesn't include O_DIRECT")
        return False


def check_bypass(dump_file):
    """
    Get the file flags of domain core dump file and check it.
    """

    cmd1 = "lsof -w %s >/dev/null 2>&1" % dump_file
    while True:
        if os.path.exists(dump_file):
            if not os.system(cmd1):
                cmd2 = ("cat /proc/$(%s |awk '/libvirt_i/{print $2}')/fdinfo/1"
                        "|grep flags|awk '{print $NF}'" % cmd1)
                (status, output) = commands.getstatusoutput(cmd2)
                if status == 0:
                    if len(output):
                        logging.debug("The flags of dumped file: %s ", output)
                        file_flag = output[-5]
                        if check_flag(file_flag):
                            logging.info("Bypass file system cache "
                                         "successfully when dumping")
                        else:
                            raise error.TestFail("Bypass file system cache "
                                                 "fail when dumping")
                        break
                else:
                    logging.error("Fail to get the flags of dumped file")
                    return 1

    thread.exit_thread()


def run_virsh_dump(test, params, env):
    """
    Test command: virsh dump.

    This command can dump the core of a domain to a file for analysis.
    1. Positive testing
        1.1 Dump domain with valid options.
        1.2 Avoid file system cache when dumping.
        1.3 Compress the dump images to valid/invalid formats.
    2. Negative testing
        2.1 Dump domain to a non-exist directory.
        2.2 Dump domain with invalid option.
        2.3 Dump a shut-off domain.
    """

    vm_name = params.get("main_vm", "vm1")
    vm = env.get_vm(params["main_vm"])
    options = params.get("dump_options")
    dump_file = params.get("dump_file", "vm.core")
    if os.path.dirname(dump_file) is "":
        dump_file = os.path.join(test.tmpdir, dump_file)
    dump_image_format = params.get("dump_image_format")
    start_vm = params.get("start_vm")
    status_error = params.get("status_error", "no")
    qemu_conf = "/etc/libvirt/qemu.conf"

    # prepare the vm state
    if vm.is_alive() and start_vm == "no":
        vm.destroy()

    if vm.is_dead() and start_vm == "yes":
        vm.start()

    def check_domstate(actual, options):
        """
        Check the domain status according to dump options.
        """

        if options.find('live') >= 0:
            domstate = "running"
            if options.find('crash') >= 0 or options.find('reset') > 0:
                domstate = "running"
        elif options.find('crash') >= 0:
            domstate = "shut off"
            if options.find('reset') >= 0:
                domstate = "running"
        elif options.find('reset') >= 0:
            domstate = "running"
        else:
            domstate = "running"

        if start_vm == "no":
            domstate = "shut off"

        logging.debug("Domain should %s after run dump %s", domstate, options)

        if domstate == actual:
            return True
        else:
            return False

    def check_dump_format(dump_image_format, dump_file):
        """
        Check the format of dumped file.

        If 'dump_image_format' is not specified or invalid in qemu.conf, then
        the file shoule be normal raw file, otherwise it shoud be compress to
        specified format, the supported compress format including: lzop, gzip,
        bzip2, and xz.
        """

        valid_format = ["lzop", "gzip", "bzip2", "xz"]
        if len(dump_image_format) == 0 or dump_image_format not in valid_format:
            logging.debug("No need check the dumped file format")
            return True
        else:
            file_cmd = "file %s" % dump_file
            (status, output) = commands.getstatusoutput(file_cmd)
            if status == 0:
                logging.debug("Run file %s output: %s", dump_file, output)
                actual_format = output.split(" ")[1]
                if actual_format == dump_image_format:
                    if dump_image_format in valid_format:
                        logging.info("Compress dumped file to %s successfully",
                                     dump_image_format)
                    return True
                else:
                    logging.error("Compress dumped file to %s fail",
                                  dump_image_format)
                    return False
            else:
                logging.error("Fail to check dumped file %s", dump_file)
                return False

    # Configure dump_image_format in /etc/libvirt/qemu.conf.
    if len(dump_image_format) != 0:
        conf_cmd = ("echo dump_image_format = \\\"%s\\\" >> %s" %
                    (dump_image_format, qemu_conf))
        if os.system(conf_cmd):
            logging.error("Config dump_image_format to %s fail",
                          dump_image_format)
        utils_libvirtd.libvirtd_restart()

    # Deal with bypass-cache option
    if options.find('bypass-cache') >= 0:
        thread.start_new_thread(check_bypass, (dump_file,))
        # Guarantee check_bypass function has run before dump
        time.sleep(5)

    # Run virsh command
    cmd_result = virsh.dump(vm_name, dump_file, options,
                            ignore_status=True, debug=True)
    status = cmd_result.exit_status

    # Check libvirtd status
    if utils_libvirtd.libvirtd_is_running():
        if check_domstate(vm.state(), options):
            if status_error == "yes":
                if status == 0:
                    raise error.TestFail("Expect fail, but run successfully")
            if status_error == "no":
                if status != 0:
                    raise error.TestFail("Expect succeed, but run fail")
                else:
                    if os.path.exists(dump_file):
                        if check_dump_format(dump_image_format, dump_file):
                            logging.info("Successfully dump domain to %s",
                                         dump_file)
                        else:
                            raise error.TestFail("The format of dumped file "
                                                 "is wrong.")
                    else:
                        raise error.TestFail(
                            "Fail to find domain dumped file.")

        else:
            raise error.TestFail("Domain status check fail.")
    else:
        raise error.TestFail("Libvirtd service is dead.")

    if os.path.isfile(dump_file):
        os.remove(dump_file)

    if len(dump_image_format) != 0:
        clean_qemu_conf = "sed -i '$d' %s " % qemu_conf
        if os.system(clean_qemu_conf):
            raise error.TestFail("Fail to recover %s", qemu_conf)
