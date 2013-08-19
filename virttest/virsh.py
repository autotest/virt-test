"""
Utility classes and functions to handle connection to a libvirt host system

Suggested usage: import autotest.client.virt.virsh

The entire contents of callables in this module (minus the names defined in
NOCLOSE below), will become methods of the Virsh and VirshPersistent classes.
A Closure class is used to wrap the module functions, lambda does not
properly store instance state in this implementation.

Because none of the methods have a 'self' parameter defined, the classes
are defined to be dict-like, and get passed in to the methods as a the
special **dargs parameter.  All virsh module functions _MUST_ include a
special **dargs (variable keyword arguments) to accept non-default
keyword arguments.

The standard set of keyword arguments to all functions/modules is declared
in the VirshBase class.  Only the 'virsh_exec' key is guaranteed to always
be present, the remainder may or may not be provided.  Therefor, virsh
functions/methods should use the dict.get() method to retrieve with a default
for non-existant keys.

@copyright: 2012 Red Hat Inc.
"""

import signal, logging, urlparse, re
from autotest.client import utils, os_dep
from autotest.client.shared import error
from virttest import aexpect, propcan, remote

# list of symbol names NOT to wrap as Virsh class methods
# Everything else from globals() will become a method of Virsh class
NOCLOSE = globals().keys() + [
    'NOCLOSE', 'SCREENSHOT_ERROR_COUNT', 'VIRSH_COMMAND_CACHE',
    'VIRSH_EXEC', 'VirshBase', 'VirshClosure', 'VirshSession', 'Virsh',
    'VirshPersistent', 'VIRSH_COMMAND_GROUP_CACHE',
    'VIRSH_COMMAND_GROUP_CACHE_NO_DETAIL',
]

# Needs to be in-scope for Virsh* class screenshot method and module function
SCREENSHOT_ERROR_COUNT = 0

# Cache of virsh commands, used by help_command_group() and help_command_only()
# TODO: Make the cache into a class attribute on VirshBase class.
VIRSH_COMMAND_CACHE = None
VIRSH_COMMAND_GROUP_CACHE = None
VIRSH_COMMAND_GROUP_CACHE_NO_DETAIL = False

# This is used both inside and outside classes
try:
    VIRSH_EXEC = os_dep.command("virsh")
except ValueError:
    logging.warning("Virsh executable not set or found on path, "
                    "virsh module will not function normally")
    VIRSH_EXEC = '/bin/true'

class VirshBase(propcan.PropCanBase):
    """
    Base Class storing libvirt Connection & state to a host
    """

    __slots__ = ('uri', 'ignore_status', 'debug', 'virsh_exec')


    def __init__(self, *args, **dargs):
        """
        Initialize instance with virsh_exec always set to something
        """
        init_dict = dict(*args, **dargs)
        init_dict['virsh_exec'] = init_dict.get('virsh_exec', VIRSH_EXEC)
        init_dict['uri'] = init_dict.get('uri', None)
        init_dict['debug'] = init_dict.get('debug', False)
        init_dict['ignore_status'] = init_dict.get('ignore_status', False)
        super(VirshBase, self).__init__(init_dict)

    def get_uri(self):
        """
        Accessor method for 'uri' property that must exist
        """
        # self.get() would call get_uri() recursivly
        try:
            return self.dict_get('uri')
        except KeyError:
            return None


class VirshSession(aexpect.ShellSession):
    """
    A virsh shell session, used with Virsh instances.
    """

    # No way to get virsh sub-command "exit" status
    # Check output against list of known error-status strings
    ERROR_REGEX_LIST = ['error:\s*.+$', '.*failed.*']

    def __init__(self, virsh_exec=None, uri=None, a_id=None,
                 prompt=r"virsh\s*[\#\>]\s*", remote_ip=None,
                 remote_user=None, remote_pwd=None):
        """
        Initialize virsh session server, or client if id set.

        @param: virsh_exec: path to virsh executable
        @param: uri: uri of libvirt instance to connect to
        @param: id: ID of an already running server, if accessing a running
                server, or None if starting a new one.
        @param: prompt: Regular expression describing the shell's prompt line.
        @param: remote_ip: Hostname/IP of remote system to ssh into (if any)
        @param: remote_user: Username to ssh in as (if any)
        @param: remote_pwd: Password to use, or None for host/pubkey
        """

        self.uri = uri
        self.remote_ip = remote_ip
        self.remote_user = remote_user
        self.remote_pwd = remote_pwd

        # Special handling if setting up a remote session
        if a_id is None and remote_ip is not None and uri is not None:
            if remote_pwd:
                pref_auth = "-o PreferredAuthentications=password"
            else:
                pref_auth = "-o PreferredAuthentications=hostbased,publickey"
            # ssh_cmd != None flags this as remote session
            ssh_cmd = ("ssh -o UserKnownHostsFile=/dev/null %s -p %s %s@%s"
                       % (pref_auth, 22, self.remote_user, self.remote_ip))
            self.virsh_exec = ( "%s \"%s -c '%s'\""
                                % (ssh_cmd, virsh_exec, self.uri) )
        else: # setting up a local session or re-using a session
            if self.uri:
                self.virsh_exec += " -c '%s'" % self.uri
            else:
                self.virsh_exec = virsh_exec
            ssh_cmd = None # flags not-remote session

        # aexpect tries to auto close session because no clients connected yet
        aexpect.ShellSession.__init__(self, self.virsh_exec, a_id,
                                      prompt=prompt, auto_close=False)

        if ssh_cmd is not None: # this is a remote session
            # Handle ssh / password prompts
            remote.handle_prompts(self, self.remote_user, self.remote_pwd,
                                  prompt, debug=True)

        # fail if libvirtd is not running
        if self.cmd_status('list', timeout=60) != 0:
            logging.debug("Persistent virsh session is not responding, "
                          "libvirtd may be dead.")
            self.auto_close = True
            raise aexpect.ShellStatusError(virsh_exec, 'list')


    def cmd_status_output(self, cmd, timeout=60, internal_timeout=None,
                          print_func=None):
        """
        Send a virsh command and return its exit status and output.

        @param cmd: virsh command to send (must not contain newline characters)
        @param timeout: The duration (in seconds) to wait for the prompt to
                return
        @param internal_timeout: The timeout to pass to read_nonblocking
        @param print_func: A function to be used to print the data being read
                (should take a string parameter)
        @return: A tuple (status, output) where status is the exit status and
                output is the output of cmd
        @raise ShellTimeoutError: Raised if timeout expires
        @raise ShellProcessTerminatedError: Raised if the shell process
                terminates while waiting for output
        @raise ShellStatusError: Raised if the exit status cannot be obtained
        @raise ShellError: Raised if an unknown error occurs
        """
        out = self.cmd_output(cmd, timeout, internal_timeout, print_func)
        for line in out.splitlines():
            if self.match_patterns(line, self.ERROR_REGEX_LIST) is not None:
                return 1, out
        return 0, out


    def cmd_result(self, cmd, ignore_status=False):
        """Mimic utils.run()"""
        exit_status, stdout = self.cmd_status_output(cmd)
        stderr = '' # no way to retrieve this separately
        result = utils.CmdResult(cmd, stdout, stderr, exit_status)
        if not ignore_status and exit_status:
            raise error.CmdError(cmd, result,
                                 "Virsh Command returned non-zero exit status")
        return result


