"""
libguestfs tools test utility functions.
"""

import logging
import signal

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
                       'virt-win-reg']

    if not (cmd in libguestfs_cmds):
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

    __slots__ = ('ignore_status', 'debug', 'timeout', 'uri', 'lgf_exec')

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

    def set_timeout(self, timeout):
        """
        Accessor method for 'timeout' property, timeout should be digit
        """
        if type(timeout) is int:
            self.dict_set('timeout', timeout)
        else:
            try:
                timeout = int(str(timeout))
                self.dict_set('timeout', timeout)
            except ValueError:
                logging.debug("Set timeout failed.")

    def get_uri(self):
        """
        Accessor method for 'uri' property that must exist
        """
        # self.get() would call get_uri() recursivly
        try:
            return self.dict_get('uri')
        except KeyError:
            return None


# There are two ways to call guestfish:
# 1.Guestfish classies provided below(shell session)
# 2.guestfs module provided in system libguestfs package

class Guestfish(LibguestfsBase):

    """
    Execute guestfish, using a new guestfish shell each time.
    """

    __slots__ = LibguestfsBase.__slots__

    def __init__(self, disk_img=None, ro_mode=False,
                 libvirt_domain=None, inspector=False,
                 uri=None, mount_options=None):
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
        guestfs_exec = self.dict_get('lgf_exec')
        ignore_status = self.dict_get('ignore_status')
        debug = self.dict_get('debug')
        timeout = self.dict_get('timeout')
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

        :param cmd: guestfish command to send (must not contain newline characters)
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


