import re
import logging
import os
from autotest.client.shared import utils, error
from virttest import virsh

try:
    from virttest.staging import utils_cgroup
except ImportError:
    from autotest.client.shared import utils_cgroup


def run(test, params, env):
    """
    Test command: virsh schedinfo.

    This version provide base test of virsh schedinfo command:
    virsh schedinfo <vm> [--set<set_ref>]
    TODO: to support more parameters.

    1) Get parameters and prepare vm's state
    2) Prepare test options.
    3) Run schedinfo command to set or get parameters.
    4) Get schedinfo in cgroup
    5) Recover environment like vm's state
    6) Check result.
    """
    def get_parameter_in_cgroup(vm, cgroup_type, parameter):
        """
        Get vm's cgroup value.

        :Param vm: the vm object
        :Param cgroup_type: type of cgroup we want, vcpu or emulator.
        :Param parameter: the cgroup parameter of vm which we need to get.
        :return: False if expected controller is not mounted.
                 else return value's result object.
        """
        cgroup_path = \
            utils_cgroup.resolve_task_cgroup_path(vm.get_pid(), "cpu")

        if not cgroup_type == "emulator":
            # When a VM has an 'emulator' child cgroup present, we must
            # strip off that suffix when detecting the cgroup for a machine
            if os.path.basename(cgroup_path) == "emulator":
                cgroup_path = os.path.dirname(cgroup_path)
            cgroup_file = os.path.join(cgroup_path, parameter)
        else:
            cgroup_file = os.path.join(cgroup_path, parameter)

        cg_file = None
        try:
            try:
                cg_file = open(cgroup_file)
                result = cg_file.read()
            except IOError:
                raise error.TestError("Failed to open cgroup file %s"
                                      % cgroup_file)
        finally:
            if cg_file is not None:
                cg_file.close()
        return result.strip()

    def schedinfo_output_analyse(result, set_ref, scheduler="posix"):
        """
        Get the value of set_ref.

        :param result: CmdResult struct
        :param set_ref: the parameter has been set
        :param scheduler: the scheduler of qemu(default is posix)
        """
        output = result.stdout.strip()
        if not re.search("Scheduler", output):
            raise error.TestFail("Output is not standard:\n%s" % output)

        result_lines = output.splitlines()
        set_value = None
        for line in result_lines:
            key_value = line.split(":")
            key = key_value[0].strip()
            value = key_value[1].strip()
            if key == "Scheduler":
                if value != scheduler:
                    raise error.TestNAError("This test do not support"
                                            " %s scheduler." % scheduler)
            elif key == set_ref:
                set_value = value
                break
        return set_value

    # Prepare vm test environment
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    domid = vm.get_id()
    domuuid = vm.get_uuid()

    # Prepare test options
    vm_ref = params.get("schedinfo_vm_ref", "domname")
    options_ref = params.get("schedinfo_options_ref", "")
    options_suffix = params.get("schedinfo_options_suffix", "")
    schedinfo_param = params.get("schedinfo_param", "vcpu")
    set_ref = params.get("schedinfo_set_ref", "")
    cgroup_ref = params.get("schedinfo_cgroup_ref", "cpu.shares")
    set_value = params.get("schedinfo_set_value", "")
    set_value_expected = params.get("schedinfo_set_value_expected", "")
    # The default scheduler on qemu/kvm is posix
    scheduler_value = "posix"
    status_error = params.get("status_error", "no")

    if vm_ref == "domid":
        vm_ref = domid
    elif vm_ref == "domname":
        vm_ref = vm_name
    elif vm_ref == "domuuid":
        vm_ref = domuuid
    elif vm_ref == "hex_id":
        if domid == '-':
            vm_ref = domid
        else:
            vm_ref = hex(int(domid))

    if set_ref == "none":
        options_ref = "--set"
        set_ref = None
    elif set_ref:
        if set_value:
            options_ref = "--set %s=%s" % (set_ref, set_value)
        else:
            options_ref = "--set %s" % set_ref

    options_ref += options_suffix

    # Run command
    result = virsh.schedinfo(vm_ref, options_ref,
                             ignore_status=True, debug=True)
    status = result.exit_status

    # VM must be running to get cgroup parameters.
    if not vm.is_alive():
        vm.start()
    set_value_of_cgroup = get_parameter_in_cgroup(vm, cgroup_type=schedinfo_param,
                                                  parameter=cgroup_ref)
    vm.destroy()

    if set_ref:
        set_value_of_output = schedinfo_output_analyse(result, set_ref,
                                                       scheduler_value)

    # Check result
    if status_error == "no":
        if status:
            raise error.TestFail("Run failed with right command.")
        else:
            if set_ref and set_value_expected:
                logging.info("value will be set:%s\n"
                             "set value in output:%s\n"
                             "set value in cgroup:%s\n"
                             "expected value:%s" % (
                                 set_value, set_value_of_output,
                                 set_value_of_cgroup, set_value_expected))
                if set_value_of_output is None:
                    raise error.TestFail("Get parameter %s failed." % set_ref)
                if not (set_value_expected == set_value_of_output):
                    raise error.TestFail("Run successful but value "
                                         "in output is not expected.")
                if not (set_value_expected == set_value_of_cgroup):
                    raise error.TestFail("Run successful but value "
                                         "in cgroup is not expected.")
    else:
        if not status:
            raise error.TestFail("Run successfully with wrong command.")
