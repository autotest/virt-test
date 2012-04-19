import os, logging, time, glob, re, shutil
from autotest.client.shared import error
from autotest.client import utils
import virt_utils

class VMError(Exception):
    pass


class VMCreateError(VMError):
    def __init__(self, cmd, status, output):
        VMError.__init__(self, cmd, status, output)
        self.cmd = cmd
        self.status = status
        self.output = output

    def __str__(self):
        return ("VM creation command failed:    %r    (status: %s,    "
                "output: %r)" % (self.cmd, self.status, self.output))


class VMStartError(VMError):
    def __init__(self, name, reason=None):
        VMError.__init__(self, name, reason)
        self.name = name
        self.reason = reason

    def __str__(self):
        msg = "VM '%s' failed to start" % self.name
        if self.reason is not None:
            msg += ": %s" % self.reason
        return msg


class VMConfigMissingError(VMError):
    def __init__(self, name, config):
        VMError.__init(self, name, config)
        self.name = name
        self.config = config

    def __str__(self):
        return "Missing config '%s' for VM %s" % (self.config, self.name)


class VMHashMismatchError(VMError):
    def __init__(self, actual, expected):
        VMError.__init__(self, actual, expected)
        self.actual_hash = actual
        self.expected_hash = expected

    def __str__(self):
        return ("CD image hash (%s) differs from expected one (%s)" %
                (self.actual_hash, self.expected_hash))


class VMImageMissingError(VMError):
    def __init__(self, filename):
        VMError.__init__(self, filename)
        self.filename = filename

    def __str__(self):
        return "CD image file not found: %r" % self.filename


class VMImageCheckError(VMError):
    def __init__(self, filename):
        VMError.__init__(self, filename)
        self.filename = filename

    def __str__(self):
        return "Errors found on image: %r" % self.filename


class VMBadPATypeError(VMError):
    def __init__(self, pa_type):
        VMError.__init__(self, pa_type)
        self.pa_type = pa_type

    def __str__(self):
        return "Unsupported PCI assignable type: %r" % self.pa_type


class VMPAError(VMError):
    def __init__(self, pa_type):
        VMError.__init__(self, pa_type)
        self.pa_type = pa_type

    def __str__(self):
        return ("No PCI assignable devices could be assigned "
                "(pci_assignable=%r)" % self.pa_type)


class VMPostCreateError(VMError):
    def __init__(self, cmd, output):
        VMError.__init__(self, cmd, output)
        self.cmd = cmd
        self.output = output


class VMHugePageError(VMPostCreateError):
    def __str__(self):
        return ("Cannot allocate hugepage memory    (command: %r,    "
                "output: %r)" % (self.cmd, self.output))


class VMKVMInitError(VMPostCreateError):
    def __str__(self):
        return ("Cannot initialize KVM    (command: %r,    output: %r)" %
                (self.cmd, self.output))


class VMDeadError(VMError):
    def __init__(self, reason='', detail=''):
        VMError.__init__(self)
        self.reason = reason
        self.detail = detail

    def __str__(self):
        msg = "VM is dead"
        if self.reason:
            msg += "    reason: %s" % self.reason
        if self.detail:
            msg += "    detail: %r" % self.detail
        return (msg)


class VMDeadKernelCrashError(VMError):
    def __init__(self, kernel_crash):
        VMError.__init__(self, kernel_crash)
        self.kernel_crash = kernel_crash

    def __str__(self):
        return ("VM is dead due to a kernel crash:\n%s" % self.kernel_crash)


class VMInvalidInstructionCode(VMError):
    def __init__(self, invalid_code):
        VMError.__init__(self, invalid_code)
        self.invalid_code = invalid_code

    def __str__(self):
        error = ""
        for invalid_code in self.invalid_code:
            error += "%s" % (invalid_code)
        return ("Invalid instruction was executed on VM:\n%s" % error)


class VMAddressError(VMError):
    pass


