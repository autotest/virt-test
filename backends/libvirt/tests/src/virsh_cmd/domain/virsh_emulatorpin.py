import os
import logging

from virttest.libvirt_xml import vm_xml
from autotest.client.shared import error
from virttest import utils_libvirtd, virsh
from virttest.utils_test.libvirt import cpus_parser

try:
    from virttest.staging import utils_cgroup
except ImportError:
    # TODO: Obsoleted path used prior autotest-0.15.2/virttest-2013.06.24
    from autotest.client.shared import utils_cgroup


def get_emulatorpin_from_cgroup(params):
    """
    Get a list of domain-specific per block stats from cgroup blkio controller.
    :params: the parameter dictionary
    """

    vm = params.get("vm")

    cpuset_path = \
        utils_cgroup.resolve_task_cgroup_path(vm.get_pid(), "cpuset")

    cpuset_file = os.path.join(cpuset_path, "cpuset.cpus")

    try:
        f_emulatorpin_params = open(cpuset_file, "rU")
        emulatorpin_params_from_cgroup = f_emulatorpin_params.readline()
        f_emulatorpin_params.close()
        return emulatorpin_params_from_cgroup
    except IOError:
        raise error.TestError("Failed to get emulatorpin "
                              "params from %s" % cpuset_file)


def check_emulatorpin(params):
    """
    Check emulator affinity
    :params: the parameter dictionary
    """
    dicts = {}
    vm = params.get("vm")
    vm_name = params.get("main_vm")
    cpu_list = params.get("cpu_list")
    cgconfig = params.get("cgconfig", "on")
    options = params.get("emulatorpin_options")

    result = virsh.emulatorpin(vm_name)
    cmd_output = result.stdout.strip().splitlines()
    logging.debug(cmd_output)
    # Parsing command output and putting them into python dictionary.
    for l in cmd_output[2:]:
        k, v = l.split(':')
        dicts[k.strip()] = v.strip()

    logging.debug(dicts)

    emulator_from_cmd = dicts['*']
    emulatorpin_from_xml = ""

    # To change a running guest with 'config' option, which will affect
    # next boot, if don't shutdown the guest, we need to run virsh dumpxml
    # with 'inactive' option to get guest XML changes.
    if options == "config" and vm and not vm.is_alive():
        emulatorpin_from_xml = \
            vm_xml.VMXML().new_from_dumpxml(vm_name, "--inactive").emulatorpin
    else:
        emulatorpin_from_xml = \
            vm_xml.VMXML().new_from_dumpxml(vm_name).emulatorpin

    # To get guest corresponding emulator/cpuset.cpus value
    # from cpuset controller of the cgroup.
    if cgconfig == "on" and vm and vm.is_alive():
        emulatorpin_from_cgroup = get_emulatorpin_from_cgroup(params)
        logging.debug("The emulatorpin value from "
                      "cgroup: %s", emulatorpin_from_cgroup)

    # To check specified cpulist value with virsh command output
    # and/or cpuset.cpus from cpuset controller of the cgroup.
    if cpu_list:
        if vm and vm.is_alive() and options != "config":
            if (cpu_list != cpus_parser(emulator_from_cmd)) or \
                    (cpu_list != cpus_parser(emulatorpin_from_cgroup)):
                logging.error("To expect emulatorpin %s: %s",
                              cpu_list, emulator_from_cmd)
                return False
        else:
            if cpu_list != cpus_parser(emulatorpin_from_xml):
                logging.error("To expect emulatorpin %s: %s",
                              cpu_list, emulatorpin_from_xml)
                return False

        return True


def get_emulatorpin_parameter(params):
    """
    Get the emulatorpin parameters
    :params: the parameter dictionary
    """
    vm_name = params.get("main_vm")
    vm = params.get("vm")
    options = params.get("emulatorpin_options")
    start_vm = params.get("start_vm", "yes")

    if start_vm == "no" and vm and vm.is_alive():
        vm.destroy()

    result = virsh.emulatorpin(vm_name, options=options)
    status = result.exit_status

    # Check status_error
    status_error = params.get("status_error", "no")

    if status_error == "yes":
        if status or not check_emulatorpin(params):
            logging.info("It's an expected : %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value", status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            logging.info(result.stdout)


def set_emulatorpin_parameter(params):
    """
    Set the emulatorpin parameters
    :params: the parameter dictionary
    """
    vm_name = params.get("main_vm")
    vm = params.get("vm")
    cpulist = params.get("emulatorpin_cpulist")
    options = params.get("emulatorpin_options")
    start_vm = params.get("start_vm", "yes")

    if start_vm == "no" and vm and vm.is_alive():
        vm.destroy()

    result = virsh.emulatorpin(vm_name, cpulist, options)
    status = result.exit_status

    # Check status_error
    status_error = params.get("status_error")

    # Changing affinity for emulator thread dynamically is
    # not allowed when CPU placement is 'auto'
    placement = vm_xml.VMXML().new_from_dumpxml(vm_name).placement
    if placement == "auto":
        status_error = "yes"

    if status_error == "yes":
        if status or not check_emulatorpin(params):
            logging.info("It's an expected : %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value", status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            if check_emulatorpin(params):
                logging.info(result.stdout)
            else:
                raise error.TestFail("The 'cpulist' is inconsistent with"
                                     " 'cpulist' emulatorpin XML or/and is"
                                     " different from emulator/cpuset.cpus"
                                     " value from cgroup cpuset controller")


def run(test, params, env):
    """
    Test emulatorpin tuning

    1) Positive testing
       1.1) get the current emulatorpin parameters for a running/shutoff guest
       1.2) set the current emulatorpin parameters for a running/shutoff guest
    2) Negative testing
       2.1) get emulatorpin parameters for a running/shutoff guest
       2.2) set emulatorpin parameters running/shutoff guest
    """

    # Run test case
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    cgconfig = params.get("cgconfig", "on")
    cpulist = params.get("emulatorpin_cpulist")
    status_error = params.get("status_error", "no")
    change_parameters = params.get("change_parameters", "no")

    # Backup original vm
    vmxml_backup = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)

    test_dicts = dict(params)
    test_dicts['vm'] = vm

    host_cpus = int(open('/proc/cpuinfo').read().count('processor'))
    test_dicts['host_cpus'] = host_cpus

    cpu_list = None

    if cpulist:
        cpu_list = cpus_parser(cpulist)
        test_dicts['cpu_list'] = cpu_list
        logging.debug("CPU list is %s", cpu_list)

    # If the physical CPU N doesn't exist, it's an expected error
    if cpu_list and max(cpu_list) > host_cpus - 1:
        test_dicts["status_error"] = "yes"

    cg = utils_cgroup.CgconfigService()

    if cgconfig == "off":
        if cg.cgconfig_is_running():
            cg.cgconfig_stop()

    # positive and negative testing #########
    try:
        if status_error == "no":
            if change_parameters == "no":
                get_emulatorpin_parameter(test_dicts)
            else:
                set_emulatorpin_parameter(test_dicts)


        if status_error == "yes":
            if change_parameters == "no":
                get_emulatorpin_parameter(test_dicts)
            else:
                set_emulatorpin_parameter(test_dicts)
    finally:
        # Recover cgconfig and libvirtd service
        if not cg.cgconfig_is_running():
            cg.cgconfig_start()
            utils_libvirtd.libvirtd_restart()
        # Recover vm.
        vmxml_backup.sync()
