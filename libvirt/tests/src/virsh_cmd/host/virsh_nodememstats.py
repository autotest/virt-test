import logging
import re
from autotest.client.shared import error
from virttest import virsh, utils_libvirtd
from virttest import utils_test


try:
    from virttest.staging import utils_memory
except ImportError:
    from autotest.client.shared import utils_memory


def run(test, params, env):
    """
    Test the command virsh nodememstats

    (1) Call the virsh nodememstats command
    (2) Get the output
    (3) Check the against /proc/meminfo output
    (4) Call the virsh nodememstats command with an unexpected option
    (5) Call the virsh nodememstats command with libvirtd service stop
    """

    # Initialize the variables
    expected = {}
    actual = {}
    deltas = []
    name_stats = ['total', 'free', 'buffers', 'cached']
    itr = int(params.get("itr"))

    def virsh_check_nodememtats(actual_stats, expected_stats, delta):
        """
        Check the nodememstats output value with /proc/meminfo value
        """

        delta_stats = {}
        for name in name_stats:
            delta_stats[name] = abs(actual_stats[name] - expected_stats[name])
            if 'total' in name:
                if not delta_stats[name] == 0:
                    raise error.TestFail("Command 'virsh nodememstats' not"
                                         " succeeded as the value for %s is "
                                         "deviated by %d\nThe total memory "
                                         "value is deviating-check"
                                         % (name, delta_stats[name]))
            else:
                if delta_stats[name] > delta:
                    raise error.TestFail("Command 'virsh nodememstats' not "
                                         "succeeded as the value for %s"
                                         " is deviated by %d"
                                         % (name, delta_stats[name]))
        return delta_stats

    # Prepare libvirtd service
    check_libvirtd = params.has_key("libvirtd")
    if check_libvirtd:
        libvirtd = params.get("libvirtd")
        if libvirtd == "off":
            utils_libvirtd.libvirtd_stop()

    # Get the option for the test case
    option = params.get("virsh_nodememstats_options")
    if option == "max":
        cell_dict = utils_test.libvirt.get_all_cells()
        option = len(cell_dict.keys())

    # Run test case for 10 iterations
    # (default can be changed in subtests.cfg file)
    # and print the final statistics
    for i in range(itr):
        output = virsh.nodememstats(option)

        # Get the status of the virsh command executed
        status = output.exit_status

        # Get status_error option for the test case
        status_error = params.get("status_error")
        if status_error == "yes":
            if status == 0:
                if libvirtd == "off":
                    utils_libvirtd.libvirtd_start()
                    raise error.TestFail("Command 'virsh nodememstats' "
                                         "succeeded with libvirtd service"
                                         " stopped, incorrect")
                else:
                    raise error.TestFail("Command 'virsh nodememstats %s' "
                                         "succeeded (incorrect command)"
                                         % option)

        elif status_error == "no":
            if status == 0:
                if option:
                    return
                # From the beginning of a line, group 1 is one or
                # more word-characters, followed by zero or more
                # whitespace characters and a ':', then one or
                # more whitespace characters, followed by group 2,
                # which is one or more digit characters,
                # then one or more whitespace characters followed by
                # a literal 'kB' or 'KiB' sequence, e.g as below
                # total  :              3809340 kB
                # total  :              3809340 KiB
                # Normalise the value to MBs
                regex_obj = re.compile(r"^(\w+)\s*:\s+(\d+)\s\w+")
                expected = {}

                for line in output.stdout.split('\n'):
                    match_obj = regex_obj.search(line)
                    # Due to the extra space in the list
                    if match_obj is not None:
                        name = match_obj.group(1)
                        value = match_obj.group(2)
                        expected[name] = int(value) / 1024

                # Get the actual value from /proc/meminfo and normalise to MBs
                actual['total'] = int(utils_memory.memtotal()) / 1024
                actual['free'] = int(utils_memory.freememtotal()) / 1024
                actual['buffers'] = int(
                    utils_memory.read_from_meminfo('Buffers')) / 1024
                actual['cached'] = int(
                    utils_memory.read_from_meminfo('Cached')) / 1024

                # Currently the delta value is kept at 200 MB this can be
                # tuned based on the accuracy
                # Check subtests.cfg for more details
                delta = int(params.get("delta"))
                output = virsh_check_nodememtats(actual, expected, delta)
                deltas.append(output)

            else:
                raise error.TestFail("Command virsh nodememstats %s not "
                                     "succeeded:\n%s" % (option, status))

    # Recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # Print the deviated values for all iterations
    if status_error == "no":
        logging.debug("The following is the deviations from "
                      "the actual(/proc/meminfo) and expected"
                      " value(output of virsh nodememstats)")

        for i in range(itr):
            logging.debug("iteration %d:", i)
            for index, name in enumerate(name_stats):
                logging.debug("%19s : %d", name, deltas[i][name])
