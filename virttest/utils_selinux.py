"""
selinux test utility functions.
"""

import logging
import re
from autotest.client import utils


class SelinuxError(Exception):

    """
    Error selinux utility functions.
    """
    pass


class SeCmdError(SelinuxError):

    """
    Error in executing cmd.
    """

    def __init__(self, cmd, detail):
        SelinuxError.__init__(self)
        self.cmd = cmd
        self.detail = detail

    def __str__(self):
        return str("Execute command %s failed.\n"
                   "Detail: %s .\n" % (self.cmd, self.detail))


STATUS_LIST = ['enforcing', 'permissive', 'disabled']


def get_status():
    """
    Get the status of selinux.

    :return: string of status in STATUS_LIST.
    @raise SeCmdError: if execute 'getenforce' failed.
    @raise SelinuxError: if 'getenforce' command exit 0,
                    but the output is not expected.
    """
    cmd = 'getenforce'
    result = utils.run(cmd, ignore_status=True)
    if result.exit_status:
        raise SeCmdError(cmd, result.stderr)

    for status in STATUS_LIST:
        if result.stdout.lower().count(status):
            return status
        else:
            continue

    raise SelinuxError("result of 'getenforce' (%s)is not expected."
                       % result.stdout)


def set_status(status):
    """
    Set status of selinux.

    :param status: status want to set selinux.
    @raise SelinuxError: status is not supported.
    @raise SelinuxError: need to reboot host.
    @raise SeCmdError: execute setenforce failed.
    @raise SelinuxError: cmd setenforce exit normally,
                but status of selinux is not set to expected.
    """
    if not status in STATUS_LIST:
        raise SelinuxError("Status %s is not accepted." % status)

    current_status = get_status()
    if status == current_status:
        return
    else:
        if current_status == "disabled" or status == "disabled":
            raise SelinuxError("Please modify /etc/selinux/config and "
                               "reboot host to set selinux to %s." % status)
        else:
            cmd = "setenforce %s" % status
            result = utils.run(cmd, ignore_status=True)
            if result.exit_status:
                raise SeCmdError(cmd, result.stderr)
            else:
                current_status = get_status()
                if not status == current_status:
                    raise SelinuxError("Status of selinux is set to %s,"
                                       "but not expected %s. "
                                       % (current_status, status))
                else:
                    pass

    logging.debug("Set status of selinux to %s success.", status)


def is_disabled():
    """
    Return True if the selinux is disabled.
    """
    status = get_status()
    if status == "disabled":
        return True
    else:
        return False


def is_not_disabled():
    """
    Return True if the selinux is not disabled.
    """
    return not is_disabled()


def get_context_from_str(string):
    """
    Get the context in a string.

    @raise SelinuxError: if there is no context in string.
    """
    context_pattern = r"[a-z,_]*_u:[a-z,_]*_r:[a-z,_]*_t:[s,\-,0-9,:[c,\,,0-9]*]*"
    if re.search(context_pattern, string):
        context_list = re.findall(context_pattern, string)
        return context_list[0]

    raise SelinuxError("There is no context in %s." % string)


def get_context_of_file(filename):
    """
    Get the context of file.

    @raise SeCmdError: if execute 'getfattr' failed.
    """
    cmd = "getfattr --name security.selinux %s" % filename
    result = utils.run(cmd, ignore_status=True)
    if result.exit_status:
        raise SeCmdError(cmd, result.stderr)

    output = result.stdout
    return get_context_from_str(output)


def set_context_of_file(filename, context):
    """
    Set context of file.

    @raise SeCmdError: if failed to execute chcon.
    @raise SelinuxError: if command chcon execute
                        normally, but the context of
                        file is not setted to context.
    """
    context = context.strip()
    cmd = ("setfattr --name security.selinux --value \"%s\" %s"
           % (context, filename))
    result = utils.run(cmd, ignore_status=True)
    if result.exit_status:
        raise SeCmdError(cmd, result.stderr)

    context_result = get_context_of_file(filename)
    if not context == context_result:
        raise SelinuxError("Context of %s after chcon is %s, "
                           "but not expected %s."
                           % (filename, context_result, context))

    logging.debug("Set context of %s success.", filename)


def get_context_of_process(pid):
    """
    Get context of process.
    """
    attr_filepath = "/proc/%s/attr/current" % pid

    attr_file = open(attr_filepath)

    output = attr_file.read()
    return get_context_from_str(output)
