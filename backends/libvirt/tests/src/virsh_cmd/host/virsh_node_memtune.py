import os
import logging
from autotest.client.shared import error
from virttest import virsh


_SYSFS_MEMORY_KSM_PATH = "/sys/kernel/mm/ksm"


def recovery_ksm_files_contents(ksm_params, change_list):
    """
    Recovery ksm relevant files are changed
    :params: change_list: the ksm files list are changed
    """
    for kt in change_list:
        key = "shm_" + kt
        ksm_file = os.path.join(_SYSFS_MEMORY_KSM_PATH, kt)
        cmd = "echo %s > %s" % (ksm_params[key], ksm_file)
        if os.system(cmd):
            logging.error("Failed to execute %s", cmd)


def get_ksm_values_and_change_list():
    """
    Get ksm relevant files contents and list are changed
    """
    ksm_params = {}
    # Currently, can be changed node memory parameters by libvirt
    change_list = ['pages_to_scan', 'sleep_millisecs',
                   'merge_across_nodes']

    ksm_files = {'shm_pages_to_scan': 'pages_to_scan',
                 'shm_sleep_millisecs': 'sleep_millisecs',
                 'shm_pages_shared': 'pages_shared',
                 'shm_pages_sharing': 'pages_sharing',
                 'shm_pages_unshared': 'pages_unshared',
                 'shm_pages_volatile': 'pages_volatile',
                 'shm_full_scans': 'full_scans',
                 'shm_merge_across_nodes': 'merge_across_nodes'}

    for k, v in ksm_files.items():
        sharing_file = os.path.join(_SYSFS_MEMORY_KSM_PATH, v)
        if os.access(sharing_file, os.R_OK):
            ksm_params[k] = open(sharing_file, 'r').read().strip()
        else:
            # The 'merge_across_nodes' is supported by specific kernel
            if v in change_list:
                change_list.remove(v)

    return (ksm_params, change_list)


def check_node_memtune(params, ksm_dicts):
    """
    Check node memory tuning parameters value
    :params: the parameter dictionary
    """
    change_parameters = params.get("change_parameters", "no")
    change_list = ksm_dicts.get('change_list')

    if change_parameters == "no":
        for k in params.keys():
            if params[k] != ksm_dicts[k]:
                logging.error("To expect %s value is %s", k, ksm_dicts[k])
                return False
    else:
        for k in change_list:
            key = "shm_" + k
            if params.get(key) and params[key] != ksm_dicts[key]:
                logging.error("To expect %s value is %s", key, ksm_dicts[key])
                return False

    return True


def get_node_memtune_parameter(params):
    """
    Get the node memory parameters
    :params: the parameter dictionary
    """
    options = params.get("options")
    result = virsh.node_memtune(options)
    status = result.exit_status

    _params = {}

    for i in result.stdout.strip().split('\n\t')[1:]:
        _params[i.split(' ')[0]] = i.split(' ')[-1]

    logging.debug(_params)

    (ksm_dicts, change_list) = get_ksm_values_and_change_list()
    ksm_dicts['change_list'] = change_list

    # Check status_error
    status_error = params.get("status_error", "no")

    if status_error == "yes":
        if status:
            logging.info("It's an expected error: %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value" % status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            if check_node_memtune(_params, ksm_dicts):
                logging.info(result)
            else:
                raise error.TestFail("The memory parameters "
                                     "mismatch with result")


def set_node_memtune_parameter(params):
    """
    Set the node memory parameters
    :params: the parameter dictionary
    """
    options = params.get("options")
    shm_pages_to_scan = params.get("shm_pages_to_scan")
    shm_sleep_millisecs = params.get("shm_sleep_millisecs")
    shm_merge_across_nodes = params.get("shm_merge_across_nodes")

    result = virsh.node_memtune(shm_pages_to_scan, shm_sleep_millisecs,
                                shm_merge_across_nodes, options=options)

    status = result.exit_status

    (ksm_dicts, change_list) = get_ksm_values_and_change_list()
    ksm_dicts['change_list'] = change_list

    # Check status_error
    status_error = params.get("status_error", "no")

    # the 'merge_across_nodes' is supported by specific kernel
    if shm_merge_across_nodes and not \
            os.access("%s/merge_across_nodes" % _SYSFS_MEMORY_KSM_PATH, os.R_OK):
        status_error = "yes"

    if status_error == "yes":
        if status:
            logging.info("It's an expected error: %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value" % status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            if check_node_memtune(params, ksm_dicts):
                logging.info(result)
            else:
                raise error.TestFail("The memory parameters "
                                     "mismatch with result")


def run(test, params, env):
    """
    Test node memory tuning

    1) Positive testing
       1.1) get the current node memory parameters for a running/shutoff guest
       1.2) set the current node memory parameters for a running/shutoff guest
    2) Negative testing
       2.1) get node memory parameters
       2.2) set node memory parameters
           2.2.1) invalid parameters
           2.2.2) invalid options with correct parameters
    """

    # Run test case
    status_error = params.get("status_error", "no")
    change_parameters = params.get("change_parameters", "no")

    (ksm_params, change_list) = get_ksm_values_and_change_list()

    # Backup ksm relevant files contents
    ksm_backup = dict(ksm_params)

    # positive and negative testing #########

    if status_error == "no":
        if change_parameters == "no":
            try:
                get_node_memtune_parameter(params)
            except error.TestFail, detail:
                # Recovery ksm relevant files contents
                recovery_ksm_files_contents(ksm_backup, change_list)
                raise error.TestFail("Failed to get node memory parameters.\n"
                                     "Detail: %s." % detail)
        else:
            try:
                set_node_memtune_parameter(params)
            except error.TestFail, detail:
                # Recovery ksm relevant files contents
                recovery_ksm_files_contents(ksm_backup, change_list)
                raise error.TestFail("Failed to set node memory parameters.\n"
                                     "Detail: %s." % detail)

    if status_error == "yes":
        if change_parameters == "no":
            try:
                get_node_memtune_parameter(params)
            except error.TestFail, detail:
                # Recovery ksm relevant files contents
                recovery_ksm_files_contents(ksm_backup, change_list)
                raise error.TestFail("Failed to get node memory parameters.\n"
                                     "Detail: %s." % detail)
        else:
            try:
                set_node_memtune_parameter(params)
            except error.TestFail, detail:
                # Recovery ksm relevant files contents
                recovery_ksm_files_contents(ksm_backup, change_list)
                raise error.TestFail("Failed to set node memory parameters.\n"
                                     "Detail: %s." % detail)

    # Recovery ksm relevant files contents
    recovery_ksm_files_contents(ksm_backup, change_list)