class GuestfishPersistent(Guestfish):

    """
    Execute operations using persistent guestfish session.
    """

    __slots__ = Guestfish.__slots__ + ('session_id', )

    # Help detect leftover sessions
    SESSION_COUNTER = 0

    def __init__(self, disk_img=None, ro_mode=False,
                 libvirt_domain=None, inspector=False,
                 uri=None, mount_options=None):
        super(GuestfishPersistent, self).__init__(disk_img, ro_mode,
                                                  libvirt_domain, inspector,
                                                  uri, mount_options)
        if self.get('session_id') is None:
            # set_uri does not call when INITIALIZED = False
            # and no session_id passed to super __init__
            self.new_session()

        # Check whether guestfish session is prepared.
        guestfs_session = self.open_session()
        if guestfs_session.cmd_status('is-ready', timeout=60) != 0:
            logging.debug("Persistent guestfish session is not responding.")
            raise aexpect.ShellStatusError(self.lgf_exec, 'is-ready')

    def close_session(self):
        """
        If a persistent session exists, close it down.
        """
        try:
            existing = self.open_session()
            # except clause exits function
            # Try to end session with inner command 'quit'
            try:
                existing.cmd("quit")
                # It should jump to exception followed normally
            except aexpect.ShellProcessTerminatedError:
                self.__class__.SESSION_COUNTER -= 1
                self.dict_del('session_id')
                return  # guestfish session was closed normally
            # Close with 'quit' did not respond
            # So close with aexpect functions
            if existing.is_alive():
                # try nicely first
                existing.close()
                if existing.is_alive():
                    # Be mean, incase it's hung
                    existing.close(sig=signal.SIGTERM)
                # Keep count:
                self.__class__.SESSION_COUNTER -= 1
                self.dict_del('session_id')
        except LibguestfsCmdError:
            # Allow other exceptions to be raised
            pass  # session was closed already

    def new_session(self):
        """
        Open new session, closing any existing
        """
        # Accessors may call this method, avoid recursion
        guestfs_exec = self.dict_get('lgf_exec')  # Must exist, can't be None
        self.close_session()
        # Always create new session
        new_session = GuestfishSession(guestfs_exec)
        # Keep count
        self.__class__.SESSION_COUNTER += 1
        session_id = new_session.get_id()
        self.dict_set('session_id', session_id)

    def open_session(self):
        """
        Return session with session_id in this class.
        """
        try:
            session_id = self.dict_get('session_id')
            if session_id:
                try:
                    return GuestfishSession(a_id=session_id)
                except aexpect.ShellStatusError:
                    # session was already closed
                    self.dict_del('session_id')
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
        ignore_status = self.dict_get('ignore_status')
        return session.cmd_result(command, ignore_status=ignore_status)

    def add_drive(self, filename):
        """
        add-drive - add an image to examine or modify

        This function is the equivalent of calling "add_drive_opts" with no
        optional parameters, so the disk is added writable, with the format
        being detected automatically.
        """
        return self.inner_cmd("add-drive %s" % filename)

    def add_drive_opts(self, filename, readonly=False, format=None,
                       iface=None, name=None):
        """
        add-drive-opts - add an image to examine or modify.

        This function adds a disk image called "filename" to the handle.
        "filename" may be a regular host file or a host device.
        """
        cmd = "add-drive-opts %s" % filename

        if readonly:
            cmd += " readonly:true"
        else:
            cmd += " readonly:false"
        if format:
            cmd += " format:%s" % format
        if iface:
            cmd += " iface:%s" % iface
        if name:
            cmd += " name:%s" % name

        return self.inner_cmd(cmd)

    def add_drive_ro(self, filename):
        """
        add-ro/add-drive-ro - add a drive in snapshot mode (read-only)

        This function is the equivalent of calling "add_drive_opts" with the
        optional parameter "GUESTFS_ADD_DRIVE_OPTS_READONLY" set to 1, so the
        disk is added read-only, with the format being detected automatically.
        """
        return self.inner_cmd("add-drive-ro %s" % filename)

    def add_domain(self, domain, libvirturi=None, readonly=False, iface=None,
                   live=False, allowuuid=False, readonlydisk=None):
        """
        domain/add-domain - add the disk(s) from a named libvirt domain

        This function adds the disk(s) attached to the named libvirt domain
        "dom". It works by connecting to libvirt, requesting the domain and
        domain XML from libvirt, parsing it for disks, and calling
        "add_drive_opts" on each one.
        """
        cmd = "add-domain %s" % domain

        if libvirturi:
            cmd += " libvirturi:%s" % libvirturi
        if readonly:
            cmd += " readonly:true"
        else:
            cmd += " readonly:false"
        if iface:
            cmd += " iface:%s" % iface
        if live:
            cmd += " live:true"
        if allowuuid:
            cmd += " allowuuid:true"
        if readonlydisk:
            cmd += " readonlydisk:%s" % readonlydisk

        return self.inner_cmd(cmd)

    def run(self):
        """
        run/launch - launch the qemu subprocess

        Internally libguestfs is implemented by running a virtual machine
        using qemu.
        """
        return self.inner_cmd("launch")

    def df(self):
        """
        df - report file system disk space usage

        This command runs the "df" command to report disk space used.
        """
        return self.inner_cmd("df")

    def list_partitions(self):
        """
        list-partitions - list the partitions

        List all the partitions detected on all block devices.
        """
        return self.inner_cmd("list-partitions")

    def mount(self, device, mountpoint):
        """
        mount - mount a guest disk at a position in the filesystem

        Mount a guest disk at a position in the filesystem.
        """
        return self.inner_cmd("mount %s %s" % (device, mountpoint))

    def mount_ro(self, device, mountpoint):
        """
        mount-ro - mount a guest disk, read-only

        This is the same as the "mount" command, but it mounts the
        filesystem with the read-only (*-o ro*) flag.
        """
        return self.inner_cmd("mount-ro %s %s" % (device, mountpoint))

    def mount_options(self, options, device, mountpoint):
        """
        mount - mount a guest disk at a position in the filesystem

        Mount a guest disk at a position in the filesystem.
        """
        return self.inner_cmd("mount %s %s %s" % (options, device, mountpoint))

    def mounts(self):
        """
        mounts - show mounted filesystems

        This returns the list of currently mounted filesystems.
        """
        return self.inner_cmd("mounts")

    def mountpoints(self):
        """
        mountpoints - show mountpoints

        This call is similar to "mounts".
        That call returns a list of devices.
        """
        return self.inner_cmd("mountpoints")

    def read_file(self, path):
        """
        read-file - read a file

        This calls returns the contents of the file "path" as a buffer.
        """
        return self.inner_cmd("read-file %s" % path)

    def cat(self, path):
        """
        cat - list the contents of a file

        Return the contents of the file named "path".
        """
        return self.inner_cmd("cat %s" % path)

    def write(self, path, content):
        """
        write - create a new file

        This call creates a file called "path". The content of the file
        is the string "content" (which can contain any 8 bit data).
        """
        return self.inner_cmd("write %s %s" % (path, content))

    def write_append(self, path, content):
        """
        write-append - append content to end of file

        This call appends "content" to the end of file "path".
        If "path" does not exist, then a new file is created.
        """
        return self.inner_cmd("write-append %s %s" % (path, content))

    def inspect_os(self):
        """
        inspect-os - inspect disk and return list of operating systems found

        This function uses other libguestfs functions and certain heuristics to
        inspect the disk(s) (usually disks belonging to a virtual machine),
        looking for operating systems.
        """
        return self.inner_cmd("inspect-os")

    def list_filesystems(self):
        """
        list-filesystems - list filesystems

        This inspection command looks for filesystems on partitions, block
        devices and logical volumes, returning a list of devices containing
        filesystems and their type.
        """
        return self.inner_cmd("list-filesystems")

    def list_devices(self):
        """
        list-devices - list the block devices

        List all the block devices.
        """
        return self.inner_cmd("list-devices")


# libguestfs module functions follow #####
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


def virt_edit_cmd(disk_or_domain, file_path, options=None,
                  extra=None, expr=None, ignore_status=True,
                  debug=False, timeout=60):
    """
    Execute virt-edit command to check whether it is ok.

    Since virt-edit will need uses' interact, maintain and return
    a session if there is no raise after command has been executed.

    :param disk_or_domain: a img path or a domain name.
    :param file_path: the file need to be edited in img file.
    :param options: the options of virt-edit.
    :param extra: additional suffix of command.
    :return: a session of executing virt-edit command.
    """
    # disk_or_domain and file_path are necessary parameters.
    cmd = "virt-edit '%s' '%s'" % (disk_or_domain, file_path)
    if options is not None:
        cmd += " %s" % options
    if extra is not None:
        cmd += " %s" % extra
    if expr is not None:
        cmd += " -e '%s'" % expr

    return lgf_command(cmd, ignore_status, debug, timeout)
