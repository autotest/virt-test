import logging
import re

from autotest.client import utils
from autotest.client.shared import error
from virttest import virsh, utils_test
from virttest.libvirt_xml import vm_xml


def run(test, params, env):
    """
    Test the command virsh vcpupin

    (1) Get the host and guest cpu count
    (2) Call virsh vcpupin for each vcpu with pinning of each cpu
    (3) Check whether the virsh vcpupin has pinned the respective vcpu to cpu
    """

    def affinity_from_vcpuinfo(domname, vcpu):
        """
        This function returns list of the vcpu's affinity from
        virsh vcpuinfo output

        :param domname: VM Name to operate on
        :param vcpu: vcpu number for which the affinity is required
        """

        output = virsh.vcpuinfo(domname).stdout.rstrip()
        affinity = re.findall('CPU Affinity: +[-y]+', output)
        total_affinity = affinity[int(vcpu)].split()[-1].strip()
        actual_affinity = list(total_affinity)
        return actual_affinity

    def check_vcpupin(domname, vcpu, cpu_list, pid):
        """
        This function checks the actual and the expected affinity of given vcpu
        and raises error if not matchs

        :param domname:  VM Name to operate on
        :param vcpu: vcpu number for which the affinity is required
        :param cpu: cpu details for the affinity
        """

        expected_output = utils_test.libvirt.cpus_string_to_affinity_list(
            cpu_list,
            host_cpu_count)
        actual_output = affinity_from_vcpuinfo(domname, vcpu)

        if expected_output == actual_output:
            logging.info("successfully pinned cpu_list: %s --> vcpu: %s",
                         cpu_list, vcpu)
        else:
            raise error.TestFail("Command 'virsh vcpupin %s %s %s'not "
                                 "succeeded, cpu pinning details not "
                                 "updated properly in virsh vcpuinfo "
                                 "command output" % (vm_name, vcpu, cpu_list))

        if pid is None:
            return
        # Get the vcpus pid
        vcpus_pid = vm.get_vcpus_pid()
        vcpu_pid = vcpus_pid[vcpu]
        # Get the actual cpu affinity value in the proc entry
        output = utils_test.libvirt.cpu_allowed_list_by_task(pid, vcpu_pid)
        actual_output_proc = utils_test.libvirt.cpus_string_to_affinity_list(
            output,
            host_cpu_count)

        if expected_output == actual_output_proc:
            logging.info("successfully pinned cpu: %s --> vcpu: %s"
                         " in respective proc entry", cpu_list, vcpu)
        else:
            raise error.TestFail("Command 'virsh vcpupin %s %s %s'not "
                                 "succeeded cpu pinning details not "
                                 "updated properly in /proc/%s/task/%s/status"
                                 % (vm_name, vcpu, cpu_list, pid, vcpu_pid))

    def run_and_check_vcpupin(vm_name, vcpu, cpu_list, options, pid):
        """
        Run the vcpupin command and then check the result.
        """
        # Execute virsh vcpupin command.
        cmdResult = virsh.vcpupin(vm_name, vcpu, cpu_list, options)
        if cmdResult.exit_status:
            if not status_error:
                # Command fail and it is in positive case.
                raise error.TestFail(cmdResult)
            else:
                # Command fail and it is in negative case.
                return
        else:
            if status_error:
                # Command success and it is in negative case.
                raise error.TestFail(cmdResult)
            else:
                # Command success and it is in positive case.
                # "--config" will take effect after VM destroyed.
                if options == "--config":
                    virsh.destroy(vm_name)
                    pid = None
                # Check the result of vcpupin command.
                check_vcpupin(vm_name, vcpu, cpu_list, pid)

    if not virsh.has_help_command('vcpucount'):
        raise error.TestNAError("This version of libvirt doesn't"
                                " support this test")
    # Get the vm name, pid of vm and check for alive
    vm_name = params.get("main_vm", "virt-tests-vm1")
    vm = env.get_vm(vm_name)
    pid = vm.get_pid()
    # Get the variables for vcpupin command.
    args = params.get("vcpupin_args", "dom_name")
    if args == "dom_name":
        args = vm_name
    options = params.get("vcpupin_options", "--current")
    cpu_list = params.get("vcpupin_cpu_list", "x")
    # Get status of this case.
    status_error = ("yes" == params.get("status_error", "no"))

    # Backup for recovery.
    vmxml_backup = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)

    try:
        # Run cases when guest is shutoff.
        if vm.is_dead() and (params.get("start_vm") == "no"):
            run_and_check_vcpupin(args, 0, 0, "", 0)
            return
        # Get the host cpu count
        host_cpu_count = utils.count_cpus()
        if (int(host_cpu_count) < 2) and (not cpu_list == "x"):
            raise error.TestNAError("We need more cpus on host in this case "
                                    "for the cpu_list=%s. But current number "
                                    "of cpu on host is %s."
                                    % (cpu_list, host_cpu_count))

        # Get the guest vcpu count
        guest_vcpu_count = virsh.vcpucount(vm_name,
                                           "--live --active").stdout.strip()
        # Run test case
        for vcpu in range(int(guest_vcpu_count)):
            if cpu_list == "x":
                for cpu in range(int(host_cpu_count)):
                    run_and_check_vcpupin(args, vcpu, str(cpu), options, pid)
            else:
                cpu_max = int(host_cpu_count) - 1
                if cpu_list == "x-y":
                    cpus = "0-%s" % cpu_max
                elif cpu_list == "x,y":
                    cpus = "0,%s" % cpu_max
                elif cpu_list == "x-y,^z":
                    cpus = "0-%s,^%s" % (cpu_max, cpu_max)
                elif cpu_list == "r":
                    cpus = "r"
                elif cpu_list == "-1":
                    cpus = "-1"
                elif cpu_list == "out_of_max":
                    cpus = str(cpu_max + 1)
                else:
                    raise error.TestNAError("Cpu_list=%s is not recognized."
                                            % cpu_list)
                run_and_check_vcpupin(args, vcpu, cpus, options, pid)
    finally:
        # Recover xml of vm.
        vmxml_backup.sync()
