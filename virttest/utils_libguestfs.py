"""
libguestfs tools test utility functions.
"""

import logging
import signal
import os

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


class GuestfishPersistent(Guestfish):

    """
    Execute operations using persistent guestfish session.
    """

    __slots__ = ['session_id']

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
                self.__dict_del__('session_id')
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
            if session_id:
                try:
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
        return self.inner_cmd("write '%s' '%s'" % (path, content))

    def write_append(self, path, content):
        """
        write-append - append content to end of file

        This call appends "content" to the end of file "path".
        If "path" does not exist, then a new file is created.
        """
        return self.inner_cmd("write-append '%s' '%s'" % (path, content))

    def inspect_os(self):
        """
        inspect-os - inspect disk and return list of operating systems found

        This function uses other libguestfs functions and certain heuristics to
        inspect the disk(s) (usually disks belonging to a virtual machine),
        looking for operating systems.
        """
        return self.inner_cmd("inspect-os")

    def inspect_get_roots(self):
        """
        inspect-get-roots - return list of operating systems found by
        last inspection

        This function is a convenient way to get the list of root devices
        """
        return self.inner_cmd("inspect-get-roots")

    def inspect_get_arch(self, root):
        """
        inspect-get-arch - get architecture of inspected operating system

        This returns the architecture of the inspected operating system.
        """
        return self.inner_cmd("inspect-get-arch %s" % root)

    def inspect_get_distro(self, root):
        """
        inspect-get-distro - get distro of inspected operating system

        This returns the distro (distribution) of the inspected
        operating system.
        """
        return self.inner_cmd("inspect-get-distro %s" % root)

    def inspect_get_filesystems(self, root):
        """
        inspect-get-filesystems - get filesystems associated with inspected
        operating system

        This returns a list of all the filesystems that we think are associated
        with this operating system.
        """
        return self.inner_cmd("inspect-get-filesystems %s" % root)

    def inspect_get_hostname(self, root):
        """
        inspect-get-hostname - get hostname of the operating system

        This function returns the hostname of the operating system as found by
        inspection of the guest's configuration files.
        """
        return self.inner_cmd("inspect-get-hostname %s" % root)

    def inspect_get_major_version(self, root):
        """
        inspect-get-major-version - get major version of inspected operating
        system

        This returns the major version number of the inspected
        operating system.
        """
        return self.inner_cmd("inspect-get-major-version %s" % root)

    def inspect_get_minor_version(self, root):
        """
        inspect-get-minor-version - get minor version of inspected operating
        system

        This returns the minor version number of the inspected operating system
        """
        return self.inner_cmd("inspect-get-minor-version %s" % root)

    def inspect_get_mountpoints(self, root):
        """
        inspect-get-mountpoints - get mountpoints of inspected operating system

        This returns a hash of where we think the filesystems associated with
        this operating system should be mounted.
        """
        return self.inner_cmd("inspect-get-mountpoints %s" % root)

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

    def tar_out(self, directory, tarfile):
        """
        tar-out - pack directory into tarfile

        This command packs the contents of "directory" and downloads it
        to local file "tarfile".
        """
        return self.inner_cmd("tar-out %s %s" % (directory, tarfile))

    def tar_in(self, tarfile, directory):
        """
        tar-in - unpack tarfile to directory

        This command uploads and unpacks local file "tarfile"
        (an *uncompressed* tar file) into "directory".
        """
        return self.inner_cmd("tar-in %s %s" % (tarfile, directory))

    def copy_out(self, remote, localdir):
        """
        copy-out - copy remote files or directories out of an image

        "copy-out" copies remote files or directories recursively out of the
        disk image, placing them on the host disk in a local directory called
        "localdir" (which must exist).
        """
        return self.inner_cmd("copy-out %s %s" % (remote, localdir))

    def copy_in(self, local, remotedir):
        """
        copy-in - copy local files or directories into an image

        "copy-in" copies local files or directories recursively into the disk
        image, placing them in the directory called "/remotedir" (which must
        exist).
        """
        return self.inner_cmd("copy-in %s /%s" % (local, remotedir))

    def rm(self, path):
        """
        rm - remove a file

        Remove the single file "path".
        """
        return self.inner_cmd("rm %s" % path)

    def is_file(self, path):
        """
        is-file - test if a regular file

        This returns "true" if and only if there is a regular file with the
        given "path" name.
        """
        return self.inner_cmd("is-file %s" % path)

    def cp(self, src, dest):
        """
        cp - copy a file

        This copies a file from "src" to "dest" where "dest" is either a
        destination filename or destination directory.
        """
        return self.inner_cmd("cp %s %s" % (src, dest))

    def part_init(self, device, parttype):
        """
        part-init - create an empty partition table

        This creates an empty partition table on "device" of one of the
        partition types listed below. Usually "parttype" should be either
        "msdos" or "gpt" (for large disks).
        """
        return self.inner_cmd("part-init %s %s" % (device, parttype))

    def part_add(self, device, prlogex, startsect, endsect):
        """
        part-add - add a partition to the device

        This command adds a partition to "device". If there is no partition
        table on the device, call "part_init" first.
        """
        cmd = "part-add %s %s %s %s" % (device, prlogex, startsect, endsect)
        return self.inner_cmd(cmd)

    def checksum(self, csumtype, path):
        """
        checksum - compute MD5, SHAx or CRC checksum of file

        This call computes the MD5, SHAx or CRC checksum of the file named
        "path".
        """
        return self.inner_cmd("checksum %s %s" % (csumtype, path))

    def is_ready(self):
        """
        is-ready - is ready to accept commands

        This returns true if this handle is ready to accept commands
        (in the "READY" state).
        """
        return self.inner_cmd("is-ready")

    def part_list(self, device):
        """
        part-list - list partitions on a device

        This command parses the partition table on "device" and
        returns the list of partitions found.
        """
        return self.inner_cmd("part-list %s" % device)

    def mkfs(self, fstype, device):
        """
        mkfs - make a filesystem

        This creates a filesystem on "device" (usually a partition or LVM
        logical volume). The filesystem type is "fstype", for example "ext3".
        """
        return self.inner_cmd("mkfs %s %s" % (fstype, device))

    def part_disk(self, device, parttype):
        """
        part-disk - partition whole disk with a single primary partition

        This command is simply a combination of "part_init" followed by
        "part_add" to create a single primary partition covering
        the whole disk.
        """
        return self.inner_cmd("part-disk %s %s" % (device, parttype))

    def part_get_bootable(self, device, partnum):
        """
        part-get-bootable - return true if a partition is bootable

        This command returns true if the partition "partnum" on "device"
        has the bootable flag set.
        """
        return self.inner_cmd("part-get-bootable %s %s" % (device, partnum))

    def part_get_mbr_id(self, device, partnum):
        """
        part-get-mbr-id - get the MBR type byte (ID byte) from a partition

        Returns the MBR type byte (also known as the ID byte) from the
        numbered partition "partnum".
        """
        return self.inner_cmd("part-get-mbr-id %s %s" % (device, partnum))

    def part_get_parttype(self, device):
        """
        part-get-parttype - get the partition table type

        This command examines the partition table on "device" and returns the
        partition table type (format) being used.
        """
        return self.inner_cmd("part-get-parttype %s" % device)

    def fsck(self, fstype, device):
        """
        fsck - run the filesystem checker

        This runs the filesystem checker (fsck) on "device" which should have
        filesystem type "fstype".
        """
        return self.inner_cmd("fsck %s %s" % (fstype, device))

    def blockdev_getss(self, device):
        """
        blockdev-getss - get sectorsize of block device

        This returns the size of sectors on a block device. Usually 512,
        but can be larger for modern devices.
        """
        return self.inner_cmd("blockdev-getss %s" % device)

    def blockdev_getsz(self, device):
        """
        blockdev-getsz - get total size of device in 512-byte sectors

        This returns the size of the device in units of 512-byte sectors
        (even if the sectorsize isn't 512 bytes ... weird).
        """
        return self.inner_cmd("blockdev-getsz %s" % device)

    def blockdev_getbsz(self, device):
        """
        blockdev-getbsz - get blocksize of block device

        This returns the block size of a device.
        """
        return self.inner_cmd("blockdev-getbsz %s" % device)

    def blockdev_getsize64(self, device):
        """
        blockdev-getsize64 - get total size of device in bytes

        This returns the size of the device in bytes
        """
        return self.inner_cmd("blockdev-getsize64 %s" % device)

    def blockdev_setbsz(self, device, blocksize):
        """
        blockdev-setbsz - set blocksize of block device

        This sets the block size of a device.
        """
        return self.inner_cmd("blockdev-setbsz %s %s" % (device, blocksize))

    def blockdev_getro(self, device):
        """
        blockdev-getro - is block device set to read-only

        Returns a boolean indicating if the block device is read-only
        (true if read-only, false if not).
        """
        return self.inner_cmd("blockdev-getro %s" % device)

    def blockdev_setro(self, device):
        """
        blockdev-setro - set block device to read-only

        Sets the block device named "device" to read-only.
        """
        return self.inner_cmd("blockdev-setro %s" % device)

    def blockdev_setrw(self, device):
        """
        blockdev-setrw - set block device to read-write

        Sets the block device named "device" to read-write.
        """
        return self.inner_cmd("blockdev-setrw %s" % device)

    def vgcreate(self, volgroup, physvols):
        """
        vgcreate - create an LVM volume group

        This creates an LVM volume group called "volgroup" from the
        non-empty list of physical volumes "physvols".
        """
        return self.inner_cmd("vgcreate %s %s" % (volgroup, physvols))

    def vgs(self):
        """
        vgs - list the LVM volume groups (VGs)

        List all the volumes groups detected.
        """
        return self.inner_cmd("vgs")

    def vgrename(self, volgroup, newvolgroup):
        """
        vgrename - rename an LVM volume group

        Rename a volume group "volgroup" with the new name "newvolgroup".
        """
        return self.inner_cmd("vgrename %s %s" % (volgroup, newvolgroup))

    def vgremove(self, vgname):
        """
        vgremove - remove an LVM volume group

        Remove an LVM volume group "vgname", (for example "VG").
        """
        return self.inner_cmd("vgremove %s" % vgname)

    def lvcreate(self, logvol, volgroup, mbytes):
        """
        lvcreate - create an LVM logical volume

        This creates an LVM logical volume called "logvol" on the
        volume group "volgroup", with "size" megabytes.
        """
        return self.inner_cmd("lvcreate %s %s %s" % (logvol, volgroup, mbytes))

    def lvuuid(self, device):
        """
        lvuuid - get the UUID of a logical volume

        This command returns the UUID of the LVM LV "device".
        """
        return self.inner_cmd("lvuuid %s" % device)

    def lvm_canonical_lv_name(self, lvname):
        """
        lvm-canonical-lv-name - get canonical name of an LV

        This converts alternative naming schemes for LVs that you might
        find to the canonical name.
        """
        return self.inner_cmd("lvm-canonical-lv-name %s" % lvname)

    def lvremove(self, device):
        """
        lvremove - remove an LVM logical volume

        Remove an LVM logical volume "device", where "device" is the path
        to the LV, such as "/dev/VG/LV".
        """
        return self.inner_cmd("lvremove %s" % device)

    def lvresize(self, device, mbytes):
        """
        lvresize - resize an LVM logical volume

        This resizes (expands or shrinks) an existing LVM logical volume to
        "mbytes".
        """
        return self.inner_cmd("lvresize %s %s" % (device, mbytes))

    def lvs(self):
        """
        lvs - list the LVM logical volumes (LVs)

        List all the logical volumes detected.
        """
        return self.inner_cmd("lvs")


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


