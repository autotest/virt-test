import logging
from autotest.client.shared import error
from virttest import virsh


def run(test, params, env):
    """
    Test command: virsh help.

    1.Get all parameters from configuration.
    2.Perform virsh help operation.
    3.Check help information valid or not.
    4.Check result.
    """
    extra = params.get("help_extra", "")
    cmd = params.get("help_command", "")
    test_target = params.get("help_target", "")
    status_error = params.get("status_error", "no")

    def help_check(test_target):
        """
        Check all virsh commands or groups's help information

        :param test_target: Test target,all virsh or all virsh groups
        :return: True if check successfully
        """
        help_list = []
        if test_target == "all_command":
            help_list = virsh.help_command_only("", False,
                                                ignore_status=True)
        elif test_target == "all_group":
            help_list = virsh.help_command_group("", False,
                                                 ignore_status=True)
        if len(help_list) == 0:
            raise error.TestError("Cannot get any virsh command/group!")
        fail_list = []
        # If any command or group's check failed, the test failed
        check_result = True
        for virsh_cmd_group in help_list:
            logging.info("Test command or group: '%s'", virsh_cmd_group)
            result = virsh.help(virsh_cmd_group, ignore_status=True)
            status = result.exit_status
            output = result.stdout.strip()
            if status != 0:
                fail_list.append(virsh_cmd_group)
                # No need to check output
                continue
            if not output:
                fail_list.append(virsh_cmd_group)
        # List all failed commands or groups
        if len(fail_list) > 0:
            check_result = False
            logging.info("These commands or groups' check failed!!!")
            for fail_cmd in fail_list:
                logging.info("%s", fail_cmd)
        return check_result

    if test_target == "":
        cmd = "%s %s" % (cmd, extra)
        result = virsh.help(cmd, ignore_status=True)
    else:
        check_result = help_check(test_target)

    if test_target == "":
        status = result.exit_status
        output = result.stdout.strip()

    # Check status_error
    if status_error == "yes":
        if test_target == "":
            if status == 0:
                raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if test_target == "":
            if status != 0:
                raise error.TestFail("Run failed with right command")
            if output == "":
                raise error.TestFail("Cannot see help information")
        else:
            if not check_result:
                raise error.TestFail(
                    "virsh help command or groups test failed")
