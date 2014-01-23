import os
import logging
from autotest.client import utils
from autotest.client.shared import error
from virttest import virsh


SYSFS_SYSTEM_PATH = "/sys/devices/system/cpu"


def get_present_cpu():
    """
    Get host present cpu

    :return: the host present cpu number
    """
    if os.path.exists("%s/present" % SYSFS_SYSTEM_PATH):
        cmd = "cat %s/present" % SYSFS_SYSTEM_PATH
        cmd_result = utils.run(cmd, ignore_status=True)
        output = cmd_result.stdout.strip()
        if '-' not in output:
            present = int(output)
        else:
            present = int(output.split('-')[1]) + 1
    elif os.path.exists("%s/cpu0" % SYSFS_SYSTEM_PATH):
        cmd = "ls %s | grep cpu[0-9] | wc -l" % SYSFS_SYSTEM_PATH
        cmd_result = utils.run(cmd, ignore_status=True)
        present = int(cmd_result.stdout.strip())
    else:
        present = None

    return present


def format_map(map_str, map_test, map_length):
    """
    Format cpu map str to tuple

    :param map_str: cpu map string
    :param map_test: template cpu map tuple
    :param map_length: cpu map tuple length
    :return: the cpu map tuple
    """
    cpu_map = ()
    if '-' in map_str:
        param = map_str.split('-')
        for i in range(map_length):
            if i in range(int(param[0]), int(param[1]) + 1):
                cpu_map += ('y',)
            else:
                cpu_map += (map_test[i],)
    else:
        for i in range(map_length):
            if i == int(map_str):
                cpu_map += ('y',)
            else:
                cpu_map += (map_test[i],)

    return cpu_map


def get_online_cpu():
    """
    Get host online cpu map and number

    :return: the host online cpu map tuple
    """
    cpu_map = ()
    map_test = ()
    cpu_map_list = []

    present = get_present_cpu()
    if not present:
        return None

    for i in range(present):
        map_test += ('-',)

    for i in range(present):
        if i == 0:
            cpu_map_list.append('y')
        else:
            cpu_map_list.append('-')

    if os.path.exists("%s/online" % SYSFS_SYSTEM_PATH):
        cmd = "cat %s/online" % SYSFS_SYSTEM_PATH
        cmd_result = utils.run(cmd, ignore_status=True)
        output = cmd_result.stdout.strip()
        if ',' in output:
            output1 = output.split(',')
            for i in range(len(output1)):
                cpu_map = format_map(output1[i], map_test, present)
                map_test = cpu_map
        else:
            cpu_map = format_map(output, map_test, present)
    else:
        for i in range(present):
            if i != 0:
                if os.path.exists("%s/cpu%s/online" % (SYSFS_SYSTEM_PATH, i)):
                    cmd = "cat %s/cpu%s/online" % (SYSFS_SYSTEM_PATH, i)
                    cmd_result = utils.run(cmd, ignore_status=True)
                    output = cmd_result.stdout.strip()
                    if int(output) == 1:
                        cpu_map_list[i] = 'y'
                else:
                    return None
        cpu_map = tuple(cpu_map_list)

    return cpu_map


def run(test, params, env):
    """
    Test the command virsh nodecpumap

    (1) Call virsh nodecpumap
    (2) Call virsh nodecpumap with an unexpected option
    """

    option = params.get("virsh_node_options")
    status_error = params.get("status_error")

    result = virsh.nodecpumap(option, ignore_status=True, debug=True)
    output = result.stdout.strip()
    status = result.exit_status

    # Check result
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
        else:
            logging.info("Run failed as expected")
    else:
        out_value = []
        out = output.split('\n')
        for i in range(3):
            out_value.append(out[i].split()[-1])

        present = get_present_cpu()
        if not present:
            raise error.TestNAError("Host cpu counting not supported")
        else:
            if present != int(out_value[0]):
                raise error.TestFail("Present cpu is not expected")

        cpu_map = get_online_cpu()
        if not cpu_map:
            raise error.TestNAError("Host cpu map not supported")
        else:
            if cpu_map != tuple(out_value[2]):
                logging.info(cpu_map)
                logging.info(tuple(out_value[2]))
                raise error.TestFail("Cpu map is not expected")

        online = 0
        for i in range(present):
            if cpu_map[i] == 'y':
                online += 1
        if online != int(out_value[1]):
            raise error.TestFail("Online cpu is not expected")