def virt_clone_cmd(original, newname=None, autoclone=False, **dargs):
    """
    Clone existing virtual machine images.

    @param original: Name of the original guest to be cloned.
    @param newname: Name of the new guest virtual machine instance.
    @param autoclone: Generate a new guest name, and paths for new storage.
    @param dargs: Standardized function API keywords. There are many
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

    @param indisk: The source disk to be sparsified.
    @param outdisk: The destination disk.
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

    @param indisk: The source disk to be resized
    @param outdisk: The destination disk.
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

    @param disk_or_domain: a disk or a domain to be mounted
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

    @param disk_or_domain: a disk or a domain to be mounted
           If you need to mount a disk, set is_disk to True in dargs
    @param mountpoint: the mountpoint of filesystems
    @param inspector: mount all filesystems automatically
    @param readonly: if mount filesystem with readonly option
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

    @param disk_or_domain: a disk or a domain to be mounted
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
    if is_disk is True:
        cmd += " -a %s" % disk_or_domain
    else:
        cmd += " -d %s" % disk_or_domain
    cmd = get_display_type(cmd, dargs)
    return lgf_command(cmd, ignore_status=dargs.get('ignore_status', True),
                       debug=dargs.get('debug', False),
                       timeout=dargs.get('timeout', 60))


def virt_list_partitions(disk_or_domain, long=False, total=False,
                         human_readable=False, ignore_status=True,
                         debug=False, timeout=60):
    """
    "virt-list-partitions" is a command line tool to list the partitions
    that are contained in a virtual machine or disk image.

    @param disk_or_domain: a disk or a domain to be mounted
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

    @param disk_or_domain: a disk or a domain to be mounted
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