# Work around for inconsistent builtin closure local reference problem
# across different versions of python
class VirshClosure(object):
    """
    Callable that uses dict-like 'self' argument to augment **dargs
    """


    def __init__(self, reference_function, dict_like_instance):
        """
        Initialize callable for reference_function on dict_like_instance
        """
        if not issubclass(dict_like_instance.__class__, dict):
            raise ValueError("dict_like_instance %s must be dict or subclass"
                             % dict_like_instance.__class__.__name__)
        self.reference_function = reference_function
        self.dict_like_instance = dict_like_instance


    def __call__(self, *args, **dargs):
        """
        Call reference_function with dict_like_instance augmented by **dargs

        @param: *args: Passthrough to reference_function
        @param: **dargs: Updates dict_like_instance copy before call
        """
        dargs.update(self.dict_like_instance)
        return self.reference_function(*args, **dargs)


class Virsh(VirshBase):
    """
    Execute libvirt operations, using a new virsh shell each time.
    """

    __slots__ = VirshBase.__slots__


    def __init__(self, *args, **dargs):
        """
        Initialize Virsh instance with persistent options

        @param: *args: Initial property keys/values
        @param: **dargs: Initial property keys/values
        """
        # Set closure_args as a dict. This dict will be passed
        # to init VirshClosure objects.
        self.super_set("closure_args", dict())
        super(Virsh, self).__init__(*args, **dargs)
        # Init the closure_args for VirshClosure.
        for key, value in self.items():
            self.super_get("closure_args")[key] = value
        # Define the instance callables from the contents of this module
        # to avoid using class methods and hand-written aliases
        for sym, ref in globals().items():
            if sym not in NOCLOSE and callable(ref):
                # Adding methods, not properties, so avoid special __slots__
                # handling.  __getattribute__ will still find these.
                self.super_set(sym, VirshClosure(ref, self.super_get("closure_args")))

    def __setitem__(self, key, value):
        """
        Overwrite this method to update closure_args in setting item.
        """
        self.super_get("closure_args")[key] = value
        return super(Virsh, self).__setitem__(key, value)


class VirshPersistent(Virsh):
    """
    Execute libvirt operations using persistent virsh session.
    """

    __slots__ = Virsh.__slots__ + ('session_id', )

    # Help detect leftover sessions
    SESSION_COUNTER = 0

    def __init__(self, *args, **dargs):
        super(VirshPersistent, self).__init__(*args, **dargs)
        if self.get('session_id') is None:
            # set_uri does not call when INITIALIZED = False
            # and no session_id passed to super __init__
            self.new_session()


    def __exit__(self, exc_type, exc_value, traceback):
        """
        Clean up any leftover sessions
        """
        self.close_session()
        super(VirshPersistent, self).__exit__(exc_type, exc_value, traceback)


    def __del__(self):
        """
        Clean up any leftover sessions
        """
        self.__exit__(None, None, None)

    def close_session(self):
        """
        If a persistent session exists, close it down.
        """
        try:
            session_id = self.dict_get('session_id')
            if session_id:
                try:
                    existing = VirshSession(a_id=session_id)
                    # except clause exits function
                    self.dict_del('session_id')
                except aexpect.ShellStatusError:
                    # session was already closed
                    self.dict_del('session_id')
                    return # don't check is_alive or update counter
                if existing.is_alive():
                    # try nicely first
                    existing.close()
                    if existing.is_alive():
                        # Be mean, incase it's hung
                        existing.close(sig=signal.SIGTERM)
                    # Keep count:
                    self.__class__.SESSION_COUNTER -= 1
                    self.dict_del('session_id')
        except KeyError:
            # Allow other exceptions to be raised
            pass # session was closed already


    def new_session(self):
        """
        Open new session, closing any existing
        """
        # Accessors may call this method, avoid recursion
        virsh_exec = self.dict_get('virsh_exec') # Must exist, can't be None
        uri = self.dict_get('uri') # Must exist, can be None
        self.close_session()
        # Always create new session
        new_session = VirshSession(virsh_exec, uri, a_id=None)
        # Keep count
        self.__class__.SESSION_COUNTER += 1
        session_id = new_session.get_id()
        self.dict_set('session_id', session_id)


    def set_uri(self, uri):
        """
        Accessor method for 'uri' property, create new session on change
        """
        if not self.INITIALIZED:
            # Allow __init__ to call new_session
            self.dict_set('uri', uri)
        else:
            # If the uri is changing
            if self.dict_get('uri') != uri:
                self.dict_set('uri', uri)
                self.new_session()
            # otherwise do nothing


class VirshConnectBack(VirshPersistent):
    """
    Persistent virsh session connected back from a remote host
    """

    __slots__ = Virsh.__slots__ + ('remote_ip', 'remote_pwd', 'remote_user')

    def new_session(self):
        """
        Open new remote session, closing any existing
        """

        # Accessors may call this method, avoid recursion
        virsh_exec = self.dict_get('virsh_exec') # Must exist, can't be None
        uri = self.dict_get('uri') # Must exist, can be None
        remote_ip = self.dict_get('remote_ip')
        try:
            remote_user = self.dict_get('remote_user')
        except KeyError:
            remote_user = 'root'
        try:
            remote_pwd = self.dict_get('remote_pwd')
        except KeyError:
            remote_pwd = None
        super(VirshConnectBack, self).close_session()
        new_session = VirshSession(virsh_exec, uri, a_id=None,
                                   remote_ip=remote_ip,
                                   remote_user=remote_user,
                                   remote_pwd=remote_pwd)
        # Keep count
        self.__class__.SESSION_COUNTER += 1
        session_id = new_session.get_id()
        self.dict_set('session_id', session_id)


    @staticmethod
    def kosher_args(remote_ip, uri):
        """
        Convenience static method to help validate argument sanity before use

        @param: remote_ip: ip/hostname of remote libvirt helper-system
        @param: uri: fully qualified libvirt uri of local system, from remote.
        @returns: True/False if checks pass or not
        """
        if remote_ip is None or uri is None:
            return False
        all_false = [
            # remote_ip checks
            bool(remote_ip.count("EXAMPLE.COM")),
            bool(remote_ip.count("localhost")),
            bool(remote_ip.count("127.")),
            # uri checks
            uri is None,
            uri is "",
            bool(uri.count("default")),
            bool(uri.count(':///')),
            bool(uri.count("localhost")),
            bool(uri.count("127."))
        ]
        return True not in all_false


##### virsh module functions follow (See module docstring for API) #####


def command(cmd, **dargs):
    """
    Interface to cmd function as 'cmd' symbol is polluted

    @param: cmd: Command line to append to virsh command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    @raises: CmdError if non-zero exit status and ignore_status=False
    """

    virsh_exec = dargs.get('virsh_exec', VIRSH_EXEC)
    uri = dargs.get('uri', None)
    debug = dargs.get('debug', False)
    ignore_status = dargs.get('ignore_status', True) # Caller deals with errors
    session_id = dargs.get('session_id', None)

    # Check if this is a VirshPersistent method call
    if session_id:
        # Retrieve existing session
        session = VirshSession(a_id=session_id)
        logging.debug("Reusing session %s", session_id)
    else:
        session = None

    if debug:
        logging.debug("Running virsh command: %s", cmd)

    if session:
        # Utilize persistant virsh session
        ret = session.cmd_result(cmd, ignore_status)
        # Mark return value with session it came from
        ret.from_session_id = session_id
    else:
        # Normal call to run virsh command
        if uri:
            # uri argument IS being used
            uri_arg = " -c '%s' " % uri
        else:
            uri_arg = " " # No uri argument being used

        cmd = "%s%s%s" % (virsh_exec, uri_arg, cmd)
        # Raise exception if ignore_status == False
        ret = utils.run(cmd, verbose=debug, ignore_status=ignore_status)
        # Mark return as not coming from persistant virsh session
        ret.from_session_id = None

    # Always log debug info, if persistant session or not
    if debug:
        logging.debug("status: %s", ret.exit_status)
        logging.debug("stdout: %s", ret.stdout.strip())
        logging.debug("stderr: %s", ret.stderr.strip())

    # Return CmdResult instance when ignore_status is True
    return ret