class VMPortNotRedirectedError(VMAddressError):
    def __init__(self, port):
        VMAddressError.__init__(self, port)
        self.port = port

    def __str__(self):
        return "Port not redirected: %s" % self.port


class VMAddressVerificationError(VMAddressError):
    def __init__(self, mac, ip):
        VMAddressError.__init__(self, mac, ip)
        self.mac = mac
        self.ip = ip

    def __str__(self):
        return ("Could not verify DHCP lease: "
                "%s --> %s" % (self.mac, self.ip))


class VMMACAddressMissingError(VMAddressError):
    def __init__(self, nic_index):
        VMAddressError.__init__(self, nic_index)
        self.nic_index = nic_index

    def __str__(self):
        return "No MAC defined for NIC #%s" % self.nic_index


class VMIPAddressMissingError(VMAddressError):
    def __init__(self, mac):
        VMAddressError.__init__(self, mac)
        self.mac = mac

    def __str__(self):
        return "No DHCP lease for MAC %s" % self.mac


class VMAddNetDevError(VMError):
    pass


class VMDelNetDevError(VMError):
    pass


class VMAddNicError(VMError):
    pass


class VMDelNicError(VMError):
    pass


class VMMigrateError(VMError):
    pass


class VMMigrateTimeoutError(VMMigrateError):
    pass


class VMMigrateCancelError(VMMigrateError):
    pass


class VMMigrateFailedError(VMMigrateError):
    pass

class VMMigrateProtoUnsupportedError(VMMigrateError):
    pass


class VMMigrateStateMismatchError(VMMigrateError):
    def __init__(self, src_hash, dst_hash):
        VMMigrateError.__init__(self, src_hash, dst_hash)
        self.src_hash = src_hash
        self.dst_hash = dst_hash

    def __str__(self):
        return ("Mismatch of VM state before and after migration (%s != %s)" %
                (self.src_hash, self.dst_hash))


class VMRebootError(VMError):
    pass

class VMStatusError(VMError):
    pass

class VMRemoveError(VMError):
    pass

class VMDeviceError(VMError):
    pass

class VMDeviceNotSupportedError(VMDeviceError):
    def __init__(self, name, device):
        VMDeviceError.__init__(self, name, device)
        self.name = name
        self.device = device

    def __str__(self):
        return ("Device '%s' is not supported for vm '%s' on this Host." %
                (self.device, self.name))

class VMUSBError(VMError):
    pass

class VMUSBControllerError(VMUSBError):
    pass

class VMUSBControllerMissingError(VMUSBControllerError):
    def __init__(self, name, controller_type):
        VMUSBControllerError.__init__(self, name, controller_type)
        self.name = name
        self.controller_type = controller_type

    def __str__(self):
        return ("Could not find '%s' USB Controller on vm '%s'. Please "
                "check config files." % (self.controller_type, self.name))

class VMUSBControllerPortFullError(VMUSBControllerError):
    def __init__(self, name):
        VMUSBControllerError.__init__(self, name)
        self.name = name

    def __str__(self):
        return ("No available USB Controller port left for VM %s." % self.name)


