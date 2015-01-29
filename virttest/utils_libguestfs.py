"""
libguestfs tools test utility functions.
"""

import logging
import signal
import os
import re

from autotest.client import os_dep, utils
from autotest.client.shared import error
import aexpect
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

    :param cmd: the cmd to use a libguest tool.
    :return: None if the cmd is not exist, otherwise return its path.
    """
    libguestfs_cmds = ['libguestfs-test-tool', 'guestfish', 'guestmount',
                       'virt-alignment-scan', 'virt-cat', 'virt-copy-in',
                       'virt-copy-out', 'virt-df', 'virt-edit',
                       'virt-filesystems', 'virt-format', 'virt-inspector',
                       'virt-list-filesystems', 'virt-list-partitions',
                       'virt-ls', 'virt-make-fs', 'virt-rescue',
                       'virt-resize', 'virt-sparsify', 'virt-sysprep',
                       'virt-tar', 'virt-tar-in', 'virt-tar-out',
                       'virt-win-reg', 'virt-inspector2']

    if cmd not in libguestfs_cmds:
        raise LibguestfsCmdError(
            "Command %s is not supported by libguestfs yet." % cmd)

    try:
        return os_dep.command(cmd)
    except ValueError:
        logging.warning("You have not installed %s on this host.", cmd)
        return None


def lgf_command(cmd, ignore_status=True, debug=False, timeout=60):
    """
    Interface of libguestfs tools' commands.

    :param cmd: Command line to execute.
    :return: CmdResult object.
    :raise: LibguestfsCmdError if non-zero exit status
            and ignore_status=False
    """
    if debug:
        logging.debug("Running command %s in debug mode.", cmd)

    # Raise exception if ignore_status is False
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

    __slots__ = ['ignore_status', 'debug', 'timeout', 'uri', 'lgf_exec']

    def __init__(self, lgf_exec="/bin/true", ignore_status=True,
                 debug=False, timeout=60, uri=None):
        init_dict = {}
        init_dict['ignore_status'] = ignore_status
        init_dict['debug'] = debug
        init_dict['timeout'] = timeout
        init_dict['uri'] = uri
        init_dict['lgf_exec'] = lgf_exec
        super(LibguestfsBase, self).__init__(init_dict)

    def set_ignore_status(self, ignore_status):
        """
        Enforce setting ignore_status as a boolean.
        """
        if bool(ignore_status):
            self.__dict_set__('ignore_status', True)
        else:
            self.__dict_set__('ignore_status', False)

    def set_debug(self, debug):
        """
        Accessor method for 'debug' property that logs message on change
        """
        if not self.INITIALIZED:
            self.__dict_set__('debug', debug)
        else:
            current_setting = self.__dict_get__('debug')
            desired_setting = bool(debug)
            if not current_setting and desired_setting:
                self.__dict_set__('debug', True)
                logging.debug("Libguestfs debugging enabled")
            # current and desired could both be True
            if current_setting and not desired_setting:
                self.__dict_set__('debug', False)
                logging.debug("Libguestfs debugging disabled")

    def set_timeout(self, timeout):
        """
        Accessor method for 'timeout' property, timeout should be digit
        """
        if type(timeout) is int:
            self.__dict_set__('timeout', timeout)
        else:
            try:
                timeout = int(str(timeout))
                self.__dict_set__('timeout', timeout)
            except ValueError:
                logging.debug("Set timeout failed.")

    def get_uri(self):
        """
        Accessor method for 'uri' property that must exist
        """
        # self.get() would call get_uri() recursivly
        try:
            return self.__dict_get__('uri')
        except KeyError:
            return None


# There are two ways to call guestfish:
# 1.Guestfish classies provided below(shell session)
# 2.guestfs module provided in system libguestfs package

class Guestfish(LibguestfsBase):

    """
    Execute guestfish, using a new guestfish shell each time.
    """

    __slots__ = []

    def __init__(self, disk_img=None, ro_mode=False,
                 libvirt_domain=None, inspector=False,
                 uri=None, mount_options=None, run_mode="interactive"):
        """
        Initialize guestfish command with options.

        :param disk_img: if it is not None, use option '-a disk'.
        :param ro_mode: only for disk_img. add option '--ro' if it is True.
        :param libvirt_domain: if it is not None, use option '-d domain'.
        :param inspector: guestfish mounts vm's disks automatically
        :param uri: guestfish's connect uri
        :param mount_options: Mount the named partition or logical volume
                               on the given mountpoint.
        """
        guestfs_exec = "guestfish"
        if lgf_cmd_check(guestfs_exec) is None:
            raise LibguestfsCmdError

        if run_mode not in ['remote', 'interactive']:
            raise AssertionError("run_mode should be remote or interactive")

        # unset GUESTFISH_XXX environment parameters
        # to avoid color of guestfish shell session for testing
        color_envs = ["GUESTFISH_PS1", "GUESTFISH_OUTPUT",
                      "GUESTFISH_RESTORE", "GUESTFISH_INIT"]
        unset_cmd = ""
        for env in color_envs:
            unset_cmd += "unset %s;" % env
        if run_mode == "interactive" and unset_cmd:
            guestfs_exec = unset_cmd + " " + guestfs_exec

        if run_mode == "remote":
            guestfs_exec += " --listen"
        else:
            if uri:
                guestfs_exec += " -c '%s'" % uri
            if disk_img:
                guestfs_exec += " -a '%s'" % disk_img
            if libvirt_domain:
                guestfs_exec += " -d '%s'" % libvirt_domain
            if ro_mode:
                guestfs_exec += " --ro"
            if inspector:
                guestfs_exec += " -i"
            if mount_options is not None:
                guestfs_exec += " --mount %s" % mount_options

        super(Guestfish, self).__init__(guestfs_exec)

    def complete_cmd(self, command):
        """
        Execute built-in command in a complete guestfish command
        (Not a guestfish session).
        command: guestfish [--options] [commands]
        """
        guestfs_exec = self.__dict_get__('lgf_exec')
        ignore_status = self.__dict_get__('ignore_status')
        debug = self.__dict_get__('debug')
        timeout = self.__dict_get__('timeout')
        if command:
            guestfs_exec += " %s" % command
            return lgf_command(guestfs_exec, ignore_status, debug, timeout)
        else:
            raise LibguestfsCmdError("No built-in command was passed.")


class GuestfishSession(aexpect.ShellSession):

    """
    A shell session of guestfish.
    """

    # Check output against list of known error-status strings
    ERROR_REGEX_LIST = ['libguestfs: error:\s*']

    def __init__(self, guestfs_exec=None, a_id=None, prompt=r"><fs>\s*"):
        """
        Initialize guestfish session server, or client if id set.

        :param guestfs_cmd: path to guestfish executable
        :param id: ID of an already running server, if accessing a running
                server, or None if starting a new one.
        :param prompt: Regular expression describing the shell's prompt line.
        """
        # aexpect tries to auto close session because no clients connected yet
        super(GuestfishSession, self).__init__(guestfs_exec, a_id,
                                               prompt=prompt,
                                               auto_close=False)

    def cmd_status_output(self, cmd, timeout=60, internal_timeout=None,
                          print_func=None):
        """
        Send a guestfish command and return its exit status and output.

        :param cmd: guestfish command to send
                    (must not contain newline characters)
        :param timeout: The duration (in seconds) to wait for the prompt to
                return
        :param internal_timeout: The timeout to pass to read_nonblocking
        :param print_func: A function to be used to print the data being read
                (should take a string parameter)
        :return: A tuple (status, output) where status is the exit status and
                output is the output of cmd
        :raise ShellTimeoutError: Raised if timeout expires
        :raise ShellProcessTerminatedError: Raised if the shell process
                terminates while waiting for output
        :raise ShellStatusError: Raised if the exit status cannot be obtained
        :raise ShellError: Raised if an unknown error occurs
        """
        out = self.cmd_output(cmd, timeout, internal_timeout, print_func)
        for line in out.splitlines():
            if self.match_patterns(line, self.ERROR_REGEX_LIST) is not None:
                return 1, out
        return 0, out

    def cmd_result(self, cmd, ignore_status=False):
        """Mimic utils.run()"""
        exit_status, stdout = self.cmd_status_output(cmd)
        stderr = ''  # no way to retrieve this separately
        result = utils.CmdResult(cmd, stdout, stderr, exit_status)
        if not ignore_status and exit_status:
            raise error.CmdError(cmd, result,
                                 "Guestfish Command returned non-zero exit status")
        return result


class GuestfishRemote(object):

    """
    Remote control of guestfish.
    """

    # Check output against list of known error-status strings
    ERROR_REGEX_LIST = ['libguestfs: error:\s*']

    def __init__(self, guestfs_exec=None, a_id=None):
        """
        Initialize guestfish session server, or client if id set.

        :param guestfs_cmd: path to guestfish executable
        :param a_id: guestfish remote id
        """
        if a_id is None:
            try:
                ret = utils.run(guestfs_exec, ignore_status=False,
                                verbose=True, timeout=60)
            except error.CmdError, detail:
                raise LibguestfsCmdError(detail)
            self.a_id = re.search("\d+", ret.stdout.strip()).group()
        else:
            self.a_id = a_id

    def get_id(self):
        return self.a_id

    def cmd_status_output(self, cmd, ignore_status=None, verbose=None, timeout=60):
        """
        Send a guestfish command and return its exit status and output.

        :param cmd: guestfish command to send(must not contain newline characters)
        :param timeout: The duration (in seconds) to wait for the prompt to return
        :return: A tuple (status, output) where status is the exit status
                 and output is the output of cmd
        :raise LibguestfsCmdError: Raised if commands execute failed
        """
        guestfs_exec = "guestfish --remote=%s " % self.a_id
        cmd = guestfs_exec + cmd
        try:
            ret = utils.run(cmd, ignore_status=ignore_status,
                            verbose=verbose, timeout=timeout)
        except error.CmdError, detail:
            raise LibguestfsCmdError(detail)

        for line in self.ERROR_REGEX_LIST:
            if re.search(line, ret.stdout.strip()):
                raise LibguestfsCmdError(detail)

        logging.debug("command: %s", cmd)
        logging.debug("stdout: %s", ret.stdout.strip())

        return 0, ret.stdout.strip()

    def cmd(self, cmd, ignore_status=False):
        """Mimic utils.run()"""
        exit_status, stdout = self.cmd_status_output(cmd)
        stderr = ''  # no way to retrieve this separately
        result = utils.CmdResult(cmd, stdout, stderr, exit_status)
        if not ignore_status and exit_status:
            raise error.CmdError(cmd, result,
                                 "Guestfish Command returned non-zero exit status")
        return result

    def cmd_result(self, cmd, ignore_status=False):
        """Mimic utils.run()"""
        exit_status, stdout = self.cmd_status_output(cmd)
        stderr = ''  # no way to retrieve this separately
        result = utils.CmdResult(cmd, stdout, stderr, exit_status)
        if not ignore_status and exit_status:
            raise error.CmdError(cmd, result,
                                 "Guestfish Command returned non-zero exit status")
        return result


class GuestfishPersistent(Guestfish):

    """
    Execute operations using persistent guestfish session.
    """

    __slots__ = ['session_id', 'run_mode']

    # Help detect leftover sessions
    SESSION_COUNTER = 0

    def __init__(self, disk_img=None, ro_mode=False,
                 libvirt_domain=None, inspector=False,
                 uri=None, mount_options=None, run_mode="interactive"):
        super(GuestfishPersistent, self).__init__(disk_img, ro_mode,
                                                  libvirt_domain, inspector,
                                                  uri, mount_options, run_mode)
        self.__dict_set__('run_mode', run_mode)

        if self.get('session_id') is None:
            # set_uri does not call when INITIALIZED = False
            # and no session_id passed to super __init__
            self.new_session()

        # Check whether guestfish session is prepared.
        guestfs_session = self.open_session()
        if run_mode != "remote":
            status, output = guestfs_session.cmd_status_output('is-config', timeout=60)
            if status != 0:
                logging.debug("Persistent guestfish session is not responding.")
                raise aexpect.ShellStatusError(self.lgf_exec, 'is-config')

    def close_session(self):
        """
        If a persistent session exists, close it down.
        """
        try:
            run_mode = self.get('run_mode')
            existing = self.open_session()
            # except clause exits function
            # Try to end session with inner command 'quit'
            try:
                existing.cmd("quit")
            # It should jump to exception followed normally
            except aexpect.ShellProcessTerminatedError:
                self.__class__.SESSION_COUNTER -= 1
                self.__dict_del__('session_id')
                return  # guestfish session was closed normally
            # Close with 'quit' did not respond
            # So close with aexpect functions
            if run_mode != "remote":
                if existing.is_alive():
                    # try nicely first
                    existing.close()
                    if existing.is_alive():
                        # Be mean, incase it's hung
                        existing.close(sig=signal.SIGTERM)
                    # Keep count:
                    self.__class__.SESSION_COUNTER -= 1
                    self.__dict_del__('session_id')
        except LibguestfsCmdError:
            # Allow other exceptions to be raised
            pass  # session was closed already

    def new_session(self):
        """
        Open new session, closing any existing
        """
        # Accessors may call this method, avoid recursion
        # Must exist, can't be None
        guestfs_exec = self.__dict_get__('lgf_exec')
        self.close_session()
        # Always create new session
        run_mode = self.get('run_mode')
        if run_mode == "remote":
            new_session = GuestfishRemote(guestfs_exec)
        else:
            new_session = GuestfishSession(guestfs_exec)
        # Keep count
        self.__class__.SESSION_COUNTER += 1
        session_id = new_session.get_id()
        self.__dict_set__('session_id', session_id)

    def open_session(self):
        """
        Return session with session_id in this class.
        """
        try:
            session_id = self.__dict_get__('session_id')
            run_mode = self.get('run_mode')
            if session_id:
                try:
                    if run_mode == "remote":
                        return GuestfishRemote(a_id=session_id)
                    else:
                        return GuestfishSession(a_id=session_id)
                except aexpect.ShellStatusError:
                    # session was already closed
                    self.__dict_del__('session_id')
                    raise LibguestfsCmdError(
                        "Open session '%s' failed." % session_id)
        except KeyError:
            raise LibguestfsCmdError("No session id.")

    # Inner command for guestfish should be executed in a guestfish session
    def inner_cmd(self, command):
        """
        Execute inner command of guestfish in a pesistent session.

        :param command: inner command to be executed.
        """
        session = self.open_session()
        # Allow to raise error by default.
        ignore_status = self.__dict_get__('ignore_status')
        return session.cmd_result(command, ignore_status=ignore_status)


def libguest_test_tool_cmd(qemuarg=None, qemudirarg=None,
                           timeoutarg=None, ignore_status=True,
                           debug=False, timeout=60):
    """
    Execute libguest-test-tool command.

    :param qemuarg: the qemu option
    :param qemudirarg: the qemudir option
    :param timeoutarg: the timeout option
    :return: a CmdResult object
    :raise: raise LibguestfsCmdError
    """
    cmd = "libguestfs-test-tool"
    if qemuarg is not None:
        cmd += " --qemu '%s'" % qemuarg
    if qemudirarg is not None:
        cmd += " --qemudir '%s'" % qemudirarg
    if timeoutarg is not None:
        cmd += " --timeout %s" % timeoutarg

    # Allow to raise LibguestfsCmdError if ignore_status is False.
    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_edit_cmd(disk_or_domain, file_path, is_disk=False, disk_format=None,
                  options=None, extra=None, expr=None, connect_uri=None,
                  ignore_status=True, debug=False, timeout=60):
    """
    Execute virt-edit command to check whether it is ok.

    Since virt-edit will need uses' interact, maintain and return
    a session if there is no raise after command has been executed.

    :param disk_or_domain: a img path or a domain name.
    :param file_path: the file need to be edited in img file.
    :param is_disk: whether disk_or_domain is disk or domain
    :param disk_format: when is_disk is true, add a format if it is set.
    :param options: the options of virt-edit.
    :param extra: additional suffix of command.
    :return: a session of executing virt-edit command.
    """
    # disk_or_domain and file_path are necessary parameters.
    cmd = "virt-edit"
    if connect_uri is not None:
        cmd += " -c %s" % connect_uri
    if is_disk:
        # For latest version, --format must exist before -a
        if disk_format is not None:
            cmd += " --format=%s" % disk_format
        cmd += " -a %s" % disk_or_domain
    else:
        cmd += " -d %s" % disk_or_domain
    cmd += " %s" % file_path
    if options is not None:
        cmd += " %s" % options
    if extra is not None:
        cmd += " %s" % extra
    if expr is not None:
        cmd += " -e '%s'" % expr

    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_clone_cmd(original, newname=None, autoclone=False, **dargs):
    """
    Clone existing virtual machine images.

    :param original: Name of the original guest to be cloned.
    :param newname: Name of the new guest virtual machine instance.
    :param autoclone: Generate a new guest name, and paths for new storage.
    :param dargs: Standardized function API keywords. There are many
                  options not listed, they can be passed in dargs.
    """
    def storage_config(cmd, options):
        """Configure options for storage"""
        # files should be a list
        files = options.get("files", [])
        if len(files):
            for file in files:
                cmd += " --file '%s'" % file
        if options.get("nonsparse") is not None:
            cmd += " --nonsparse"
        return cmd

    def network_config(cmd, options):
        """Configure options for network"""
        mac = options.get("mac")
        if mac is not None:
            cmd += " --mac '%s'" % mac
        return cmd

    cmd = "virt-clone --original '%s'" % original
    if newname is not None:
        cmd += " --name '%s'" % newname
    if autoclone is True:
        cmd += " --auto-clone"
    # Many more options can be added if necessary.
    cmd = storage_config(cmd, dargs)
    cmd = network_config(cmd, dargs)

    ignore_status = dargs.get("ignore_status", True)
    debug = dargs.get("debug", False)
    timeout = dargs.get("timeout", 60)

    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_sparsify_cmd(indisk, outdisk, compress=False, convert=None,
                      format=None, ignore_status=True, debug=False,
                      timeout=60):
    """
    Make a virtual machine disk sparse.

    :param indisk: The source disk to be sparsified.
    :param outdisk: The destination disk.
    """
    cmd = "virt-sparsify"
    if compress is True:
        cmd += " --compress"
    if format is not None:
        cmd += " --format '%s'" % format
    cmd += " '%s'" % indisk

    if convert is not None:
        cmd += " --convert '%s'" % convert
    cmd += " '%s'" % outdisk
    # More options can be added if necessary.

    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_resize_cmd(indisk, outdisk, **dargs):
    """
    Resize a virtual machine disk.

    :param indisk: The source disk to be resized
    :param outdisk: The destination disk.
    """
    cmd = "virt-resize"
    ignore_status = dargs.get("ignore_status", True)
    debug = dargs.get("debug", False)
    timeout = dargs.get("timeout", 60)
    resize = dargs.get("resize")
    resized_size = dargs.get("resized_size", "0")
    expand = dargs.get("expand")
    shrink = dargs.get("shrink")
    ignore = dargs.get("ignore")
    delete = dargs.get("delete")
    if resize is not None:
        cmd += " --resize %s=%s" % (resize, resized_size)
    if expand is not None:
        cmd += " --expand %s" % expand
    if shrink is not None:
        cmd += " --shrink %s" % shrink
    if ignore is not None:
        cmd += " --ignore %s" % ignore
    if delete is not None:
        cmd += " --delete %s" % delete
    cmd += " %s %s" % (indisk, outdisk)

    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_list_partitions_cmd(disk_or_domain, long=False, total=False,
                             human_readable=False, ignore_status=True,
                             debug=False, timeout=60):
    """
    "virt-list-partitions" is a command line tool to list the partitions
    that are contained in a virtual machine or disk image.

    :param disk_or_domain: a disk or a domain to be mounted
    """
    cmd = "virt-list-partitions %s" % disk_or_domain
    if long is True:
        cmd += " --long"
    if total is True:
        cmd += " --total"
    if human_readable is True:
        cmd += " --human-readable"
    return lgf_command(cmd, ignore_status, debug, timeout)


def guestmount(disk_or_domain, mountpoint, inspector=False,
               readonly=False, **dargs):
    """
    guestmount - Mount a guest filesystem on the host using
                 FUSE and libguestfs.

    :param disk_or_domain: a disk or a domain to be mounted
           If you need to mount a disk, set is_disk to True in dargs
    :param mountpoint: the mountpoint of filesystems
    :param inspector: mount all filesystems automatically
    :param readonly: if mount filesystem with readonly option
    """
    def get_special_mountpoint(cmd, options):
        special_mountpoints = options.get("special_mountpoints", [])
        for mountpoint in special_mountpoints:
            cmd += " -m %s" % mountpoint
        return cmd

    cmd = "guestmount"
    ignore_status = dargs.get("ignore_status", True)
    debug = dargs.get("debug", False)
    timeout = dargs.get("timeout", 60)
    # If you need to mount a disk, set is_disk to True
    is_disk = dargs.get("is_disk", False)
    if is_disk is True:
        cmd += " -a %s" % disk_or_domain
    else:
        cmd += " -d %s" % disk_or_domain
    if inspector is True:
        cmd += " -i"
    if readonly is True:
        cmd += " --ro"
    cmd = get_special_mountpoint(cmd, dargs)
    cmd += " %s" % mountpoint
    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_filesystems(disk_or_domain, **dargs):
    """
    virt-filesystems - List filesystems, partitions, block devices,
    LVM in a virtual machine or disk image

    :param disk_or_domain: a disk or a domain to be mounted
           If you need to mount a disk, set is_disk to True in dargs
    """
    def get_display_type(cmd, options):
        all = options.get("all", False)
        filesystems = options.get("filesystems", False)
        extra = options.get("extra", False)
        partitions = options.get("partitions", False)
        block_devices = options.get("block_devices", False)
        logical_volumes = options.get("logical_volumes", False)
        volume_groups = options.get("volume_groups", False)
        physical_volumes = options.get("physical_volumes", False)
        long_format = options.get("long_format", False)
        human_readable = options.get("human_readable", False)
        if all is True:
            cmd += " --all"
        if filesystems is True:
            cmd += " --filesystems"
        if extra is True:
            cmd += " --extra"
        if partitions is True:
            cmd += " --partitions"
        if block_devices is True:
            cmd += " --block_devices"
        if logical_volumes is True:
            cmd += " --logical_volumes"
        if volume_groups is True:
            cmd += " --volume_groups"
        if physical_volumes is True:
            cmd += " --physical_volumes"
        if long_format is True:
            cmd += " --long"
        if human_readable is True:
            cmd += " -h"
        return cmd

    cmd = "virt-filesystems"
    # If you need to mount a disk, set is_disk to True
    is_disk = dargs.get("is_disk", False)
    ignore_status = dargs.get("ignore_status", True)
    debug = dargs.get("debug", False)
    timeout = dargs.get("timeout", 60)

    if is_disk is True:
        cmd += " -a %s" % disk_or_domain
    else:
        cmd += " -d %s" % disk_or_domain
    cmd = get_display_type(cmd, dargs)
    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_list_partitions(disk_or_domain, long=False, total=False,
                         human_readable=False, ignore_status=True,
                         debug=False, timeout=60):
    """
    "virt-list-partitions" is a command line tool to list the partitions
    that are contained in a virtual machine or disk image.

    :param disk_or_domain: a disk or a domain to be mounted
    """
    cmd = "virt-list-partitions %s" % disk_or_domain
    if long is True:
        cmd += " --long"
    if total is True:
        cmd += " --total"
    if human_readable is True:
        cmd += " --human-readable"
    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_list_filesystems(disk_or_domain, format=None, long=False,
                          all=False, ignore_status=True, debug=False,
                          timeout=60):
    """
    "virt-list-filesystems" is a command line tool to list the filesystems
    that are contained in a virtual machine or disk image.

    :param disk_or_domain: a disk or a domain to be mounted
    """
    cmd = "virt-list-filesystems %s" % disk_or_domain
    if format is not None:
        cmd += " --format %s" % format
    if long is True:
        cmd += " --long"
    if all is True:
        cmd += " --all"
    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_df(disk_or_domain, ignore_status=True, debug=False, timeout=60):
    """
    "virt-df" is a command line tool to display free space on
    virtual machine filesystems.
    """
    cmd = "virt-df %s" % disk_or_domain
    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_sysprep_cmd(disk_or_domain, options=None,
                     extra=None, ignore_status=True,
                     debug=False, timeout=600):
    """
    Execute virt-sysprep command to reset or unconfigure a virtual machine.

    :param disk_or_domain: a img path or a domain name.
    :param options: the options of virt-sysprep.
    :return: a CmdResult object.
    """
    if os.path.isfile(disk_or_domain):
        disk_or_domain = "-a " + disk_or_domain
    else:
        disk_or_domain = "-d " + disk_or_domain
    cmd = "virt-sysprep %s" % (disk_or_domain)
    if options is not None:
        cmd += " %s" % options
    if extra is not None:
        cmd += " %s" % extra

    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_cat_cmd(disk_or_domain, file_path, options=None, ignore_status=True,
                 debug=False, timeout=60):
    """
    Execute virt-cat command to print guest's file detail.

    :param disk_or_domain: a img path or a domain name.
    :param file_path: the file to print detail
    :param options: the options of virt-cat.
    :return: a CmdResult object.
    """
    # disk_or_domain and file_path are necessary parameters.
    if os.path.isfile(disk_or_domain):
        disk_or_domain = "-a " + disk_or_domain
    else:
        disk_or_domain = "-d " + disk_or_domain
    cmd = "virt-cat %s '%s'" % (disk_or_domain, file_path)
    if options is not None:
        cmd += " %s" % options

    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_tar_in(disk_or_domain, tar_file, destination, is_disk=False,
                ignore_status=True, debug=False, timeout=60):
    """
    "virt-tar-in" unpacks an uncompressed tarball into a virtual machine
    disk image or named libvirt domain.
    """
    cmd = "virt-tar-in"
    if is_disk is True:
        cmd += " -a %s" % disk_or_domain
    else:
        cmd += " -d %s" % disk_or_domain
    cmd += " %s %s" % (tar_file, destination)
    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_tar_out(disk_or_domain, directory, tar_file, is_disk=False,
                 ignore_status=True, debug=False, timeout=60):
    """
    "virt-tar-out" packs a virtual machine disk image directory into a tarball.
    """
    cmd = "virt-tar-out"
    if is_disk is True:
        cmd += " -a %s" % disk_or_domain
    else:
        cmd += " -d %s" % disk_or_domain
    cmd += " %s %s" % (directory, tar_file)
    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_copy_in(disk_or_domain, file, destination, is_disk=False,
                 ignore_status=True, debug=False, timeout=60):
    """
    "virt-copy-in" copies files and directories from the local disk into a
    virtual machine disk image or named libvirt domain.
    #TODO: expand file to files
    """
    cmd = "virt-copy-in"
    if is_disk is True:
        cmd += " -a %s" % disk_or_domain
    else:
        cmd += " -d %s" % disk_or_domain
    cmd += " %s %s" % (file, destination)
    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_copy_out(disk_or_domain, file_path, localdir, is_disk=False,
                  ignore_status=True, debug=False, timeout=60):
    """
    "virt-copy-out" copies files and directories out of a virtual machine
    disk image or named libvirt domain.
    """
    cmd = "virt-copy-out"
    if is_disk is True:
        cmd += " -a %s" % disk_or_domain
    else:
        cmd += " -d %s" % disk_or_domain
    cmd += " %s %s" % (file_path, localdir)
    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_format(disk, filesystem=None, image_format=None, lvm=None,
                partition=None, wipe=False, ignore_status=False,
                debug=False, timeout=60):
    """
    Virt-format takes an existing disk file (or it can be a host partition,
    LV etc), erases all data on it, and formats it as a blank disk.
    """
    cmd = "virt-format -a %s" % disk
    if filesystem is not None:
        cmd += " --filesystem=%s" % filesystem
    if image_format is not None:
        cmd += " --format=%s" % image_format
    if lvm is not None:
        cmd += " --lvm=%s" % lvm
    if partition is not None:
        cmd += " --partition=%s" % partition
    if wipe is True:
        cmd += " --wipe"
    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_inspector(disk_or_domain, is_disk=False, ignore_status=True,
                   debug=False, timeout=60):
    """
    virt-inspector2 examines a virtual machine or disk image and tries to
    determine the version of the operating system and other information
    about the virtual machine.
    """
    # virt-inspector has been replaced by virt-inspector2 in RHEL7
    # Check it here to choose which one to be used.
    cmd = lgf_cmd_check("virt-inspector2")
    if cmd is None:
        cmd = "virt-inspector"

    # If you need to mount a disk, set is_disk to True
    if is_disk is True:
        cmd += " -a %s" % disk_or_domain
    else:
        cmd += " -d %s" % disk_or_domain
    return lgf_command(cmd, ignore_status, debug, timeout)


def virt_sysprep_operations():
    """Get virt-sysprep support operation"""
    sys_list_cmd = "virt-sysprep --list-operations"
    result = lgf_command(sys_list_cmd, ignore_status=False)
    oper_info = result.stdout.strip()
    oper_dict = {}
    for oper_item in oper_info.splitlines():
        oper = oper_item.split("*")[0].strip()
        desc = oper_item.split("*")[-1].strip()
        oper_dict[oper] = desc
    return oper_dict


def virt_cmd_contain_opt(virt_cmd, opt):
    """ Check if opt is supported by virt-command"""
    if lgf_cmd_check(virt_cmd) is None:
        raise LibguestfsCmdError
    if not opt.startswith('-'):
        raise ValueError("Format should be '--a' or '-a', not '%s'" % opt)
    virt_help_cmd = virt_cmd + " --help"
    result = lgf_command(virt_help_cmd, ignore_status=False)
    # "--add" will not equal to "--addxxx"
    opt = " " + opt.strip() + " "
    return (result.stdout.count(opt) != 0)


def virt_ls_cmd(disk_or_domain, file_dir_path, is_disk=False, options=None,
                extra=None, connect_uri=None, ignore_status=True,
                debug=False, timeout=60):
    """
    Execute virt-ls command to check whether file exists.

    :param disk_or_domain: a img path or a domain name.
    :param file_dir_path: the file or directory need to check.
    """
    # disk_or_domain and file_dir_path are necessary parameters.
    cmd = "virt-ls"
    if connect_uri is not None:
        cmd += " -c %s" % connect_uri
    if is_disk:
        cmd += " -a %s" % disk_or_domain
    else:
        cmd += " -d %s" % disk_or_domain
    cmd += " %s" % file_dir_path
    if options is not None:
        cmd += " %s" % options
    if extra is not None:
        cmd += " %s" % extra

    return lgf_command(cmd, ignore_status, debug, timeout)