def domname(dom_id_or_uuid, **dargs):
    """
    Convert a domain id or UUID to domain name

    @param: dom_id_or_uuid: a domain id or UUID.
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("domname --domain %s" % dom_id_or_uuid, **dargs)


def qemu_monitor_command(vm_name, cmd, **dargs):
    """
    This helps to execute the qemu monitor command through virsh command.

    @param: vm_name: Name of monitor domain
    @param: cmd: monitor command to execute
    @param: dargs: standardized virsh function API keywords
    """

    cmd_qemu_monitor = "qemu-monitor-command %s --hmp \'%s\'" % (vm_name, cmd)
    return command(cmd_qemu_monitor, **dargs)


def setvcpus(vm_name, count, extra="", **dargs):
    """
    Change the number of virtual CPUs in the guest domain.

    @oaram vm_name: name of vm to affect
    @param count: value for vcpu parameter
    @param options: any extra command options.
    @param dargs: standardized virsh function API keywords
    @return: CmdResult object from command
    """
    cmd = "setvcpus %s %s %s" % (vm_name, count, extra)
    return command(cmd, **dargs)


def vcpupin(vm_name, vcpu, cpu, **dargs):
    """
    Changes the cpu affinity for respective vcpu.

    @param: vm_name: name of domain
    @param: vcpu: virtual CPU to modify
    @param: cpu: physical CPU specification (string)
    @param: dargs: standardized virsh function API keywords
    @return: True operation was successful
    """
    dargs['ignore_status'] = False
    try:
        cmd_vcpupin = "vcpupin %s %s %s" % (vm_name, vcpu, cpu)
        command(cmd_vcpupin, **dargs)

    except error.CmdError, detail:
        logging.error("Virsh vcpupin VM %s failed:\n%s", vm_name, detail)
        return False


def vcpuinfo(vm_name, **dargs):
    """
    Retrieves the vcpuinfo command result if values not "N/A"

    @param: vm_name: name of domain
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    # Guarantee cmdresult object created
    dargs['ignore_status'] = True
    cmdresult = command("vcpuinfo %s" % vm_name, **dargs)
    if cmdresult.exit_status == 0:
        # Non-running vm makes virsh exit(0) but have "N/A" info.
        # on newer libvirt.  Treat this as an error.
        if re.search(r"\s*CPU:\s+N/A\s*", cmdresult.stdout.strip()):
            cmdresult.exit_status = -1
            cmdresult.stdout += "\n\nvirsh.vcpuinfo inject error: N/A values\n"
    return cmdresult


def vcpucount_live(vm_name, **dargs):
    """
    Prints the vcpucount of a given domain.

    @param: vm_name: name of a domain
    @param: dargs: standardized virsh function API keywords
    @return: standard output from command
    """

    cmd_vcpucount = "vcpucount --live --active %s" % vm_name
    return command(cmd_vcpucount, **dargs).stdout.strip()


def freecell(extra="", **dargs):
    """
    Prints the available amount of memory on the machine or within a NUMA cell.

    @param: dargs: extra: extra argument string to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd_freecell = "freecell %s" % extra
    return command(cmd_freecell, **dargs)


def nodeinfo(extra="", **dargs):
    """
    Returns basic information about the node,like number and type of CPU,
    and size of the physical memory.

    @param: dargs: extra: extra argument string to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd_nodeinfo = "nodeinfo %s" % extra
    return command(cmd_nodeinfo, **dargs)


def canonical_uri(option='', **dargs):
    """
    Return the hypervisor canonical URI.

    @param: option: additional option string to pass
    @param: dargs: standardized virsh function API keywords
    @return: standard output from command
    """
    return command("uri %s" % option, **dargs).stdout.strip()


def hostname(option='', **dargs):
    """
    Return the hypervisor hostname.

    @param: option: additional option string to pass
    @param: dargs: standardized virsh function API keywords
    @return: standard output from command
    """
    return command("hostname %s" % option, **dargs).stdout.strip()


def version(option='', **dargs):
    """
    Return the major version info about what this built from.

    @param: option: additional option string to pass
    @param: dargs: standardized virsh function API keywords
    @return: standard output from command
    """
    return command("version %s" % option, **dargs).stdout.strip()


def dom_list(options="", **dargs):
    """
    Return the list of domains.

    @param: options: options to pass to list command
    @return: CmdResult object
    """
    return command("list %s" % options, **dargs)


def reboot(name, options="", **dargs):
    """
    Run a reboot command in the target domain.

    @param: name: Name of domain.
    @param: options: options: options to pass to reboot command
    @return: CmdResult object
    """
    return command("reboot --domain %s %s" % (name, options), **dargs)


def managedsave(name, options="", **dargs):
    """
    Managed save of a domain state.

    @param: name: Name of domain to save
    @param: options: options: options to pass to list command
    @return: CmdResult object
    """
    return command("managedsave --domain %s %s" % (name, options), **dargs)


def managedsave_remove(name, **dargs):
    """
    Remove managed save of a domain

    @param: name: name of managed-saved domain to remove
    @return: CmdResult object
    """
    return command("managedsave-remove --domain %s" % name, **dargs)


def driver(**dargs):
    """
    Return the driver by asking libvirt

    @param: dargs: standardized virsh function API keywords
    @return: VM driver name
    """
    # libvirt schme composed of driver + command
    # ref: http://libvirt.org/uri.html
    scheme = urlparse.urlsplit( canonical_uri(**dargs) )[0]
    # extract just the driver, whether or not there is a '+'
    return scheme.split('+', 2)[0]


def domstate(name, **dargs):
    """
    Return the state about a running domain.

    @param name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("domstate %s" % name, **dargs)


def domid(vm_name, **dargs):
    """
    Return VM's ID.

    @param vm_name: VM name or uuid
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    return command("domid %s" % (vm_name), **dargs)


def dominfo(vm_name, **dargs):
    """
    Return the VM information.

    @param: vm_name: VM's name or id,uuid.
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    return command("dominfo %s" % (vm_name), **dargs)


def domuuid(name, **dargs):
    """
    Return the Converted domain name or id to the domain UUID.

    @param name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    return command("domuuid %s" % name, **dargs)


def screenshot(name, filename, **dargs):
    """
    Capture a screenshot of VM's console and store it in file on host

    @param: name: VM name
    @param: filename: name of host file
    @param: dargs: standardized virsh function API keywords
    @return: filename
    """
    global SCREENSHOT_ERROR_COUNT
    dargs['ignore_status'] = False
    try:
        command("screenshot %s %s" % (name, filename), **dargs)
    except error.CmdError, detail:
        if SCREENSHOT_ERROR_COUNT < 1:
            logging.error("Error taking VM %s screenshot. You might have to "
                          "set take_regular_screendumps=no on your "
                          "tests.cfg config file \n%s.  This will be the "
                          "only logged error message.", name, detail)
        SCREENSHOT_ERROR_COUNT += 1
    return filename


