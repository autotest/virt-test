import os, commands, logging
from autotest.client.shared import error
from virttest import virsh


def check_node_memtune(params):
    """
    Compare weight and device-weights value with guest XML configuration
    @params: the parameter dictionary
    """

    change_parameters = params.get("change_parameters", "no")
    sysfs_memory_shared_path = "/sys/kernel/mm/ksm"
    dicts = {}
    # Currently, can be changed node memory parameters by libvirt
    change_list = [ 'pages_to_scan', 'sleep_millisecs',
                    'merge_across_nodes' ]

    ksm_files = { 'shm_pages_to_scan'      : 'pages_to_scan',
                  'shm_sleep_millisecs'    : 'sleep_millisecs',
                  'shm_pages_shared'       : 'pages_shared',
                  'shm_pages_sharing'      : 'pages_sharing',
                  'shm_pages_unshared'     : 'pages_unshared',
                  'shm_pages_volatile'     : 'pages_volatile',
                  'shm_full_scans'         : 'full_scans',
                  'shm_merge_across_nodes' : 'merge_across_nodes' }

    for k, v in ksm_files.items():
        sharing_file = os.path.join(sysfs_memory_shared_path, v)
        if os.access(sharing_file, os.R_OK):
            dicts[k] = commands.getoutput("cat %s" % sharing_file)
        else:
            # The 'merge_across_nodes' is supported by specific kernel
            change_list.remove(v)

    if change_parameters == "no":
        for k in  params.keys():
            if params[k] != dicts[k]:
                logging.error("To expect %s value is %s", k, dicts[k])
                return False
    else:
        for k in  change_list:
            key = "shm_" + k
            if params.get(key) and params[key] != dicts[key]:
                logging.error("To expect %s value is %s", key, dicts[key])
                return False

    return True


def get_node_memtune_parameter(params):
    """
    Get the node memory parameters
    @params: the parameter dictionary
    """
    options = params.get("memtune_options")
    result = virsh.node_memtune(options=options)
    status = result.exit_status

    test_dict = {}

    for i in result.stdout.strip().split('\n\t')[1:]:
        test_dict[i.split(' ')[0]]=i.split(' ')[-1]

    logging.debug(test_dict)

    # Check status_error
    status_error = params.get("status_error", "no")

    if status_error == "yes":
        if status:
            logging.info("It's an expected error: %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value", status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            if check_node_memtune(test_dict):
                logging.info(result.stdout)
            else:
                raise error.TestFail("The memory parameters "
                                     "mismatch with result")

def set_node_memtune_parameter(params):
    """
    Set the node memory parameters
    @params: the parameter dictionary
    """
    options = params.get("memtune_options")
    shm_pages_to_scan = params.get("shm_pages_to_scan")
    shm_sleep_millisecs = params.get("shm_sleep_millisecs")
    shm_merge_across_nodes = params.get("shm_merge_across_nodes")

    result = virsh.node_memtune(shm_pages_to_scan=shm_pages_to_scan,
                                shm_sleep_millisecs=shm_sleep_millisecs,
                                shm_merge_across_nodes=shm_merge_across_nodes,
                                options=options)

    status = result.exit_status

    # Check status_error
    status_error = params.get("status_error", "no")

    # the 'merge_across_nodes' is supported by specific kernel
    if shm_merge_across_nodes and not \
        os.access("/sys/kernel/mm/ksm/merge_across_nodes", os.R_OK):
        status_error = "yes"

    if status_error == "yes":
        if status:
            logging.info("It's an expected error: %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value", status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            if check_node_memtune(params):
                logging.info(result.stdout)
            else:
                raise error.TestFail("The memory parameters "
                                     "mismatch with result")

def run_virsh_node_memtune(test, params, env):
    """
    Test node memory tuning

    1) Positive testing
       1.1) get the current node memory parameters for a running/shutoff guest
       1.2) set the current node memory parameters for a running/shutoff guest
           1.2.1) set valid 'shm-pages-to-scan parameters
           1.2.2) set valid 'shm-sleep-millisecs' parameters
           1.2.3) set valid 'shm-merge-across-nodes' parameters
    2) Negative testing
       2.1) get node memory parameters
           2.1.1) invalid options
       2.2) set node memory parameters
           2.2.1) invalid parameters
               2.2.1.1) invalid 'shm-pages-to-scan' parameters
               2.2.1.2) invalid 'shm-sleep-millisecs' parameters
               2.2.1.3) invalid 'shm-merge-across-nodes' parameters
           2.2.2) invalid options with correct parameters
    """

    # Run test case
    status_error = params.get("status_error", "no")
    change_parameters = params.get("change_parameters", "no")

    ########## positive and negative testing #########

    if status_error == "no":
        if change_parameters == "no":
            get_node_memtune_parameter(params)
        else:
            set_node_memtune_parameter(params)

    if status_error == "yes":
        if change_parameters == "no":
            get_node_memtune_parameter(params)
        else:
            set_node_memtune_parameter(params)

