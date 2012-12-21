"""
libguestfs tools test utility functions.
"""

import logging

from autotest.client import os_dep, utils
from autotest.client.shared import error
import propcan


class LibguestfsCmdError(Exception):
    """
    Error of libguestfs-tool command.
    """

    def __init__(self, details=''):
        self.details = details
        Exception.__init__(self)


    def __str__(self):
        return str(self.details)


def lgf_cmd_check(cmd):
    """
    To check whether the cmd is supported on this host.

    @param cmd: the cmd to use a libguest tool.
    @return: None if the cmd is not exist, otherwise return its path.
    """
    libguestfs_cmds = ['libguestfs_test_tool', 'guestfish', 'guestmount',
                       'virt-alignment-scan', 'virt-cat', 'virt-copy-in',
                       'virt-copy-out', 'virt-df', 'virt-edit',
                       'virt-filesystems', 'virt-format', 'virt-inspector',
                       'virt-list-filesystems', 'virt-list-partitions',
                       'virt-ls', 'virt-make-fs', 'virt-rescue',
                       'virt-resize', 'virt-sparsify', 'virt-sysprep',
                       'virt-tar', 'virt-tar-in', 'virt-tar-out',
                       'virt-win-reg']

    if not (cmd in libguestfs_cmds):
        raise LibguestfsCmdError("Command %s is not supported by libguestfs yet." % cmd)

    try:
        return os_dep.command(cmd)
    except ValueError:
        logging.warning("You have not installed %s on this host.", cmd)
        return None


def lgf_command(cmd, **dargs):
    """
    Interface of libguestfs tools' commands.

    @param cmd: Command line to execute.
    @param dargs: standardized command keywords.
    @return: CmdResult object.
    @raise: LibguestfsCmdError if non-zero exit status
            and ignore_status=False
    """
    ignore_status = dargs.get('ignore_status', True)
    debug = dargs.get('debug', False)
    uri = dargs.get('uri', None)
    timeout = dargs.get('timeout', 60)

    if debug:
        logging.debug("Running command %s in debug mode.", cmd)

    # Raise exception if ignore_status == False
    try:
        ret = utils.run(cmd, ignore_status=ignore_status, 
                        verbose=debug, timeout=timeout)
    except error.CmdError, detail:
        raise LibguestfsCmdError(detail)

    if debug:
        logging.debug("status: %s", ret.exit_status)
        logging.debug("stdout: %s", ret.stdout.strip())
        logging.debug("stderr: %s", ret.stderr.strip())

    # Return CmdResult instance when ignore_status is True
    return ret


class LibguestfsBase(propcan.PropCanBase):
    """
    Base class of libguestfs tools.
    """

    __slots__ = ('ignore_status', 'debug', 'timeout')

    def __init__(self, *args, **dargs):
        init_dict = dict(*args, **dargs)
        init_dict['ignore_status'] = init_dict.get('ignore_status', True)
        init_dict['debug'] = init_dict.get('debug', False)
        init_dict['timeout'] = init_dict.get('timeout', 60)
        super(LibguestfsBase, self).__init__(init_dict)


    def set_ignore_status(self, ignore_status):
        """
        Enforce setting ignore_status as a boolean.
        """
        if bool(ignore_status):
            self.dict_set('ignore_status', True)
        else:
            self.dict_set('ignore_status', False)


    def set_debug(self, debug):
        """
        Accessor method for 'debug' property that logs message on change
        """
        if not self.INITIALIZED:
            self.dict_set('debug', debug)
        else:
            current_setting = self.dict_get('debug')
            desired_setting = bool(debug)
            if not current_setting and desired_setting:
                self.dict_set('debug', True)
                logging.debug("Libguestfs debugging enabled")
            # current and desired could both be True
            if current_setting and not desired_setting:
                self.dict_set('debug', False)
                logging.debug("Libguestfs debugging disabled")


def libguest_test_tool_cmd(qemuarg=None, qemudirarg=None,
                           timeoutarg=None, **dargs):
    """
    Execute libguest-test-tool command.

    @param qemuarg: the qemu option
    @param qemudirarg: the qemudir option
    @param timeoutarg: the timeout option
    @return: a CmdResult object
    @raise: raise LibguestfsCmdError
    """
    cmd = "libguest-test-tool"
    if qemuarg is not None:
        cmd += " --qemu '%s'" % qemuarg
    if qemudirarg is not None:
        cmd += " --qemudir '%s'" % qemudirarg
    if timeoutarg is not None:
        cmd += " --timeout %s" % timeoutarg

    # Allow to raise LibguestfsCmdError if ignore_status is False.
    return lgf_command(cmd, **dargs) 


def virt_edit_cmd(disk_or_domain, file_path, options=None,
                  extra=None, expr=None, **dargs):
    """
    Execute virt-edit command to check whether it is ok.

    Since virt-edit will need uses' interact, maintain and return
    a session if there is no raise after command has been executed.

    @param disk_or_domain: a img path or a domain name.
    @param file_path: the file need to be edited in img file.
    @param options: the options of virt-edit.
    @param extra: additional suffix of command.
    @return: a session of executing virt-edit command.
    """
    # disk_or_domain and file_path are necessary parameters.
    cmd = "virt-edit '%s' '%s'" % (disk_or_domain, file_path)
    if options is not None:
        cmd += " %s" % options
    if extra is not None:
        cmd += " %s" % extra
    if expr is not None:
        cmd += " -e '%s'" % expr

    return lgf_command(cmd, **dargs)