def domblkstat(name, device, option, **dargs):
    """
    Store state of VM into named file.

    @param: name: VM's name.
    @param: device: VM's device.
    @param: option: command domblkstat option.
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    return command("domblkstat %s %s %s" % (name, device, option), **dargs)


def dumpxml(name, extra="", to_file="", **dargs):
    """
    Return the domain information as an XML dump.

    @param: name: VM name
    @param: to_file: optional file to write XML output to
    @param: dargs: standardized virsh function API keywords
    @return: standard output from command
    """
    dargs['ignore_status'] = True
    cmd = "dumpxml %s %s" % (name, extra)
    result = command(cmd, **dargs)
    if to_file:
        result_file = open(to_file, 'w')
        result_file.write(result.stdout.strip())
        result_file.close()
    if result.exit_status:
        raise error.CmdError(cmd, result,
                                 "Virsh dumpxml returned non-zero exit status")
    return result.stdout.strip()


def domifstat(name, interface, **dargs):
    """
    Get network interface stats for a running domain.

    @param: name: Name of domain
    @param: interface: interface device
    @return: CmdResult object
    """
    return command("domifstat %s %s" % (name, interface), **dargs)


def domjobinfo(name, **dargs):
    """
    Get domain job information.

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    return command("domjobinfo %s" % name, **dargs)


def edit(options, **dargs):
    """
    Edit the XML configuration for a domain.

    @param options: virsh edit options string.
    @param dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("edit %s" % options, **dargs)


def domjobabort(vm_name, **dargs):
    """
    Aborts the currently running domain job.

    @param vm_name: VM's name, id or uuid.
    @param dargs: standardized virsh function API keywords
    @return: result from command
    """
    return command("domjobabort %s" % vm_name, **dargs)


def domxml_from_native(format, file, options=None, **dargs):
    """
    Convert native guest configuration format to domain XML format.

    @param format:The command's options. For exmple:qemu-argv.
    @param file:Native infomation file.
    @param options:extra param.
    @param dargs: standardized virsh function API keywords.
    @return: result from command
    """
    cmd = "domxml-from-native %s %s %s" % (format, file, options)
    return command(cmd, **dargs)


def domxml_to_native(format, file, options, **dargs):
    """
    Convert domain XML config to a native guest configuration format.

    @param format:The command's options. For exmple:qemu-argv.
    @param file:XML config file.
    @param options:extra param.
    @param dargs: standardized virsh function API keywords
    @return: result from command
    """
    cmd = "domxml-to-native %s %s %s" % (format, file, options)
    return command(cmd, **dargs)


def vncdisplay(vm_name,  **dargs):
    """
    Output the IP address and port number for the VNC display.

    @param vm_name: VM's name or id,uuid.
    @param dargs: standardized virsh function API keywords.
    @return: result from command
    """
    return command("vncdisplay %s" % vm_name, **dargs)


def is_alive(name, **dargs):
    """
    Return True if the domain is started/alive.

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: True operation was successful
    """
    return not is_dead(name, **dargs)


def is_dead(name, **dargs):
    """
    Return True if the domain is undefined or not started/dead.

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: True operation was successful
    """
    dargs['ignore_status'] = False
    try:
        state = domstate(name, **dargs).stdout.strip()
    except error.CmdError:
        return True
    if state in ('running', 'idle', 'no state', 'paused'):
        return False
    else:
        return True


def suspend(name, **dargs):
    """
    True on successful suspend of VM - kept in memory and not scheduled.

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("suspend %s" % (name), **dargs)


def resume(name, **dargs):
    """
    True on successful moving domain out of suspend

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("resume %s" % (name), **dargs)


def dommemstat(name, extra="", **dargs):
    """
    Store state of VM into named file.

    @param: name: VM name
    @param: extra: extra options to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    return command("dommemstat %s %s" % (name, extra), **dargs)


def dump(name, path, option="", **dargs):
    """
    Dump the core of a domain to a file for analysis.

    @param: name: VM name
    @param: path: absolute path to state file
    @param: option: command's option.
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    return command("dump %s %s %s" % (name, path, option), **dargs)


def save(option, path, **dargs):
    """
    Store state of VM into named file.

    @param: option: save command's first option, vm'name, id or uuid.
    @param: path: absolute path to state file
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    return command("save %s %s" % (option, path), **dargs)


def restore(path, **dargs):
    """
    Load state of VM from named file and remove file.

    @param: path: absolute path to state file.
    @param: dargs: standardized virsh function API keywords
    """
    return command("restore %s" % path, **dargs)


def start(name, **dargs):
    """
    True on successful start of (previously defined) inactive domain.

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object.
    """
    return command("start %s" % name, **dargs)


def shutdown(name, **dargs):
    """
    True on successful domain shutdown.

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("shutdown %s" % (name), **dargs)


def destroy(name, **dargs):
    """
    True on successful domain destruction

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("destroy %s" % (name), **dargs)


def define(xml_path, **dargs):
    """
    Return True on successful domain define.

    @param: xml_path: XML file path
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd = "define --file %s" % xml_path
    logging.debug("Define VM from %s", xml_path)
    return command(cmd, **dargs)


def undefine(name, **dargs):
    """
    Return cmd result of domain undefine (after shutdown/destroy).

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd = "undefine %s" % name
    logging.debug("Undefine VM %s", name)
    return command(cmd, **dargs)


def remove_domain(name, **dargs):
    """
    Return True after forcefully removing a domain if it exists.

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: True operation was successful
    """
    if domain_exists(name, **dargs):
        if is_alive(name, **dargs):
            destroy(name, **dargs)
        try:
            dargs['ignore_status'] = False
            undefine(name, **dargs)
        except error.CmdError, detail:
            logging.error("Undefine VM %s failed:\n%s", name, detail)
            return False
    return True


def domain_exists(name, **dargs):
    """
    Return True if a domain exits.

    @param name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: True operation was successful
    """
    dargs['ignore_status'] = False
    try:
        command("domstate %s" % name, **dargs)
        return True
    except error.CmdError, detail:
        logging.warning("VM %s does not exist:\n%s", name, detail)
        return False


