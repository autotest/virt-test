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
import aexpect, propcan

# list of symbol names NOT to wrap as Virsh class methods
# Everything else from globals() will become a method of Virsh class
NOCLOSE = globals().keys() + [
    'NOCLOSE', 'SCREENSHOT_ERROR_COUNT', 'VIRSH_COMMAND_CACHE',
    'VIRSH_EXEC', 'VirshBase', 'VirshClosure', 'VirshSession', 'Virsh',
    'VirshPersistent',
]

# Needs to be in-scope for Virsh* class screenshot method and module function
SCREENSHOT_ERROR_COUNT = 0

# Cache of virsh commands, used by has_help_command() and help_command()
VIRSH_COMMAND_CACHE = None

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
        super(VirshBase, self).__init__(init_dict)


    def set_ignore_status(self, ignore_status):
        """
        Enforce setting ignore_status as a boolean
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
                logging.debug("Virsh debugging enabled")
            # current and desired could both be True
            if current_setting and not desired_setting:
                self.dict_set('debug', False)
                logging.debug("Virsh debugging disabled")


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
                 prompt=r"virsh\s*\#\s*"):
        """
        Initialize virsh session server, or client if id set.

        @param: virsh_exec: path to virsh executable
        @param: uri: uri of libvirt instance to connect to
        @param: id: ID of an already running server, if accessing a running
                server, or None if starting a new one.
        @param prompt: Regular expression describing the shell's prompt line.
        """

        self.uri = uri

        if self.uri:
            virsh_exec += " -c '%s'" % self.uri

        # aexpect tries to auto close session because no clients connected yet
        aexpect.ShellSession.__init__(self, virsh_exec, a_id, prompt=prompt,
                                      auto_close=False)
        # fail if libvirtd is not running
        if self.cmd_status('list', timeout=10) != 0:
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
        super(Virsh, self).__init__(*args, **dargs)
        # Define the instance callables from the contents of this module
        # to avoid using class methods and hand-written aliases
        for sym, ref in globals().items():
            if sym not in NOCLOSE and callable(ref):
                # Adding methods, not properties, so avoid special __slots__
                # handling.  __getattribute__ will still find these.
                self.super_set(sym, VirshClosure(ref, self))


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


    def close_session(self):
        """
        If a persistent session exists, close it down.
        """
        try:
            session_id = self.dict_get('session_id')
            if session_id:
                try:
                    existing = VirshSession(a_id=session_id)
                except aexpect.ShellStatusError:
                    # session was already closed
                    return
                if existing.is_alive():
                    # try nicely first
                    existing.close()
                    if existing.is_alive():
                        # Be mean, incase it's hung
                        existing.close(sig=signal.SIGTERM)
                    # Keep count:
                    self.__class__.SESSION_COUNTER -= 1
        except KeyError:
            # Allow other exceptions to be raised
            pass


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
        # Use existing session only if uri is the same
        if session.uri is not uri:
            # Invalidate session for this command
            if debug:
                logging.debug("VirshPersistent instance not using persistant "
                              " session for command %s with different uri %s "
                              " (persistant uri is %s)", cmd, uri, session.uri)
                session = None
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
    Prints the vcpuinfo of a given domain.

    @param: vm_name: name of domain
    @param: dargs: standardized virsh function API keywords
    @return: standard output from command
    """

    cmd_vcpuinfo = "vcpuinfo %s" % vm_name
    return command(cmd_vcpuinfo, **dargs).stdout.strip()


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
    @return: standard output from command
    """
    return command("domstate %s" % name, **dargs).stdout.strip()


def domid(name, **dargs):
    """
    Return VM's ID.

    @param name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: standard output from command
    """
    return command("domid %s" % (name), **dargs).stdout.strip()


def dominfo(name, **dargs):
    """
    Return the VM information.

    @param: dargs: standardized virsh function API keywords
    @return: standard output from command
    """
    return command("dominfo %s" % (name), **dargs).stdout.strip()


def domuuid(name, **dargs):
    """
    Return the Converted domain name or id to the domain UUID.

    @param name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: standard output from command
    """
    return command("domuuid %s" % name, **dargs).stdout.strip()


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


def dumpxml(name, to_file="", **dargs):
    """
    Return the domain information as an XML dump.

    @param: name: VM name
    @param: to_file: optional file to write XML output to
    @param: dargs: standardized virsh function API keywords
    @return: standard output from command
    """
    dargs['ignore_status'] = True
    if to_file:
        cmd = "dumpxml %s > %s" % (name, to_file)
    else:
        cmd = "dumpxml %s" % name
    result = command(cmd, **dargs)
    if result.exit_status:
        raise error.CmdError(cmd, result,
                                 "Virsh dumpxml returned non-zero exit status")
    return result.stdout.strip()


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
        state = domstate(name, **dargs)
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
    @return: True operation was successful
    """
    dargs['ignore_status'] = False
    try:
        command("suspend %s" % (name), **dargs)
        if domstate(name, **dargs) == 'paused':
            logging.debug("Suspended VM %s", name)
            return True
        else:
            return False
    except error.CmdError, detail:
        logging.error("Suspending VM %s failed:\n%s", name, detail)
        return False


