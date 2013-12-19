import re
from autotest.client.shared import error
from autotest.client import utils
from virttest import virsh, utils_libvirtd


def run(test, params, env):
    """
    Test the command virsh nodecpustats

    (1) Call the virsh nodecpustats command for all cpu host cpus
        separately
    (2) Get the output
    (3) Check the against /proc/stat output(o) for respective cpu
        user: o[0] + o[1]
        system: o[2] + o[5] + o[6]
        idle: o[3]
        iowait: o[4]
    (4) Call the virsh nodecpustats command with an unexpected option
    (5) Call the virsh nodecpustats command with libvirtd service stop
    """

    def virsh_check_nodecpustats_percpu(actual_stats):
        """
        Check the acual nodecpustats output value
        total time <= system uptime
        """

        # Normalise to seconds from nano seconds
        total = float((actual_stats['system'] + actual_stats['user'] +
                       actual_stats['idle'] + actual_stats['iowait']) / (10 ** 9))
        uptime = float(utils.get_uptime())
        if not total <= uptime:
            raise error.TestFail("Commands 'virsh nodecpustats' not succeeded"
                                 " as total time: %f is more"
                                 " than uptime: %f" % (total, uptime))
        return True

    def virsh_check_nodecpustats(actual_stats, cpu_count):
        """
        Check the acual nodecpustats output value
        total time <= system uptime
        """

        # Normalise to seconds from nano seconds and get for one cpu
        total = float(((actual_stats['system'] + actual_stats['user'] +
                        actual_stats['idle'] + actual_stats['iowait']) / (10 ** 9)) / (
            cpu_count))
        uptime = float(utils.get_uptime())
        if not total <= uptime:
            raise error.TestFail("Commands 'virsh nodecpustats' not succeeded"
                                 " as total time: %f is more"
                                 " than uptime: %f" % (total, uptime))
        return True

    def virsh_check_nodecpustats_percentage(actual_per):
        """
        Check the actual nodecpustats percentage adds up to 100%
        """

        total = int(round(actual_per['user'] + actual_per['system'] +
                    actual_per['idle'] + actual_per['iowait']))

        if not total == 100:
            raise error.TestFail("Commands 'virsh nodecpustats' not succeeded"
                                 " as the total percentage value: %d"
                                 " is not equal 100" % total)

    def parse_output(output):
        """
        To get the output parsed into a dictionary
        :param virsh command output

        :return: dict of user,system,idle,iowait times
        """

        # From the beginning of a line, group 1 is one or more word-characters,
        # followed by zero or more whitespace characters and a ':',
        # then one or more whitespace characters,
        # followed by group 2, which is one or more digit characters,
        # e.g as below
        # user:                  6163690000000
        #
        regex_obj = re.compile(r"^(\w+)\s*:\s+(\d+)")
        actual = {}

        for line in output.stdout.split('\n'):
            match_obj = regex_obj.search(line)
            # Due to the extra space in the list
            if match_obj is not None:
                name = match_obj.group(1)
                value = match_obj.group(2)
                actual[name] = int(value)
        return actual

    def parse_percentage_output(output):
        """
        To get the output parsed into a dictionary
        :param virsh command output

        :return: dict of user,system,idle,iowait times
        """

        # From the beginning of a line, group 1 is one or more word-characters,
        # followed by zero or more whitespace characters and a ':',
        # then one or more whitespace characters,
        # followed by group 2, which is one or more digit characters,
        # e.g as below
        # user:             1.5%
        #
        regex_obj = re.compile(r"^(\w+)\s*:\s+(\d+.\d+)")
        actual_percentage = {}

        for line in output.stdout.split('\n'):
            match_obj = regex_obj.search(line)
            # Due to the extra space in the list
            if match_obj is not None:
                name = match_obj.group(1)
                value = match_obj.group(2)
                actual_percentage[name] = float(value)
        return actual_percentage

    # Initialize the variables
    itr = int(params.get("inner_test_iterations"))
    option = params.get("virsh_cpunodestats_options")
    status_error = params.get("status_error")
    libvirtd = params.get("libvirtd", "on")

    # Prepare libvirtd service
    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    # Get the host cpu count
    host_cpu_count = utils.count_cpus()

    # Run test case for 5 iterations default can be changed in subtests.cfg
    # file
    for i in range(itr):

        if status_error == "yes":
            output = virsh.nodecpustats(ignore_status=True, option=option)
            status = output.exit_status

            if status == 0:
                if libvirtd == "off":
                    utils_libvirtd.libvirtd_start()
                    raise error.TestFail("Command 'virsh nodecpustats' "
                                         "succeeded with libvirtd service "
                                         "stopped, incorrect")
                else:
                    raise error.TestFail("Command 'virsh nodecpustats %s' "
                                         "succeeded (incorrect command)" % option)

        elif status_error == "no":
            # Run the testcase for each cpu to get the cpu stats
            for cpu in range(host_cpu_count):
                option = "--cpu %d" % cpu
                output = virsh.nodecpustats(ignore_status=True, option=option)
                status = output.exit_status

                if status == 0:
                    actual_value = parse_output(output)
                    virsh_check_nodecpustats_percpu(actual_value)
                else:
                    raise error.TestFail("Command 'virsh nodecpustats %s'"
                                         "not succeeded" % option)

            # Run the test case for each cpu to get the cpu stats in percentage
            for cpu in range(host_cpu_count):
                option = "--cpu %d --percent" % cpu
                output = virsh.nodecpustats(ignore_status=True, option=option)
                status = output.exit_status

                if status == 0:
                    actual_value = parse_percentage_output(output)
                    virsh_check_nodecpustats_percentage(actual_value)
                else:
                    raise error.TestFail("Command 'virsh nodecpustats %s'"
                                         " not succeeded" % option)

            option = ''
            # Run the test case for total cpus to get the cpus stats
            output = virsh.nodecpustats(ignore_status=True, option=option)
            status = output.exit_status

            if status == 0:
                actual_value = parse_output(output)
                virsh_check_nodecpustats(actual_value, host_cpu_count)
            else:
                raise error.TestFail("Command 'virsh nodecpustats %s'"
                                     " not succeeded" % option)

            # Run the test case for the total cpus to get the stats in
            # percentage
            option = "--percent"
            output = virsh.nodecpustats(ignore_status=True, option=option)
            status = output.exit_status

            if status == 0:
                actual_value = parse_percentage_output(output)
                virsh_check_nodecpustats_percentage(actual_value)
            else:
                raise error.TestFail("Command 'virsh nodecpustats %s'"
                                     " not succeeded" % option)

    # Recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()