def migrate(name="", dest_uri="", option="", extra="", **dargs):
    """
    Migrate a guest to another host.

    @param: name: name of guest on uri.
    @param: dest_uri: libvirt uri to send guest to
    @param: option: Free-form string of options to virsh migrate
    @param: extra: Free-form string of options to follow <domain> <desturi>
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd = "migrate"
    if option:
        cmd += " %s" % option
    if name:
        cmd += " --domain %s" % name
    if dest_uri:
        cmd += " --desturi %s" % dest_uri
    if extra:
        cmd += " %s" % extra

    return command(cmd, **dargs)


def migrate_setmaxdowntime(domain, downtime, extra=None, **dargs):
    """
    Set maximum tolerable downtime of a domain
    which is being live-migrated to another host.

    @param domain: name/uuid/id of guest
    @param downtime: downtime number of live migration
    """
    cmd = "migrate-setmaxdowntime %s %s" % (domain, downtime)
    if extra is not None:
        cmd += " %s" % extra
    return command(cmd, **dargs)


def attach_device(name, xml_file, extra="", **dargs):
    """
    Attach a device to VM.

    @param: name: name of guest
    @param: xml_file: xml describing device to detach
    @param: extra: additional arguments to command
    @param: dargs: standardized virsh function API keywords
    @return: True operation was successful
    """
    cmd = "attach-device --domain %s --file %s %s" % (name, xml_file, extra)
    dargs['ignore_status'] = False
    try:
        command(cmd, **dargs)
        return True
    except error.CmdError:
        logging.error("Attaching device to VM %s failed.", name)
        return False


def detach_device(name, xml_file, extra="", **dargs):
    """
    Detach a device from VM.

    @param: name: name of guest
    @param: xml_file: xml describing device to detach
    @param: extra: additional arguments to command
    @param: dargs: standardized virsh function API keywords
    @return: True operation was successful
    """
    cmd = "detach-device --domain %s --file %s %s" % (name, xml_file, extra)
    dargs['ignore_status'] = False
    try:
        command(cmd, **dargs)
        return True
    except error.CmdError:
        logging.error("Detaching device from VM %s failed.", name)
        return False


def update_device(domainarg=None, filearg=None,
                  domain_opt=None, file_opt=None,
                  flagstr="", **dargs):
    """
    Update device from an XML <file>.

    @param: domainarg: Domain name (first pos. parameter)
    @param: filearg: File name (second pos. parameter)
    @param: domain_opt: Option to --domain parameter
    @param: file_opt: Option to --file parameter
    @param: flagstr: string of "--force, --persistent, etc."
    @param dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    cmd = "update-device"
    if domainarg is not None: # Allow testing of ""
        cmd += " %s" % domainarg
    if filearg is not None: # Allow testing of 0 and ""
        cmd += " %s" % filearg
    if domain_opt is not None: # Allow testing of --domain ""
        cmd += " --domain %s" % domain_opt
    if file_opt is not None: # Allow testing of --file ""
        cmd += " --file %s" % file_opt
    if len(flagstr) > 0:
        cmd += " %s" % flagstr
    return command(cmd, **dargs)


def attach_disk(name, source, target, extra="", **dargs):
    """
    Attach a disk to VM.

    @param: name: name of guest
    @param: source: source of disk device
    @param: target: target of disk device
    @param: extra: additional arguments to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd = "attach-disk --domain %s --source %s --target %s %s"\
           % (name, source, target, extra)
    return command(cmd, **dargs)


def detach_disk(name, target, extra="", **dargs):
    """
    Detach a disk from VM.

    @param: name: name of guest
    @param: target: target of disk device
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd = "detach-disk --domain %s --target %s %s" % (name, target, extra)
    return command(cmd, **dargs)


def attach_interface(name, option="", **dargs):
    """
    Attach a NIC to VM.

    @param: name: name of guest
    @param: option: options to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd = "attach-interface "

    if name:
        cmd += "--domain %s" % name
    if option:
        cmd += " %s" % option

    return command(cmd, **dargs)


def detach_interface(name, option="", **dargs):
    """
    Detach a NIC to VM.

    @param: name: name of guest
    @param: option: options to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd = "detach-interface "

    if name:
        cmd += "--domain %s" % name
    if option:
        cmd += " %s" % option

    return command(cmd, **dargs)


def net_dumpxml(net_name, extra="", to_file="", **dargs):
    """
    Dump XML from network named net_name.

    @param: net_name: Name of a network
    @param: extra: Extra parameters to pass to command
    @param: to_file: Send result to a file
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd = "net-dumpxml %s %s" % (net_name, extra)
    result = command(cmd, **dargs)
    if to_file:
        result_file = open(to_file, 'w')
        result_file.write(result.stdout.strip())
        result_file.close()
    return result


def net_create(xml_file, extra="", **dargs):
    """
    Create _transient_ network from a XML file.

    @param: xml_file: xml defining network
    @param: extra: extra parameters to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("net-create %s %s" % (xml_file, extra), **dargs)


def net_define(xml_file, extra="", **dargs):
    """
    Define network from a XML file, do not start

    @param: xml_file: xml defining network
    @param: extra: extra parameters to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("net-define %s %s" % (xml_file, extra), **dargs)


def net_list(options, extra="", **dargs):
    """
    List networks on host.

    @param: options: options to pass to command
    @param: extra: extra parameters to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("net-list %s %s" % (options, extra), **dargs)


def net_state_dict(only_names=False, **dargs):
    """
    Return network name to state/autostart/persistent mapping

    @param: only_names: When true, return network names as keys and None values
    @param: dargs: standardized virsh function API keywords
    @return: dictionary
    """
    # Using multiple virsh commands in different ways
    dargs['ignore_status'] = False # force problem detection
    net_list_result = net_list("--all", **dargs)
    # If command failed, exception would be raised here
    netlist = net_list_result.stdout.strip().splitlines()
    # First two lines contain table header
    # TODO: Double-check first-two lines really are header
    netlist = netlist[2:]
    result = {}
    for line in netlist:
        # Split on whitespace, assume 3 columns
        linesplit = line.split(None, 3)
        name = linesplit[0]
        # Several callers in libvirt_xml only requre defined names
        if only_names:
            result[name] = None
            continue
        # Keep search fast & avoid first-letter capital problems
        active = not bool(linesplit[1].count("nactive"))
        autostart = bool(linesplit[2].count("es"))
        # There is no representation of persistent status in output
        try:
            # Rely on net_autostart will raise() if not persistent state
            if autostart: # Enabled, try enabling again
                # dargs['ignore_status'] already False
                net_autostart(name, **dargs)
            else: # Disabled, try disabling again
                net_autostart(name, "--disable", **dargs)
            # no exception raised, must be persistent
            persistent = True
        except error.CmdError, detail:
            # Exception thrown, could be transient or real problem
            if bool(str(detail.result_obj).count("ransient")):
                persistent = False
            else: # A unexpected problem happened, re-raise it.
                raise
        # Warning: These key names are used by libvirt_xml and test modules!
        result[name] = {'active':active,
                        'autostart':autostart,
                        'persistent':persistent}
    return result


def net_start(network, extra="", **dargs):
    """
    Start network on host.

    @param: network: name/parameter for network option/argument
    @param: extra: extra parameters to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("net-start %s %s" % (network, extra), **dargs)


def net_destroy(network, extra="", **dargs):
    """
    Destroy (stop) an activated network on host.

    @param: network: name/parameter for network option/argument
    @param: extra: extra string to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("net-destroy %s %s" % (network, extra), **dargs)


def net_undefine(network, extra="", **dargs):
    """
    Undefine a defined network on host.

    @param: network: name/parameter for network option/argument
    @param: extra: extra string to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("net-undefine %s %s" % (network, extra), **dargs)


def net_name(net_uuid, extra="", **dargs):
    """
    Get network name on host.

    @param: net_uuid: network UUID.
    @param: extra: extra parameters to pass to command.
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("net-name %s %s" % (net_uuid, extra), **dargs)


def net_uuid(network, extra="", **dargs):
    """
    Get network UUID on host.

    @param: network: name/parameter for network option/argument
    @param: extra: extra parameters to pass to command.
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("net-uuid %s %s" % (network, extra), **dargs)


def net_autostart(network, extra="", **dargs):
    """
    Set/unset a network to autostart on host boot

    @param: network: name/parameter for network option/argument
    @param: extra: extra parameters to pass to command (e.g. --disable)
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    return command("net-autostart %s %s" % (network, extra), **dargs)


def pool_info(name, **dargs):
    """
    Returns basic information about the storage pool.

    @param: name: name of pool
    @param: dargs: standardized virsh function API keywords
    """
    cmd = "pool-info %s" % name
    return command(cmd, **dargs)