class BaseVM(object):
    """
    Base class for all hypervisor specific VM subclasses.

    This class should not be used directly, that is, do not attempt to
    instantiate and use this class. Instead, one should implement a subclass
    that implements, at the very least, all methods defined right after the
    the comment blocks that are marked with:

    "Public API - *must* be reimplemented with virt specific code"

    and

    "Protected API - *must* be reimplemented with virt specific classes"

    The current proposal regarding methods naming convention is:

    - Public API methods: named in the usual way, consumed by tests
    - Protected API methods: name begins with a single underline, to be
      consumed only by BaseVM and subclasses
    - Private API methods: name begins with double underline, to be consumed
      only by the VM subclass itself (usually implements virt specific
      functionality: example: __make_qemu_command())

    So called "protected" methods are intended to be used only by VM classes,
    and not be consumed by tests. Theses should respect a naming convention
    and always be preceeded by a single underline.

    Currently most (if not all) methods are public and appears to be consumed
    by tests. It is a ongoing task to determine whether  methods should be
    "public" or "protected".
    """

    #
    # Assuming that all low-level hypervisor have at least migration via tcp
    # (true for xen & kvm). Also true for libvirt (using xen and kvm drivers)
    #
    MIGRATION_PROTOS = ['tcp', ]

    #
    # Timeout definition. This is being kept inside the base class so that
    # sub classes can change the default just for themselves
    #
    LOGIN_TIMEOUT = 10
    LOGIN_WAIT_TIMEOUT = 240
    COPY_FILES_TIMEOUT = 600
    MIGRATE_TIMEOUT = 3600
    REBOOT_TIMEOUT = 240
    CREATE_TIMEOUT = 5

    def __init__(self, name, params):
        self.name = name
        self.params = params

        #
        # Assuming all low-level hypervisors will have a serial (like) console
        # connection to the guest. libvirt also supports serial (like) consoles
        # (virDomainOpenConsole). subclasses should set this to an object that
        # is or behaves like aexpect.ShellSession.
        #
        self.serial_console = None

        self._generate_unique_id()


    def _generate_unique_id(self):
        """
        Generate a unique identifier for this VM
        """
        while True:
            self.instance = (time.strftime("%Y%m%d-%H%M%S-") +
                             virt_utils.generate_random_string(4))
            if not glob.glob("/tmp/*%s" % self.instance):
                break


    #
    # Public API - could be reimplemented with virt specific code
    #
    def verify_alive(self):
        """
        Make sure the VM is alive and that the main monitor is responsive.

        Can be subclassed to provide better information on why the VM is
        not alive (reason, detail)

        @raise VMDeadError: If the VM is dead
        @raise: Various monitor exceptions if the monitor is unresponsive
        """
        if self.is_dead():
            raise VMDeadError


    def get_mac_address(self, nic_index=0):
        """
        Return the MAC address of a NIC.

        @param nic_index: Index of the NIC
        @raise VMMACAddressMissingError: If no MAC address is defined for the
                requested NIC
        """
        nic_name = self.params.objects("nics")[nic_index]
        nic_params = self.params.object_params(nic_name)
        mac = (nic_params.get("nic_mac") or
               virt_utils.get_mac_address(self.instance, nic_index))
        if not mac:
            raise VMMACAddressMissingError(nic_index)
        return mac


    def verify_kernel_crash(self):
        """
        Find kernel crash message on the VM serial console.

        @raise: VMDeadKernelCrashError, in case a kernel crash message was
                found.
        """
        if self.serial_console is not None:
            data = self.serial_console.get_output()
            match = re.search(r"BUG:.*---\[ end trace .* \]---", data,
                              re.DOTALL|re.MULTILINE)
            if match is not None:
                raise VMDeadKernelCrashError(match.group(0))


    def verify_illegal_instruction(self):
        """
        Find illegal instruction code on VM serial console output.

        @raise: VMInvalidInstructionCode, in case a wrong instruction code.
        """
        if self.serial_console is not None:
            data = self.serial_console.get_output()
            match = re.findall(r".*trap invalid opcode.*\n", data,
                               re.MULTILINE)

            if match:
                raise VMInvalidInstructionCode(match)


    def get_params(self):
        """
        Return the VM's params dict. Most modified params take effect only
        upon VM.create().
        """
        return self.params


    def get_serial_console_filename(self):
        """
        Return the serial console filename.
        """
        return "/tmp/serial-%s" % self.instance


    def get_testlog_filename(self):
        """
        Return the testlog filename.
        """
        return "/tmp/testlog-%s" % self.instance


    @error.context_aware
    def login(self, nic_index=0, timeout=LOGIN_TIMEOUT):
        """
        Log into the guest via SSH/Telnet/Netcat.
        If timeout expires while waiting for output from the guest (e.g. a
        password prompt or a shell prompt) -- fail.

        @param nic_index: The index of the NIC to connect to.
        @param timeout: Time (seconds) before giving up logging into the
                guest.
        @return: A ShellSession object.
        """
        error.context("logging into '%s'" % self.name)
        username = self.params.get("username", "")
        password = self.params.get("password", "")
        prompt = self.params.get("shell_prompt", "[\#\$]")
        linesep = eval("'%s'" % self.params.get("shell_linesep", r"\n"))
        client = self.params.get("shell_client")
        address = self.get_address(nic_index)
        port = self.get_port(int(self.params.get("shell_port")))
        log_filename = ("session-%s-%s.log" %
                        (self.name, virt_utils.generate_random_string(4)))
        session = virt_utils.remote_login(client, address, port, username,
                                         password, prompt, linesep,
                                         log_filename, timeout)
        session.set_status_test_command(self.params.get("status_test_command",
                                                        ""))
        return session


    def remote_login(self, nic_index=0, timeout=LOGIN_TIMEOUT):
        """
        Alias for login() for backward compatibility.
        """
        return self.login(nic_index, timeout)


    def wait_for_login(self, nic_index=0, timeout=LOGIN_WAIT_TIMEOUT,
                       internal_timeout=LOGIN_TIMEOUT):
        """
        Make multiple attempts to log into the guest via SSH/Telnet/Netcat.

        @param nic_index: The index of the NIC to connect to.
        @param timeout: Time (seconds) to keep trying to log in.
        @param internal_timeout: Timeout to pass to login().
        @return: A ShellSession object.
        """
        error_messages = []
        logging.debug("Attempting to log into '%s' (timeout %ds)", self.name,
                      timeout)
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                return self.login(nic_index, internal_timeout)
            except (virt_utils.LoginError, VMError), e:
                e = str(e)
                if e not in error_messages:
                    logging.debug(e)
                    error_messages.append(e)
            time.sleep(2)
        # Timeout expired; try one more time but don't catch exceptions
        return self.login(nic_index, internal_timeout)


    @error.context_aware
    def copy_files_to(self, host_path, guest_path, nic_index=0, verbose=False,
                      timeout=COPY_FILES_TIMEOUT):
        """
        Transfer files to the remote host(guest).

        @param host_path: Host path
        @param guest_path: Guest path
        @param nic_index: The index of the NIC to connect to.
        @param verbose: If True, log some stats using logging.debug (RSS only)
        @param timeout: Time (seconds) before giving up on doing the remote
                copy.
        """
        error.context("sending file(s) to '%s'" % self.name)
        username = self.params.get("username", "")
        password = self.params.get("password", "")
        client = self.params.get("file_transfer_client")
        address = self.get_address(nic_index)
        port = self.get_port(int(self.params.get("file_transfer_port")))
        log_filename = ("transfer-%s-to-%s-%s.log" %
                        (self.name, address,
                        virt_utils.generate_random_string(4)))
        virt_utils.copy_files_to(address, client, username, password, port,
                                host_path, guest_path, log_filename, verbose,
                                timeout)


    @error.context_aware
    def copy_files_from(self, guest_path, host_path, nic_index=0,
                        verbose=False, timeout=COPY_FILES_TIMEOUT):
        """
        Transfer files from the guest.

        @param host_path: Guest path
        @param guest_path: Host path
        @param nic_index: The index of the NIC to connect to.
        @param verbose: If True, log some stats using logging.debug (RSS only)
        @param timeout: Time (seconds) before giving up on doing the remote
                copy.
        """
        error.context("receiving file(s) from '%s'" % self.name)
        username = self.params.get("username", "")
        password = self.params.get("password", "")
        client = self.params.get("file_transfer_client")
        address = self.get_address(nic_index)
        port = self.get_port(int(self.params.get("file_transfer_port")))
        log_filename = ("transfer-%s-from-%s-%s.log" %
                        (self.name, address,
                        virt_utils.generate_random_string(4)))
        virt_utils.copy_files_from(address, client, username, password, port,
                                  guest_path, host_path, log_filename,
                                  verbose, timeout)


    @error.context_aware
    def serial_login(self, timeout=LOGIN_TIMEOUT):
        """
        Log into the guest via the serial console.
        If timeout expires while waiting for output from the guest (e.g. a
        password prompt or a shell prompt) -- fail.

        @param timeout: Time (seconds) before giving up logging into the guest.
        @return: ShellSession object on success and None on failure.
        """
        error.context("logging into '%s' via serial console" % self.name)
        username = self.params.get("username", "")
        password = self.params.get("password", "")
        prompt = self.params.get("shell_prompt", "[\#\$]")
        linesep = eval("'%s'" % self.params.get("shell_linesep", r"\n"))
        status_test_command = self.params.get("status_test_command", "")

        self.serial_console.set_linesep(linesep)
        self.serial_console.set_status_test_command(status_test_command)

        # Try to get a login prompt
        self.serial_console.sendline()

        virt_utils._remote_login(self.serial_console, username, password,
                                prompt, timeout)
        return self.serial_console


    def wait_for_serial_login(self, timeout=LOGIN_WAIT_TIMEOUT,
                              internal_timeout=LOGIN_TIMEOUT):
        """
        Make multiple attempts to log into the guest via serial console.

        @param timeout: Time (seconds) to keep trying to log in.
        @param internal_timeout: Timeout to pass to serial_login().
        @return: A ShellSession object.
        """
        error_messages = []
        logging.debug("Attempting to log into '%s' via serial console "
                      "(timeout %ds)", self.name, timeout)
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                return self.serial_login(internal_timeout)
            except virt_utils.LoginError, e:
                e = str(e)
                if e not in error_messages:
                    logging.debug(e)
                    error_messages.append(e)
            time.sleep(2)
        # Timeout expired; try one more time but don't catch exceptions
        return self.serial_login(internal_timeout)


    def get_uuid(self):
        """
        Catch UUID of the VM.

        @return: None,if not specified in config file
        """
        if self.params.get("uuid") == "random":
            return self.uuid
        else:
            return self.params.get("uuid", None)


    def send_string(self, str):
        """
        Send a string to the VM.

        @param str: String, that must consist of alphanumeric characters only.
                Capital letters are allowed.
        """
        for char in str:
            if char.isupper():
                self.send_key("shift-%s" % char.lower())
            else:
                self.send_key(char)


    def get_cpu_count(self):
        """
        Get the cpu count of the VM.
        """
        session = self.login()
        try:
            return int(session.cmd(self.params.get("cpu_chk_cmd")))
        finally:
            session.close()


    def get_memory_size(self, cmd=None):
        """
        Get bootup memory size of the VM.

        @param check_cmd: Command used to check memory. If not provided,
                self.params.get("mem_chk_cmd") will be used.
        """
        session = self.login()
        try:
            if not cmd:
                cmd = self.params.get("mem_chk_cmd")
            mem_str = session.cmd(cmd)
            mem = re.findall("([0-9]+)", mem_str)
            mem_size = 0
            for m in mem:
                mem_size += int(m)
            if "GB" in mem_str:
                mem_size *= 1024
            elif "MB" in mem_str:
                pass
            else:
                mem_size /= 1024
            return int(mem_size)
        finally:
            session.close()


    def get_current_memory_size(self):
        """
        Get current memory size of the VM, rather than bootup memory.
        """
        cmd = self.params.get("mem_chk_cur_cmd")
        return self.get_memory_size(cmd)


    #
    # Public API - *must* be reimplemented with virt specific code
    #
    def is_alive(self):
        """
        Return True if the VM is alive and the management interface is responsive.
        """
        raise NotImplementedError


    def is_dead(self):
        """
        Return True if the the VM is dead.
        """
        raise NotImplementedError


    def get_address(self, index=0):
        """
        Return the IP address of a NIC of the guest

        @param index: Index of the NIC whose address is requested.
        @raise VMMACAddressMissingError: If no MAC address is defined for the
                requested NIC
        @raise VMIPAddressMissingError: If no IP address is found for the the
                NIC's MAC address
        @raise VMAddressVerificationError: If the MAC-IP address mapping cannot
                be verified (using arping)
        """
        raise NotImplementedError


    def clone(self, name, **params):
        """
        Return a clone of the VM object with optionally modified parameters.

        This method should be implemented by
        """
        raise NotImplementedError


    def destroy(self, gracefully=True, free_mac_addresses=True):
        """
        Destroy the VM.

        If gracefully is True, first attempt to shutdown the VM with a shell
        command.  Then, attempt to destroy the VM via the monitor with a 'quit'
        command.  If that fails, send SIGKILL to the qemu process.

        @param gracefully: If True, an attempt will be made to end the VM
                using a shell command before trying to end the qemu process
                with a 'quit' or a kill signal.
        @param free_mac_addresses: If True, the MAC addresses used by the VM
                will be freed.
        """
        raise NotImplementedError


    def migrate(self, timeout=MIGRATE_TIMEOUT, protocol="tcp",
                cancel_delay=None, offline=False, stable_check=False,
                clean=True, save_path="/tmp", dest_host="localhost",
                remote_port=None):
        """
        Migrate the VM.

        If the migration is local, the VM object's state is switched with that
        of the destination VM.  Otherwise, the state is switched with that of
        a dead VM (returned by self.clone()).

        @param timeout: Time to wait for migration to complete.
        @param protocol: Migration protocol ('tcp', 'unix' or 'exec').
        @param cancel_delay: If provided, specifies a time duration after which
                migration will be canceled.  Used for testing migrate_cancel.
        @param offline: If True, pause the source VM before migration.
        @param stable_check: If True, compare the VM's state after migration to
                its state before migration and raise an exception if they
                differ.
        @param clean: If True, delete the saved state files (relevant only if
                stable_check is also True).
        @save_path: The path for state files.
        @param dest_host: Destination host (defaults to 'localhost').
        @param remote_port: Port to use for remote migration.
        """
        raise NotImplementedError


    def reboot(self, session=None, method="shell", nic_index=0,
               timeout=REBOOT_TIMEOUT):
        """
        Reboot the VM and wait for it to come back up by trying to log in until
        timeout expires.

        @param session: A shell session object or None.
        @param method: Reboot method.  Can be "shell" (send a shell reboot
                command) or "system_reset" (send a system_reset monitor command).
        @param nic_index: Index of NIC to access in the VM, when logging in
                after rebooting.
        @param timeout: Time to wait for login to succeed (after rebooting).
        @return: A new shell session object.
        """
        raise NotImplementedError


    # should this really be expected from VMs of all hypervisor types?
    def send_key(self, keystr):
        """
        Send a key event to the VM.

        @param: keystr: A key event string (e.g. "ctrl-alt-delete")
        """
        raise NotImplementedError

    def save_to_file(self, path):
        """
        State of paused VM recorded to path and VM shutdown on success

        Throws a VMStatusError if before/after state is incorrect.

        @param: path: file where VM state recorded

        """
        raise NotImplementedError

    def restore_from_file(self, path):
        """
        A shutdown or paused VM is resumed from path, & possibly set running

        Throws a VMStatusError if before/after restore state is incorrect

        @param: path: path to file vm state was saved to
        """
        raise NotImplementedError

    def needs_restart(self, name, params, basedir):
        """
        Based on virt preprocessing information, decide whether the VM needs
        a restart.
        """
        raise NotImplementedError


    def pause(self):
        """
        Stop the VM operation.
        """
        raise NotImplementedError


    def resume(self):
        """
        Resume the VM operation in case it's stopped.
        """
        raise NotImplementedError