def resume(name, **dargs):
    """
    True on successful moving domain out of suspend

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: True operation was successful
    """
    dargs['ignore_status'] = False
    try:
        command("resume %s" % (name), **dargs)
        if is_alive(name, **dargs):
            logging.debug("Resumed VM %s", name)
            return True
        else:
            return False
    except error.CmdError, detail:
        logging.error("Resume VM %s failed:\n%s", name, detail)
        return False


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
    @return: True operation was successful
    """
    if is_alive(name, **dargs):
        return True
    dargs['ignore_status'] = False
    try:
        command("start %s" % (name), **dargs)
        return True
    except error.CmdError, detail:
        logging.error("Start VM %s failed:\n%s", name, detail)
        return False


def shutdown(name, **dargs):
    """
    True on successful domain shutdown.

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: True operation was successful
    """
    if domstate(name, **dargs) == 'shut off':
        return True
    dargs['ignore_status'] = False
    try:
        command("shutdown %s" % (name), **dargs)
        return True
    except error.CmdError, detail:
        logging.error("Shutdown VM %s failed:\n%s", name, detail)
        return False


def destroy(name, **dargs):
    """
    True on successful domain destruction

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: True operation was successful
    """
    if domstate(name, **dargs) == 'shut off':
        return True
    dargs['ignore_status'] = False
    try:
        command("destroy %s" % (name), **dargs)
        return True
    except error.CmdError, detail:
        logging.error("Destroy VM %s failed:\n%s", name, detail)
        return False


def define(xml_path, **dargs):
    """
    Return True on successful domain define.

    @param: xml_path: XML file path
    @param: dargs: standardized virsh function API keywords
    @return: True operation was successful
    """
    dargs['ignore_status'] = False
    cmd = "define --file %s" % xml_path
    logging.debug("Define VM from %s", xml_path)
    return command(cmd, **dargs)


def undefine(name, **dargs):
    """
    Return True on successful domain undefine (after shutdown/destroy).

    @param: name: VM name
    @param: dargs: standardized virsh function API keywords
    @return: True operation was successful
    """
    dargs['ignore_status'] = False
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


def net_create(xml_file, extra="", **dargs):
    """
    Create network from a XML file.

    @param: xml_file: xml defining network
    @param: extra: extra parameters to pass to command
    @param: options: options to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd = "net-create --file %s %s" % (xml_file, extra)
    return command(cmd, **dargs)


def net_list(options, extra="", **dargs):
    """
    List networks on host.

    @param: extra: extra parameters to pass to command
    @param: options: options to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd = "net-list %s %s" % (options, extra)
    return command(cmd, **dargs)


def net_destroy(name, extra="", **dargs):
    """
    Destroy actived network on host.

    @param: name: name of guest
    @param: extra: extra string to pass to command
    @param: dargs: standardized virsh function API keywords
    @return: CmdResult object
    """
    cmd = "net-destroy --network %s %s" % (name, extra)
    return command(cmd, **dargs)


def pool_info(name, **dargs):
    """
    Returns basic information about the storage pool.

    @param: name: name of pool
    @param: dargs: standardized virsh function API keywords
    """
    cmd = "pool-info %s" % name
    dargs['ignore_status'] = False
    try:
        command(cmd, **dargs)
        return True
    except error.CmdError, detail:
        logging.error("Pool %s doesn't exist:\n%s", name, detail)
        return False


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


def help_command(options='', cache=False, **dargs):
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
        cmd = 'help'
        if options:
            cmd += (' ' + options)
        regx = re.compile(r"\s+([a-zA-Z0-9-]+)\s+")
        for line in command(cmd, **dargs).stdout.strip().splitlines():
            mobj = regx.search(line)
            if mobj:
                VIRSH_COMMAND_CACHE.append(mobj.group(1))
    # Prevent accidental modification of cache itself
    return list(VIRSH_COMMAND_CACHE)


def has_help_command(cmd, options='', **dargs):
    """
    String match on cmd in help output command list

    @param: cmd: Name of command to look for
    @param: options: Additional options to send to help command
    @param: dargs: standardized virsh function API keywords
    @return: True/False
    """
    return bool(help_command(options, cache=True, **dargs).count(cmd))


def has_command_help_match(cmd, regex, **dargs):
    """
    Regex search on subcommand help output

    @param: cmd: Name of command to match help output
    @param: regex: regular expression string to match
    @param: dargs: standardized virsh function API keywords
    @return: re match object
    """
    command_help_output = command("help %s" % cmd, **dargs).stdout.strip()
    return re.search(regex, command_help_output)


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