def pool_destroy(name, **dargs):
    """
    Forcefully stop a given pool.

    @param: name: name of pool
    @param: dargs: standardized virsh function API keywords
    """
    cmd = "pool-destroy %s" % name
    dargs['ignore_status'] = False
    try:
        command(cmd, **dargs)
        return True
    except error.CmdError, detail:
        logging.error("Failed to destroy pool: %s.", detail)
        return False


def pool_create_as(name, pool_type, target, extra="", **dargs):
    """
    Create a pool from a set of args.

    @param: name: name of pool
    @param: pool_type: storage pool type such as 'dir'
    @param: target: libvirt uri to send guest to
    @param: extra: Free-form string of options
    @param: dargs: standardized virsh function API keywords
    @return: True if pool creation command was successful
    """

    if not name:
        logging.error("Please give a pool name")

    types = [ 'dir', 'fs', 'netfs', 'disk', 'iscsi', 'logical' ]

    if pool_type and pool_type not in types:
        logging.error("Only support pool types: %s.", types)
    elif not pool_type:
        pool_type = types[0]

    logging.info("Create %s type pool %s", pool_type, name)
    cmd = "pool-create-as --name %s --type %s --target %s %s" \
          % (name, pool_type, target, extra)
    dargs['ignore_status'] = False
    try:
        command(cmd, **dargs)
        return True
    except error.CmdError, detail:
        logging.error("Failed to create pool: %s.", detail)
        return False

def pool_list(option="", extra="", **dargs):
    """
    Prints the pool information of Host

    @param: option: options given to command
    --all - gives all pool details, including inactive
    --inactive - gives only inactive pool details
    --details - Gives the complete details about the pools
    @param: extra: to provide extra options(to enter invalid options)
    """
    return command("pool-list %s %s" % (option, extra), **dargs)


def pool_define_as(name, pool_type, target, extra="", **dargs):
    """
    Define the pool from the arguments

    @param: name: Name of the pool to be defined
    @param: typ: Type of the pool to be defined
    dir - file system directory
    disk - Physical Disk Device
    fs - Pre-formatted Block Device
    netfs - Network Exported Directory
    iscsi - iSCSI Target
    logical - LVM Volume Group
    mpath - Multipath Device Enumerater
    scsi - SCSI Host Adapter
    @param: target: libvirt uri to send guest to
    @param: extra: Free-form string of options
    @param: dargs: standardized virsh function API keywords
    @return: True if pool define command was successful
    """

    types = [ 'dir', 'fs', 'netfs', 'disk', 'iscsi', 'logical' ]

    if pool_type and pool_type not in types:
        logging.error("Only support pool types: %s.", types)
    elif not pool_type:
        pool_type = types[0]

    logging.info("Define %s type pool %s", pool_type, name)
    cmd = "pool-define-as --name %s --type %s --target %s %s" \
          % (name, pool_type, target, extra)
    return command(cmd, **dargs)


def pool_start(name, extra="", **dargs):
    """
    Start the defined pool
    @param: name: Name of the pool to be started
    @param: extra: Free-form string of options
    @param: dargs: standardized virsh function API keywords
    @return: True if pool start command was successful
    """
    return command("pool-start %s %s" % (name, extra), **dargs)


def pool_autostart(name, extra="", **dargs):
    """
    Mark for autostart of a pool
    @param: name: Name of the pool to be mark for autostart
    @param: extra: Free-form string of options
    @param: dargs: standardized virsh function API keywords
    @return: True if pool autostart command was successful
    """
    return command("pool-autostart %s %s" % (name, extra), **dargs)


def pool_undefine(name, extra="", **dargs):
    """
    Undefine the given pool

    @param: name: Name of the pool to be undefined
    @param: extra: Free-form string of options
    @param: dargs: standardized virsh function API keywords
    @return: True if pool undefine command was successful
    """
    return command("pool-undefine %s %s" % (name, extra), **dargs)


def vol_create_as(vol_name, pool_name, capacity, allocation,
                  frmt, extra="", **dargs):
    """
    To create the volumes on different available pool

    @param: name: Name of the volume to be created
    @param: pool_name: Name of the pool to be used
    @param: capacity: Size of the volume
    @param: allocaltion: Size of the volume to be pre-allocated
    @param: frmt: volume formats(e.g. raw, qed, qcow2)
    @param: extra: Free-form string of options
    @param: dargs: standardized virsh function API keywords
    @return: True if pool undefine command was successful
    """

    cmd = "vol-create-as --pool %s  %s --capacity %s" % (pool_name, vol_name, capacity)

    if allocation:
        cmd += " --allocation %s" % (allocation)
    if frmt:
        cmd += " --format %s" % (frmt)
    if extra:
        cmd += " %s" % (extra)
    return command(cmd, **dargs)


def vol_list(pool_name, extra="", **dargs):
    """
    List the volumes for a given pool
    """
    return command("vol-list %s %s" % (pool_name, extra), **dargs)


def vol_delete(vol_name, pool_name, extra="", **dargs):
    """
    Delete a given volume
    """
    return command("vol-delete %s %s %s" % (vol_name, pool_name, extra), **dargs)


def capabilities(option='', **dargs):
    """
    Return output from virsh capabilities command

    @param: option: additional options (takes none)
    @param: dargs: standardized virsh function API keywords
    """
    return command('capabilities %s' % option, **dargs).stdout.strip()


def nodecpustats(option='', **dargs):
    """
    Returns basic information about the node CPU statistics

    @param: option: additional options (takes none)
    @param: dargs: standardized virsh function API keywords
    """

    cmd_nodecpustat = "nodecpustats %s" % option
    return command(cmd_nodecpustat, **dargs)


def nodememstats(option='', **dargs):
    """
    Returns basic information about the node Memory statistics

    @param: option: additional options (takes none)
    @param: dargs: standardized virsh function API keywords
    """

    return command('nodememstats %s' % option, **dargs)


def memtune_set(vm_name, options, **dargs):
    """
    Set the memory controller parameters

    @param: domname: VM Name
    @param: options: contains the values limit, state and value
    """
    return command("memtune %s %s" % (vm_name, options), **dargs)


def memtune_list(vm_name, **dargs):
    """
    List the memory controller value of a given domain

    @param: domname: VM Name
    """
    return command("memtune %s" % (vm_name), **dargs)


def memtune_get(vm_name, key):
    """
    Get the specific memory controller value

    @param: domname: VM Name
    @param: key: memory controller limit for which the value needed
    @return: the memory value of a key in Kbs
    """
    memtune_output = memtune_list(vm_name)
    memtune_value = re.findall(r"%s\s*:\s+(\S+)" % key, str(memtune_output))
    if memtune_value:
        return int(memtune_value[0])
    else:
        return -1


def help_command(options='', cache=False, **dargs):
    """
    Return list of commands and groups in help command output

    @param: options: additional options to pass to help command
    @param: cache: Return cached result if True, or refreshed cache if False
    @param: dargs: standardized virsh function API keywords
    @return: List of command and group names
    """
    # Combine virsh command list and virsh group list.
    virsh_command_list = help_command_only(options, cache, **dargs)
    virsh_group_list = help_command_group(options, cache, **dargs)
    virsh_command_group = None
    virsh_command_group = virsh_command_list + virsh_group_list
    return virsh_command_group


