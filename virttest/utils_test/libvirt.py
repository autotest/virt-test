"""
High-level libvirt test utility functions.

This module is meant to reduce code size by performing common test procedures.
Generally, code here should look like test code.

More specifically:
    - Functions in this module should raise exceptions if things go wrong
    - Functions in this module typically use functions and classes from
      lower-level modules (e.g. utils_misc, qemu_vm, aexpect).
    - Functions in this module should not be used by lower-level modules.
    - Functions in this module should be used in the right context.
      For example, a function should not be used where it may display
      misleading or inaccurate info or debug messages.

:copyright: 2013 Red Hat Inc.
"""

import re
import logging

from autotest.client import utils

def cpus_parser(cpulist):
    """
    Parse a list of cpu list, its syntax is a comma separated list,
    with '-' for ranges and '^' denotes exclusive.
    :param cpulist: a list of physical CPU numbers
    """
    hyphens = []
    carets = []
    commas = []
    others = []

    if cpulist is None:
        return None

    else:
        if "," in cpulist:
            cpulist_list = re.split(",", cpulist)
            for cpulist in cpulist_list:
                if "-" in cpulist:
                    tmp = re.split("-", cpulist)
                    hyphens = hyphens + range(int(tmp[0]), int(tmp[-1]) + 1)
                elif "^" in cpulist:
                    tmp = re.split("\^", cpulist)[-1]
                    carets.append(int(tmp))
                else:
                    try:
                        commas.append(int(cpulist))
                    except ValueError:
                        logging.error("The cpulist has to be an "
                                      "integer. (%s)", cpulist)
        elif "-" in cpulist:
            tmp = re.split("-", cpulist)
            hyphens = range(int(tmp[0]), int(tmp[-1]) + 1)
        elif "^" in cpulist:
            tmp = re.split("^", cpulist)[-1]
            carets.append(int(tmp))
        else:
            try:
                others.append(int(cpulist))
                return others
            except ValueError:
                logging.error("The cpulist has to be an "
                              "integer. (%s)", cpulist)

        cpus_set = set(hyphens).union(set(commas)).difference(set(carets))

        return sorted(list(cpus_set))


def cpus_string_to_affinity_list(cpus_string, num_cpus):
    """
    Parse the cpus_string string to a affinity list.

    e.g
    host_cpu_count = 4
    0       -->     [y,-,-,-]
    0,1     -->     [y,y,-,-]
    0-2     -->     [y,y,y,-]
    0-2,^2  -->     [y,y,-,-]
    r       -->     [y,y,y,y]
    """
    # Check the input string.
    single_pattern = r"\d+"
    between_pattern = r"\d+-\d+"
    exclude_pattern = r"\^\d+"
    sub_pattern = r"(%s)|(%s)|(%s)" % (exclude_pattern,
                  single_pattern, between_pattern)
    pattern = r"^((%s),)*(%s)$" % (sub_pattern, sub_pattern)
    if not re.match(pattern, cpus_string):
        logging.debug("Cpus_string=%s is not a supported format for cpu_list."
                      % cpus_string)
    # Init a list for result.
    affinity = []
    for i in range(int(num_cpus)):
        affinity.append('-')
    # Letter 'r' means all cpus.
    if cpus_string == "r":
        for i in range(len(affinity)):
            affinity[i] = "y"
        return affinity
    # Split the string with ','.
    sub_cpus = cpus_string.split(",")
    # Parse each sub_cpus.
    for cpus in sub_cpus:
        if "-" in cpus:
            minmum = cpus.split("-")[0]
            maxmum = cpus.split("-")[-1]
            for i in range(int(minmum), int(maxmum) + 1):
                affinity[i] = "y"
        elif "^" in cpus:
            affinity[int(cpus.strip("^"))] = "-"
        else:
            affinity[int(cpus)] = "y"
    return affinity


def cpu_allowed_list_by_task(pid, tid):
    """
    Get the Cpus_allowed_list in status of task.
    """
    cmd = "cat /proc/%s/task/%s/status|grep Cpus_allowed_list:| awk '{print $2}'" % (pid, tid)
    result = utils.run(cmd, ignore_status=True)
    if result.exit_status:
        return None
    return result.stdout.strip()


def transform_size(value):
    """
    Transform size, make its unit to be bytes.
    :param value: transformed size, format can be
                  11, "11", "11G", "11M", "1.1M" etc.
    """
    try:
        # if value is an integer, just return it
        if isinstance(value, int):
            return value
        human = {'B': 1,
                 'K': 1024,
                 'M': 1048576,
                 'G': 1073741824,
                 'T': 1099511627776
                }
        if not human.has_key(value[-1]):
            try:
                # if value can be format to int, return it
                value = int(value)
                return value
            except ValueError:
                raise error.TestFail("Transformed size format is not valid")
        value = int(float(value[:-1]) * human[value[-1]])
        return value
    except (IndexError, ValueError), detail:
        raise error.TestFail("Size transform failed!:\n %s" % detail)


def get_image_info(image_file):
    """
    Get image information and put it into a dict. Image information like this:
    *******************************
    image: /path/vm1_6.3.img
    file format: raw
    virtual size: 10G (10737418240 bytes)
    disk size: 888M
    ....
    ....
    *******************************
    And the image info dict will be like this
    image_info_dict = { 'format':'raw',
                        'vsize' : '10737418240'
                        'dsize' : '931135488'
                      }
    TODO: Add more information to dict
    """
    try:
        cmd = "qemu-img info %s" % image_file
        image_info = utils.run(cmd, ignore_status=False).stdout.strip()
        image_info_dict = {}
        if image_info:
            for line in image_info.splitlines():
                if line.find("format") != -1:
                    image_info_dict['format'] = line.split(':')[-1].strip()
                elif line.find("virtual size") != -1:
                    vsize = line.split(":")[-1].strip().split(" ")[0]
                    image_info_dict['vsize'] = transform_size(vsize)
                elif line.find("disk size") != -1:
                    dsize = line.split(':')[-1].strip()
                    image_info_dict['dsize'] = transform_size(dsize)
        return image_info_dict
    except (KeyError, IndexError, error.CmdError), detail:
        raise error.TestError("Fail to get information of %s:\n%s" %
                              (image_file, detail))
