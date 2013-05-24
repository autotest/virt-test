#!/usr/bin/python
"""
Module used to generate a bug description for qemu.

@copyright: Red Hat 2013
@author: Qingtang Zhou (qzhou@redhat.com)
"""

import os, sys, re, commands, optparse


def _get_log_info_path(result_dir):
    for dir_name, _, file_list in os.walk(result_dir):
        for f in file_list:
            if f.endswith(".INFO"):
                return os.path.join(dir_name, f)
        else:
            # There is only a `debug.log` file in standalone
            # mode, in this case we need to find this file
            # instead.
            for f in file_list:
                if f == "debug.log":
                    return os.path.join(dir_name, f)
    return ""


def get_description_info(result_dir):
    ret = "Description of problem:\n"
    ret += "\n"
    return ret


def get_packages_info(result_dir):
    ret = "Version-Release number of selected component (if applicable):\n"
    cmd = "rpm -qa | grep '"
    cmd += "^kernel"
    cmd += "\|qemu"
    cmd += "\|seabios"
    cmd += "\|virtio"
    cmd += "\|pxe"
    cmd += "\|vgabios"
    cmd += "\|spice"
    cmd += "' | sort"
    ret += "# %s\n" % cmd
    ret += "%s\n" % commands.getoutput(cmd)

    ret += "\nRunning Kernel:\n"
    ret += "%s\n" % commands.getoutput("uname -r")
    ret += "\n"

    ret += "\nHost kernel cli:\n"
    ret += "%s\n" % commands.getoutput("cat /proc/cmdline")
    ret += "\n"

    return ret


def get_reproduce_rate(result_dir):
    ret = "How reproducible:\n"
    ret += "\n"
    return ret


def get_step_info(result_dir):
    log_file_path = _get_log_info_path(result_dir)
    if not log_file_path:
        return ""

    ret = "Steps to Reproduce:\n"
    qemu_cmd = commands.getoutput(r'grep "TestStep" %s' % log_file_path)
    ret += re.sub(r".*\|{1} TestStep:", "", qemu_cmd)
    ret += "\n"
    ret += "\n"

    return ret


def get_actual_result_info(result_dir):
    ret = "Actual results:\n"
    ret += "\n"
    return ret


def get_expected_result_info(result_dir):
    ret = "Expected results:\n"
    ret += "\n"
    return ret


def get_additional_info(result_dir):
    ret = "Additional info:\n"
    ret += "\n%s\n" % get_qemu_cmd_info(result_dir)
    ret += "\n%s\n" % get_qemu_output_info(result_dir)
    ret += "\n%s\n" % get_core_info(result_dir)
    ret += "\n%s\n" % get_cpu_info(result_dir)
    ret += "\n"

    return ret


def get_core_info(result_dir):
    core_info_files = []
    for dir_name, _, file_list in os.walk(result_dir):
        if not re.search("crash.qemu", dir_name):
            continue

        core_info_files = ([os.path.join(dir_name, f) for f in file_list
                            if f in ("gdb_cmd", "report")])
        break

    if not core_info_files:
        return ""

    ret = "Coredump info:\n"
    for f in core_info_files:
        try:
            f_obj = None
            f_obj = open(f)
            ret += "".join(f_obj.readlines())
        finally:
            if f_obj:
                f_obj.close()

    return ret


def get_qemu_cmd_info(result_dir):
    log_file_path = _get_log_info_path(result_dir)
    if not log_file_path:
        return ""

    ret = "Qemu CLI:\n"
    qemu_cmd = commands.getoutput(r'grep "qemu $\|    -" %s' % log_file_path)
    ret += re.sub(r".*\|{1}     ?", "", qemu_cmd)

    return ret


def get_qemu_output_info(result_dir):
    log_file_path = _get_log_info_path(result_dir)
    if not log_file_path:
        return ""

    ret = "Qemu output:\n"
    qemu_cmd = commands.getoutput(r'grep "\[qemu output\]" %s' % log_file_path)
    ret += re.sub(r".*\|{1} \[qemu output\] ", "", qemu_cmd)

    return ret


def get_cpu_info(result_dir):
    ret = ""
    cmd = "lscpu"
    ret += "# %s\n" % cmd
    ret += "%s\n" % commands.getoutput(cmd)
    cmd = "grep flags /proc/cpuinfo | head -n 1"
    ret += "%s" % commands.getoutput(cmd)

    return ret


def create_report(dirname, output_file_name=None):
    """
    Create a bug report with info about an qemu job.

    @param output_file_name: Path to the report file.
    """
    report_text = get_description_info(dirname)
    report_text += get_packages_info(dirname)
    report_text += get_reproduce_rate(dirname)
    report_text += get_step_info(dirname)
    report_text += get_actual_result_info(dirname)
    report_text += get_expected_result_info(dirname)
    report_text += get_additional_info(dirname)

    if output_file_name is None:
        output_file_name = os.path.join(dirname, 'bug_report.txt')

    try:
        output_file = None
        output_file = open(output_file_name, "w")
        output_file.write(report_text)
    finally:
        if output_file:
            output_file.close()


if __name__ == "__main__":
    parser = optparse.OptionParser(
                      usage="%prog -r <result_directory> [-f output_file]")
    parser.add_option("-r", dest="results_dir",
                      help="Path to an autotest results directory")
    parser.add_option("-f", dest="output_file",
                      help="Path to an output file")

    options = parser.parse_args()[0]

    if not options.results_dir:
        print "No autotest results dir specified."
        parser.print_help()
        sys.exit(2)

    results_dir = os.path.abspath(options.results_dir)
    output_file = os.path.abspath(options.output_file)
    if not os.path.isdir(results_dir):
        print "Autotest result directory does not exist"
        parser.print_help()
        sys.exit(1)

    create_report(results_dir, output_file)
    sys.exit(0)