def help_command_only(options='', cache=False, **dargs):
    """
    Return list of commands in help command output

    @param: options: additional options to pass to help command
    @param: cache: Return cached result if True, or refreshed cache if False
    @param: dargs: standardized virsh function API keywords
    @return: List of command names
    """
    # global needed to support this function's use in Virsh method closure
    global VIRSH_COMMAND_CACHE
    if not VIRSH_COMMAND_CACHE or cache is False:
        VIRSH_COMMAND_CACHE = []
        regx_command_word = re.compile(r"\s+([a-z0-9-]+)\s+")
        for line in help(options, **dargs).stdout.strip().splitlines():
            # Get rid of 'keyword' line
            if line.find("keyword") != -1:
                continue
            mobj_command_word = regx_command_word.search(line)
            if mobj_command_word:
                VIRSH_COMMAND_CACHE.append(mobj_command_word.group(1))
    # Prevent accidental modification of cache itself
    return list(VIRSH_COMMAND_CACHE)


def help_command_group(options='', cache=False, **dargs):
    """
    Return list of groups in help command output

    @param: options: additional options to pass to help command
    @param: cache: Return cached result if True, or refreshed cache if False
    @param: dargs: standardized virsh function API keywords
    @return: List of group names
    """
    # global needed to support this function's use in Virsh method closure
    global VIRSH_COMMAND_GROUP_CACHE, VIRSH_COMMAND_GROUP_CACHE_NO_DETAIL
    if VIRSH_COMMAND_GROUP_CACHE_NO_DETAIL:
        return []
    if not VIRSH_COMMAND_GROUP_CACHE or cache is False:
        VIRSH_COMMAND_GROUP_CACHE = []
        regx_group_word = re.compile(r"[\']([a-zA-Z0-9]+)[\']")
        for line in help(options, **dargs).stdout.strip().splitlines():
            # 'keyword' only exists in group line.
            if line.find("keyword") != -1:
                mojb_group_word = regx_group_word.search(line)
                if mojb_group_word:
                    VIRSH_COMMAND_GROUP_CACHE.append(mojb_group_word.group(1))
    if len(list(VIRSH_COMMAND_GROUP_CACHE)) == 0:
        VIRSH_COMMAND_GROUP_CACHE_NO_DETAIL = True
    # Prevent accidental modification of cache itself
    return list(VIRSH_COMMAND_GROUP_CACHE)


def has_help_command(virsh_cmd, options='', **dargs):
    """
    String match on virsh command in help output command list

    @param: virsh_cmd: Name of virsh command or group to look for
    @param: options: Additional options to send to help command
    @param: dargs: standardized virsh function API keywords
    @return: True/False
    """
    return bool( help_command_only(options, cache=True,
                 **dargs).count(virsh_cmd) )


def has_command_help_match(virsh_cmd, regex, **dargs):
    """
    Regex search on subcommand help output

    @param: virsh_cmd: Name of virsh command or group to match help output
    @param: regex: regular expression string to match
    @param: dargs: standardized virsh function API keywords
    @return: re match object
    """
    command_help_output = help(virsh_cmd, **dargs).stdout.strip()
    return re.search(regex, command_help_output)


def help(virsh_cmd='', **dargs):
    """
    Prints global help, command specific help, or help for a
    group of related commands

    @param virsh_cmd: Name of virsh command or group
    @param: dargs: standardized virsh function API keywords
    @returns: CmdResult instance
    """
    return command("help %s" % virsh_cmd, **dargs)


def schedinfo(domain, options="", **dargs):
    """
    Show/Set scheduler parameters.

    @param domain: vm's name id or uuid.
    @param options: additional options.
    @param: dargs: standardized virsh function API keywords
    """
    cmd = "schedinfo %s %s" % (domain, options)
    return command(cmd, **dargs)


def setmem(domainarg=None, sizearg=None, domain=None,
           size=None, use_kilobytes=False, flagstr="", **dargs):
    """
    Change the current memory allocation in the guest domain.

    @param: domainarg: Domain name (first pos. parameter)
    @param: sizearg: Memory size in KiB (second. pos. parameter)
    @param: domain: Option to --domain parameter
    @param: size: Option to --size or --kilobytes parameter
    @param: use_kilobytes: True for --kilobytes, False for --size
    @param: dargs: standardized virsh function API keywords
    @param: flagstr: string of "--config, --live, --current, etc."
    @returns: CmdResult instance
    @raises: error.CmdError: if libvirtd is not running!!!!!!
    """

    cmd = "setmem"
    if domainarg is not None: # Allow testing of ""
        cmd += " %s" % domainarg
    if sizearg is not None: # Allow testing of 0 and ""
        cmd += " %s" % sizearg
    if domain is not None: # Allow testing of --domain ""
        cmd += " --domain %s" % domain
    if size is not None: # Allow testing of --size "" or --size 0
        if use_kilobytes:
            cmd += " --kilobytes %s" % size
        else:
            cmd += " --size %s" % size
    if len(flagstr) > 0:
        cmd += " %s" % flagstr
    return command(cmd, **dargs)


def setmaxmem(domainarg=None, sizearg=None, domain=None,
              size=None, use_kilobytes=False, flagstr="", **dargs):
    """
    Change the maximum memory allocation for the guest domain.

    @param: domainarg: Domain name (first pos. parameter)
    @param: sizearg: Memory size in KiB (second. pos. parameter)
    @param: domain: Option to --domain parameter
    @param: size: Option to --size or --kilobytes parameter
    @param: use_kilobytes: True for --kilobytes, False for --size
    @param: flagstr: string of "--config, --live, --current, etc."
    @returns: CmdResult instance
    @raises: error.CmdError: if libvirtd is not running.
    """
    cmd = "setmaxmem"
    if domainarg is not None: # Allow testing of ""
        cmd += " %s" % domainarg
    if sizearg is not None: # Allow testing of 0 and ""
        cmd += " %s" % sizearg
    if domain is not None: # Allow testing of --domain ""
        cmd += " --domain %s" % domain
    if size is not None: # Allow testing of --size "" or --size 0
        if use_kilobytes:
            cmd += " --kilobytes %s" % size
        else:
            cmd += " --size %s" % size
    if len(flagstr) > 0:
        cmd += " %s" % flagstr
    return command(cmd, **dargs)


def snapshot_create(name, **dargs):
    """
    Create snapshot of domain.

    @param name: name of domain
    @param: dargs: standardized virsh function API keywords
    @return: name of snapshot
    """
    # CmdResult is handled here, force ignore_status
    dargs['ignore_status'] = True
    cmd = "snapshot-create %s" % name
    sc_output = command(cmd, **dargs)
    if sc_output.exit_status != 0:
        raise error.CmdError(cmd, sc_output, "Failed to create snapshot")
    snapshot_number = re.search("\d+", sc_output.stdout.strip()).group(0)

    return snapshot_number


def snapshot_current(name, **dargs):
    """
    Create snapshot of domain.

    @param name: name of domain
    @param: dargs: standardized virsh function API keywords
    @return: name of snapshot
    """
    # CmdResult is handled here, force ignore_status
    dargs['ignore_status'] = True
    cmd = "snapshot-current %s --name" % name
    sc_output = command(cmd, **dargs)
    if sc_output.exit_status != 0:
        raise error.CmdError(cmd, sc_output, "Failed to get current snapshot")

    return sc_output.stdout.strip()


def snapshot_list(name, **dargs):
    """
    Get list of snapshots of domain.

    @param name: name of domain
    @param: dargs: standardized virsh function API keywords
    @return: list of snapshot names
    """
    # CmdResult is handled here, force ignore_status
    dargs['ignore_status'] = True
    ret = []
    cmd = "snapshot-list %s" % name
    sc_output = command(cmd, **dargs)
    if sc_output.exit_status != 0:
        raise error.CmdError(cmd, sc_output, "Failed to get list of snapshots")

    data = re.findall("\w* *\d*-\d*-\d* \d*:\d*:\d* [+-]\d* \w*",
                      sc_output.stdout)
    for rec in data:
        if not rec:
            continue
        ret.append(re.match("\w*", rec).group())

    return ret


def snapshot_info(name, snapshot, **dargs):
    """
    Check snapshot information.

    @param name: name of domain
    @param snapshot: name os snapshot to verify
    @param: dargs: standardized virsh function API keywords
    @return: snapshot information dictionary
    """
    # CmdResult is handled here, force ignore_status
    dargs['ignore_status'] = True
    ret = {}
    values = ["Name", "Domain", "Current", "State", "Parent",
              "Children","Descendants", "Metadata"]

    cmd = "snapshot-info %s %s" % (name, snapshot)
    sc_output = command(cmd, **dargs)
    if sc_output.exit_status != 0:
        raise error.CmdError(cmd, sc_output, "Failed to get snapshot info")

    for val in values:
        data = re.search("(?<=%s:) *\w*" % val, sc_output.stdout)
        if data is None:
            continue
        ret[val] = data.group(0).strip()

    if ret["Parent"] == "-":
        ret["Parent"] = None

    return ret


def snapshot_revert(name, snapshot, **dargs):
    """
    Revert domain state to saved snapshot.

    @param name: name of domain
    @param: dargs: standardized virsh function API keywords
    @param snapshot: snapshot to revert to
    @return: CmdResult instance
    """
    return command("snapshot-revert %s %s" % (name, snapshot), **dargs)


def snapshot_delete(name, snapshot, **dargs):
    """
    Remove domain snapshot

    @param name: name of domain
    @param: dargs: standardized virsh function API keywords
    @param snapshot: snapshot to delete
    @return: CmdResult instance
    """
    return command("snapshot-delete %s %s" % (name, snapshot), **dargs)


def domblkinfo(vm_name, device, **dargs):
    """
    Get block device size info for a domain.

    @param: vm_name: VM's name or id,uuid.
    @param: device: device of VM.
    @param: dargs: standardized virsh function API keywords.
    @return: CmdResult object.
    """
    return command("domblkinfo %s %s" % (vm_name, device), **dargs)


def domblklist(name, options=None, **dargs):
    """
    Get domain devices.

    @param name: name of domain
    @param options: options of domblklist.
    @param dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    cmd = "domblklist %s" % name
    if options:
        cmd += " %s" % options

    return command(cmd, **dargs)


def cpu_stats(name, options, **dargs):
    """
    Display per-CPU and total statistics about domain's CPUs

    @param name: name of domain
    @param options: options of cpu_stats
    @param dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    cmd = "cpu-stats %s" % name
    if options:
        cmd += " %s" % options

    return command(cmd, **dargs)


def change_media(name, device, options, **dargs):
    """
    Change media of CD or floppy drive.

    @param: name: VM's name.
    @param: path: Fully-qualified path or target of disk device
    @param: options: command change_media options.
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    cmd = "change-media %s %s " % (name, device)
    if options:
        cmd += " %s " % options
    return command(cmd, **dargs)


def cpu_compare(xml_file, **dargs):
    """
    Compare host CPU with a CPU described by an XML file

    @param xml_file: file containing an XML CPU description.
    @param dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    return command("cpu-compare %s" % xml_file, **dargs)


def cpu_baseline(xml_file, **dargs):
    """
    Compute baseline CPU for a set of given CPUs.

    @param xml_file: file containing an XML CPU description.
    @param dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    return command("cpu-baseline %s" % xml_file, **dargs)


def numatune(name, mode=None, nodeset=None, options=None, **dargs):
    """
    Set or get a domain's numa parameters
    @param name: name of domain
    @param options: options may be live, config and current
    @param dargs: standardized virsh function API keywords
    @return: CmdResult instance
    """
    cmd = "numatune %s" % name
    if options:
        cmd += " --%s" % options
    if mode:
        cmd += " --mode %s" % mode
    if nodeset:
        cmd += " --nodeset %s" % nodeset

    return command(cmd, **dargs)


def ttyconsole(name, **dargs):
    """
    Print tty console device.

    @param name: name, uuid or id of domain
    @return: CmdResult instance
    """
    return command("ttyconsole %s" % name, **dargs)

def nodedev_dumpxml(name, options="", to_file=None, **dargs):
    """
    Do dumpxml for node device.

    @param name: the name of device.
    @param options: extra options to nodedev-dumpxml cmd.
    @param to_file: optional file to write XML output to.

    @return: Cmdobject of virsh nodedev-dumpxml.
    """
    cmd = ('nodedev-dumpxml %s %s' % (name, options))
    result = command(cmd, **dargs)
    if to_file is not None:
        result_file = open(to_file, 'w')
        result_file.write(result.stdout.strip())
        result_file.close()

    return result

def connect(connect_uri="", options="", **dargs):
    """
    Run a connect command to the uri.

    @param connect_uri: target uri connect to.
    @param: options: options to pass to connect command
    @return: CmdResult object.
    """
    return command("connect %s %s" % (connect_uri, options), **dargs)

def domif_setlink(name, interface, state, options=None, **dargs):
    """
    Set network interface stats for a running domain.

    @param: name: Name of domain
    @param: interface: interface device
    @param: state: new state of the device  up or down
    @param: options: command options.
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd = "domif-setlink %s %s %s " % (name, interface, state)
    if options:
        cmd += " %s" % options

    return command(cmd, **dargs)

def domif_getlink(name, interface, options=None, **dargs):
    """
    Get network interface stats for a running domain.

    @param: name: Name of domain
    @param: interface: interface device
    @param: options: command options.
    @param: dargs: standardized virsh function API keywords
    @return: domif state
    """
    cmd = "domif-getlink %s %s " % (name, interface)
    if options:
        cmd += " %s" % options

    return command(cmd, **dargs)

def nodedev_list(options="", **dargs):
    """
    List the node devices.

    @return: CmdResult object.
    """
    cmd = "nodedev-list %s" % (options)
    CmdResult = command(cmd, **dargs)

    return CmdResult


def nodedev_detach(name, options="", **dargs):
    """
    Detach node device from host.

    @return: cmdresult object.
    """
    cmd = ("nodedev-detach --device %s %s" % (name, options))
    CmdResult = command(cmd, **dargs)

    return CmdResult


def nodedev_dettach(name, options="", **dargs):
    """
    Detach node device from host.

    @return: nodedev_detach(name).
    """
    return nodedev_detach(name, options, **dargs)


def nodedev_reattach(name, options="", **dargs):
    """
    If node device is detached, this action will
    reattach it to its device driver.

    @return: cmdresult object.
    """
    cmd = ("nodedev-reattach --device %s %s" % (name, options))
    CmdResult = command(cmd, **dargs)

    return CmdResult


def vcpucount(name, options, **dargs):
    """
    Get the vcpu count of guest.

    @param name: name of domain.
    @param options: options for vcpucoutn command.
    @return: CmdResult object.
    """
    cmd = "vcpucount %s %s" % (name, options)
    return command(cmd, **dargs)
