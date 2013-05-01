#!/usr/bin/python
"""
A class and functions used for running and controlling child processes.

@copyright: 2008-2009 Red Hat Inc.
"""

import os, sys, pty, select, termios, fcntl


# The following helper functions are shared by the server and the client.

def _lock(filename):
    if not os.path.exists(filename):
        open(filename, "w").close()
    fd = os.open(filename, os.O_RDWR)
    fcntl.lockf(fd, fcntl.LOCK_EX)
    return fd


def _unlock(fd):
    fcntl.lockf(fd, fcntl.LOCK_UN)
    os.close(fd)


def _locked(filename):
    try:
        fd = os.open(filename, os.O_RDWR)
    except:
        return False
    try:
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except:
        os.close(fd)
        return True
    fcntl.lockf(fd, fcntl.LOCK_UN)
    os.close(fd)
    return False


def _wait(filename):
    fd = _lock(filename)
    _unlock(fd)


def _get_filenames(base_dir, id):
    return [os.path.join(base_dir, s + id) for s in
            "shell-pid-", "status-", "output-", "inpipe-",
            "lock-server-running-", "lock-client-starting-"]


def _get_reader_filename(base_dir, id, reader):
    return os.path.join(base_dir, "outpipe-%s-%s" % (reader, id))


# The following is the server part of the module.

if __name__ == "__main__":
    id = sys.stdin.readline().strip()
    echo = sys.stdin.readline().strip() == "True"
    readers = sys.stdin.readline().strip().split(",")
    command = sys.stdin.readline().strip() + " && echo %s > /dev/null" % id

    # Define filenames to be used for communication
    base_dir = "/tmp/kvm_spawn"
    (shell_pid_filename,
     status_filename,
     output_filename,
     inpipe_filename,
     lock_server_running_filename,
     lock_client_starting_filename) = _get_filenames(base_dir, id)

    # Populate the reader filenames list
    reader_filenames = [_get_reader_filename(base_dir, id, reader)
                        for reader in readers]

    # Set $TERM = dumb
    os.putenv("TERM", "dumb")

    (shell_pid, shell_fd) = pty.fork()
    if shell_pid == 0:
        # Child process: run the command in a subshell
        os.execv("/bin/sh", ["/bin/sh", "-c", command])
    else:
        # Parent process
        lock_server_running = _lock(lock_server_running_filename)

        # Set terminal echo on/off and disable pre- and post-processing
        attr = termios.tcgetattr(shell_fd)
        attr[0] &= ~termios.INLCR
        attr[0] &= ~termios.ICRNL
        attr[0] &= ~termios.IGNCR
        attr[1] &= ~termios.OPOST
        if echo:
            attr[3] |= termios.ECHO
        else:
            attr[3] &= ~termios.ECHO
        termios.tcsetattr(shell_fd, termios.TCSANOW, attr)

        # Open output file
        output_file = open(output_filename, "w")
        # Open input pipe
        os.mkfifo(inpipe_filename)
        inpipe_fd = os.open(inpipe_filename, os.O_RDWR)
        # Open output pipes (readers)
        reader_fds = []
        for filename in reader_filenames:
            os.mkfifo(filename)
            reader_fds.append(os.open(filename, os.O_RDWR))

        # Write shell PID to file
        file = open(shell_pid_filename, "w")
        file.write(str(shell_pid))
        file.close()

        # Print something to stdout so the client can start working
        print "Server %s ready" % id
        sys.stdout.flush()

        # Initialize buffers
        buffers = ["" for reader in readers]

        # Read from child and write to files/pipes
        while True:
            check_termination = False
            # Make a list of reader pipes whose buffers are not empty
            fds = [fd for (i, fd) in enumerate(reader_fds) if buffers[i]]
            # Wait until there's something to do
            r, w, x = select.select([shell_fd, inpipe_fd], fds, [], 0.5)
            # If a reader pipe is ready for writing --
            for (i, fd) in enumerate(reader_fds):
                if fd in w:
                    bytes_written = os.write(fd, buffers[i])
                    buffers[i] = buffers[i][bytes_written:]
            # If there's data to read from the child process --
            if shell_fd in r:
                try:
                    data = os.read(shell_fd, 16384)
                except OSError:
                    data = ""
                if not data:
                    check_termination = True
                # Remove carriage returns from the data -- they often cause
                # trouble and are normally not needed
                data = data.replace("\r", "")
                output_file.write(data)
                output_file.flush()
                for i in range(len(readers)):
                    buffers[i] += data
            # If os.read() raised an exception or there was nothing to read --
            if check_termination or shell_fd not in r:
                pid, status = os.waitpid(shell_pid, os.WNOHANG)
                if pid:
                    status = os.WEXITSTATUS(status)
                    break
            # If there's data to read from the client --
            if inpipe_fd in r:
                data = os.read(inpipe_fd, 1024)
                os.write(shell_fd, data)

        # Write the exit status to a file
        file = open(status_filename, "w")
        file.write(str(status))
        file.close()

        # Wait for the client to finish initializing
        _wait(lock_client_starting_filename)

        # Delete FIFOs
        for filename in reader_filenames + [inpipe_filename]:
            try:
                os.unlink(filename)
            except OSError:
                pass

        # Close all files and pipes
        output_file.close()
        os.close(inpipe_fd)
        for fd in reader_fds:
            os.close(fd)

        _unlock(lock_server_running)
        exit(0)


# The following is the client part of the module.

import subprocess, time, signal, re, threading, logging
import virt_utils


class ExpectError(Exception):
    def __init__(self, patterns, output):
        Exception.__init__(self, patterns, output)
        self.patterns = patterns
        self.output = output

    def _pattern_str(self):
        if len(self.patterns) == 1:
            return "pattern %r" % self.patterns[0]
        else:
            return "patterns %r" % self.patterns

    def __str__(self):
        return ("Unknown error occurred while looking for %s    (output: %r)" %
                (self._pattern_str(), self.output))


class ExpectTimeoutError(ExpectError):
    def __str__(self):
        return ("Timeout expired while looking for %s    (output: %r)" %
                (self._pattern_str(), self.output))


class ExpectProcessTerminatedError(ExpectError):
    def __init__(self, patterns, status, output):
        ExpectError.__init__(self, patterns, output)
        self.status = status

    def __str__(self):
        return ("Process terminated while looking for %s    "
                "(status: %s,    output: %r)" % (self._pattern_str(),
                                                 self.status, self.output))


class ShellError(Exception):
    def __init__(self, cmd, output):
        Exception.__init__(self, cmd, output)
        self.cmd = cmd
        self.output = output

    def __str__(self):
        return ("Could not execute shell command %r    (output: %r)" %
                (self.cmd, self.output))


class ShellTimeoutError(ShellError):
    def __str__(self):
        return ("Timeout expired while waiting for shell command to "
                "complete: %r    (output: %r)" % (self.cmd, self.output))


class ShellProcessTerminatedError(ShellError):
    # Raised when the shell process itself (e.g. ssh, netcat, telnet)
    # terminates unexpectedly
    def __init__(self, cmd, status, output):
        ShellError.__init__(self, cmd, output)
        self.status = status

    def __str__(self):
        return ("Shell process terminated while waiting for command to "
                "complete: %r    (status: %s,    output: %r)" %
                (self.cmd, self.status, self.output))


class ShellCmdError(ShellError):
    # Raised when a command executed in a shell terminates with a nonzero
    # exit code (status)
    def __init__(self, cmd, status, output):
        ShellError.__init__(self, cmd, output)
        self.status = status

    def __str__(self):
        return ("Shell command failed: %r    (status: %s,    output: %r)" %
                (self.cmd, self.status, self.output))


class ShellStatusError(ShellError):
    # Raised when the command's exit status cannot be obtained
    def __str__(self):
        return ("Could not get exit status of command: %r    (output: %r)" %
                (self.cmd, self.output))


def run_bg(command, termination_func=None, output_func=None, output_prefix="",
           timeout=1.0):
    """
    Run command as a subprocess.  Call output_func with each line of output
    from the subprocess (prefixed by output_prefix).  Call termination_func
    when the subprocess terminates.  Return when timeout expires or when the
    subprocess exits -- whichever occurs first.

    @brief: Run a subprocess in the background and collect its output and
            exit status.

    @param command: The shell command to execute
    @param termination_func: A function to call when the process terminates
            (should take an integer exit status parameter)
    @param output_func: A function to call with each line of output from
            the subprocess (should take a string parameter)
    @param output_prefix: A string to pre-pend to each line of the output,
            before passing it to stdout_func
    @param timeout: Time duration (in seconds) to wait for the subprocess to
            terminate before returning

    @return: A Tail object.
    """
    process = Tail(command=command,
                   termination_func=termination_func,
                   output_func=output_func,
                   output_prefix=output_prefix)

    end_time = time.time() + timeout
    while time.time() < end_time and process.is_alive():
        time.sleep(0.1)

    return process


def run_fg(command, output_func=None, output_prefix="", timeout=1.0):
    """
    Run command as a subprocess.  Call output_func with each line of output
    from the subprocess (prefixed by prefix).  Return when timeout expires or
    when the subprocess exits -- whichever occurs first.  If timeout expires
    and the subprocess is still running, kill it before returning.

    @brief: Run a subprocess in the foreground and collect its output and
            exit status.

    @param command: The shell command to execute
    @param output_func: A function to call with each line of output from
            the subprocess (should take a string parameter)
    @param output_prefix: A string to pre-pend to each line of the output,
            before passing it to stdout_func
    @param timeout: Time duration (in seconds) to wait for the subprocess to
            terminate before killing it and returning

    @return: A 2-tuple containing the exit status of the process and its
            STDOUT/STDERR output.  If timeout expires before the process
            terminates, the returned status is None.
    """
    process = run_bg(command, None, output_func, output_prefix, timeout)
    output = process.get_output()
    if process.is_alive():
        status = None
    else:
        status = process.get_status()
    process.close()
    return (status, output)


class Spawn:
    """
    This class is used for spawning and controlling a child process.

    A new instance of this class can either run a new server (a small Python
    program that reads output from the child process and reports it to the
    client and to a text file) or attach to an already running server.
    When a server is started it runs the child process.
    The server writes output from the child's STDOUT and STDERR to a text file.
    The text file can be accessed at any time using get_output().
    In addition, the server opens as many pipes as requested by the client and
    writes the output to them.
    The pipes are requested and accessed by classes derived from Spawn.
    These pipes are referred to as "readers".
    The server also receives input from the client and sends it to the child
    process.
    An instance of this class can be pickled.  Every derived class is
    responsible for restoring its own state by properly defining
    __getinitargs__().

    The first named pipe is used by _tail(), a function that runs in the
    background and reports new output from the child as it is produced.
    The second named pipe is used by a set of functions that read and parse
    output as requested by the user in an interactive manner, similar to
    pexpect.
    When unpickled it automatically
    resumes _tail() if needed.
    """

    def __init__(self, command=None, id=None, auto_close=False, echo=False,
                 linesep="\n"):
        """
        Initialize the class and run command as a child process.

        @param command: Command to run, or None if accessing an already running
                server.
        @param id: ID of an already running server, if accessing a running
                server, or None if starting a new one.
        @param auto_close: If True, close() the instance automatically when its
                reference count drops to zero (default False).
        @param echo: Boolean indicating whether echo should be initially
                enabled for the pseudo terminal running the subprocess.  This
                parameter has an effect only when starting a new server.
        @param linesep: Line separator to be appended to strings sent to the
                child process by sendline().
        """
        self.id = id or virt_utils.generate_random_string(8)

        # Define filenames for communication with server
        base_dir = "/tmp/kvm_spawn"
        try:
            os.makedirs(base_dir)
        except:
            pass
        (self.shell_pid_filename,
         self.status_filename,
         self.output_filename,
         self.inpipe_filename,
         self.lock_server_running_filename,
         self.lock_client_starting_filename) = _get_filenames(base_dir,
                                                              self.id)

        # Remember some attributes
        self.auto_close = auto_close
        self.echo = echo
        self.linesep = linesep

        # Make sure the 'readers' and 'close_hooks' attributes exist
        if not hasattr(self, "readers"):
            self.readers = []
        if not hasattr(self, "close_hooks"):
            self.close_hooks = []

        # Define the reader filenames
        self.reader_filenames = dict(
            (reader, _get_reader_filename(base_dir, self.id, reader))
            for reader in self.readers)

        # Let the server know a client intends to open some pipes;
        # if the executed command terminates quickly, the server will wait for
        # the client to release the lock before exiting
        lock_client_starting = _lock(self.lock_client_starting_filename)

        # Start the server (which runs the command)
        if command:
            sub = subprocess.Popen("%s %s" % (sys.executable, __file__),
                                   shell=True,
                                   stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
            # Send parameters to the server
            sub.stdin.write("%s\n" % self.id)
            sub.stdin.write("%s\n" % echo)
            sub.stdin.write("%s\n" % ",".join(self.readers))
            sub.stdin.write("%s\n" % command)
            # Wait for the server to complete its initialization
            while not "Server %s ready" % self.id in sub.stdout.readline():
                pass

        # Open the reading pipes
        self.reader_fds = {}
        try:
            assert(_locked(self.lock_server_running_filename))
            for reader, filename in self.reader_filenames.items():
                self.reader_fds[reader] = os.open(filename, os.O_RDONLY)
        except:
            pass

        # Allow the server to continue
        _unlock(lock_client_starting)


    # The following two functions are defined to make sure the state is set
    # exclusively by the constructor call as specified in __getinitargs__().

    def __getstate__(self):
        pass


    def __setstate__(self, state):
        pass


    def __getinitargs__(self):
        # Save some information when pickling -- will be passed to the
        # constructor upon unpickling
        return (None, self.id, self.auto_close, self.echo, self.linesep)


    def __del__(self):
        if self.auto_close:
            self.close()


    def _add_reader(self, reader):
        """
        Add a reader whose file descriptor can be obtained with _get_fd().
        Should be called before __init__().  Intended for use by derived
        classes.

        @param reader: The name of the reader.
        """
        if not hasattr(self, "readers"):
            self.readers = []
        self.readers.append(reader)


    def _add_close_hook(self, hook):
        """
        Add a close hook function to be called when close() is called.
        The function will be called after the process terminates but before
        final cleanup.  Intended for use by derived classes.

        @param hook: The hook function.
        """
        if not hasattr(self, "close_hooks"):
            self.close_hooks = []
        self.close_hooks.append(hook)


    def _get_fd(self, reader):
        """
        Return an open file descriptor corresponding to the specified reader
        pipe.  If no such reader exists, or the pipe could not be opened,
        return None.  Intended for use by derived classes.

        @param reader: The name of the reader.
        """
        return self.reader_fds.get(reader)


    def get_id(self):
        """
        Return the instance's id attribute, which may be used to access the
        process in the future.
        """
        return self.id


    def get_pid(self):
        """
        Return the PID of the process.

        Note: this may be the PID of the shell process running the user given
        command.
        """
        try:
            file = open(self.shell_pid_filename, "r")
            pid = int(file.read())
            file.close()
            return pid
        except:
            return None


    def get_status(self):
        """
        Wait for the process to exit and return its exit status, or None
        if the exit status is not available.
        """
        _wait(self.lock_server_running_filename)
        try:
            file = open(self.status_filename, "r")
            status = int(file.read())
            file.close()
            return status
        except:
            return None


    def get_output(self):
        """
        Return the STDOUT and STDERR output of the process so far.
        """
        try:
            file = open(self.output_filename, "r")
            output = file.read()
            file.close()
            return output
        except:
            return ""


    def is_alive(self):
        """
        Return True if the process is running.
        """
        return _locked(self.lock_server_running_filename)


    def close(self, sig=signal.SIGKILL):
        """
        Kill the child process if it's alive and remove temporary files.

        @param sig: The signal to send the process when attempting to kill it.
        """
        # Kill it if it's alive
        if self.is_alive():
            virt_utils.kill_process_tree(self.get_pid(), sig)
        # Wait for the server to exit
        _wait(self.lock_server_running_filename)
        # Call all cleanup routines
        for hook in self.close_hooks:
            hook(self)
        # Close reader file descriptors
        for fd in self.reader_fds.values():
            try:
                os.close(fd)
            except:
                pass
        self.reader_fds = {}
        # Remove all used files
        for filename in (_get_filenames("/tmp/kvm_spawn", self.id) +
                         self.reader_filenames.values()):
            try:
                os.unlink(filename)
            except OSError:
                pass


    def set_linesep(self, linesep):
        """
        Sets the line separator string (usually "\\n").

        @param linesep: Line separator string.
        """
        self.linesep = linesep


    def send(self, str=""):
        """
        Send a string to the child process.

        @param str: String to send to the child process.
        """
        try:
            fd = os.open(self.inpipe_filename, os.O_RDWR)
            os.write(fd, str)
            os.close(fd)
        except:
            pass


    def sendline(self, str=""):
        """
        Send a string followed by a line separator to the child process.

        @param str: String to send to the child process.
        """
        self.send(str + self.linesep)


_thread_kill_requested = False

def kill_tail_threads():
    """
    Kill all Tail threads.

    After calling this function no new threads should be started.
    """
    global _thread_kill_requested
    _thread_kill_requested = True
    for t in threading.enumerate():
        if hasattr(t, "name") and t.name.startswith("tail_thread"):
            t.join(10)
    _thread_kill_requested = False


class Tail(Spawn):
    """
    This class runs a child process in the background and sends its output in
    real time, line-by-line, to a callback function.

    See Spawn's docstring.

    This class uses a single pipe reader to read data in real time from the
    child process and report it to a given callback function.
    When the child process exits, its exit status is reported to an additional
    callback function.

    When this class is unpickled, it automatically resumes reporting output.
    """

    def __init__(self, command=None, id=None, auto_close=False, echo=False,
                 linesep="\n", termination_func=None, termination_params=(),
                 output_func=None, output_params=(), output_prefix=""):
        """
        Initialize the class and run command as a child process.

        @param command: Command to run, or None if accessing an already running
                server.
        @param id: ID of an already running server, if accessing a running
                server, or None if starting a new one.
        @param auto_close: If True, close() the instance automatically when its
                reference count drops to zero (default False).
        @param echo: Boolean indicating whether echo should be initially
                enabled for the pseudo terminal running the subprocess.  This
                parameter has an effect only when starting a new server.
        @param linesep: Line separator to be appended to strings sent to the
                child process by sendline().
        @param termination_func: Function to call when the process exits.  The
                function must accept a single exit status parameter.
        @param termination_params: Parameters to send to termination_func
                before the exit status.
        @param output_func: Function to call whenever a line of output is
                available from the STDOUT or STDERR streams of the process.
                The function must accept a single string parameter.  The string
                does not include the final newline.
        @param output_params: Parameters to send to output_func before the
                output line.
        @param output_prefix: String to prepend to lines sent to output_func.
        """
        # Add a reader and a close hook
        self._add_reader("tail")
        self._add_close_hook(Tail._join_thread)

        # Init the superclass
        Spawn.__init__(self, command, id, auto_close, echo, linesep)

        # Remember some attributes
        self.termination_func = termination_func
        self.termination_params = termination_params
        self.output_func = output_func
        self.output_params = output_params
        self.output_prefix = output_prefix

        # Start the thread in the background
        self.tail_thread = None
        if termination_func or output_func:
            self._start_thread()


    def __getinitargs__(self):
        return Spawn.__getinitargs__(self) + (self.termination_func,
                                              self.termination_params,
                                              self.output_func,
                                              self.output_params,
                                              self.output_prefix)


    def set_termination_func(self, termination_func):
        """
        Set the termination_func attribute. See __init__() for details.

        @param termination_func: Function to call when the process terminates.
                Must take a single parameter -- the exit status.
        """
        self.termination_func = termination_func
        if termination_func and not self.tail_thread:
            self._start_thread()


    def set_termination_params(self, termination_params):
        """
        Set the termination_params attribute. See __init__() for details.

        @param termination_params: Parameters to send to termination_func
                before the exit status.
        """
        self.termination_params = termination_params


    def set_output_func(self, output_func):
        """
        Set the output_func attribute. See __init__() for details.

        @param output_func: Function to call for each line of STDOUT/STDERR
                output from the process.  Must take a single string parameter.
        """
        self.output_func = output_func
        if output_func and not self.tail_thread:
            self._start_thread()


    def set_output_params(self, output_params):
        """
        Set the output_params attribute. See __init__() for details.

        @param output_params: Parameters to send to output_func before the
                output line.
        """
        self.output_params = output_params


    def set_output_prefix(self, output_prefix):
        """
        Set the output_prefix attribute. See __init__() for details.

        @param output_prefix: String to pre-pend to each line sent to
                output_func (see set_output_callback()).
        """
        self.output_prefix = output_prefix


    def _tail(self):
        def print_line(text):
            # Pre-pend prefix and remove trailing whitespace
            text = self.output_prefix + text.rstrip()
            # Pass text to output_func
            try:
                params = self.output_params + (text,)
                self.output_func(*params)
            except TypeError:
                pass

        try:
            fd = self._get_fd("tail")
            buffer = ""
            while True:
                global _thread_kill_requested
                if _thread_kill_requested:
                    return
                try:
                    # See if there's any data to read from the pipe
                    r, w, x = select.select([fd], [], [], 0.05)
                except:
                    break
                if fd in r:
                    # Some data is available; read it
                    new_data = os.read(fd, 1024)
                    if not new_data:
                        break
                    buffer += new_data
                    # Send the output to output_func line by line
                    # (except for the last line)
                    if self.output_func:
                        lines = buffer.split("\n")
                        for line in lines[:-1]:
                            print_line(line)
                    # Leave only the last line
                    last_newline_index = buffer.rfind("\n")
                    buffer = buffer[last_newline_index+1:]
                else:
                    # No output is available right now; flush the buffer
                    if buffer:
                        print_line(buffer)
                        buffer = ""
            # The process terminated; print any remaining output
            if buffer:
                print_line(buffer)
            # Get the exit status, print it and send it to termination_func
            status = self.get_status()
            if status is None:
                return
            print_line("(Process terminated with status %s)" % status)
            try:
                params = self.termination_params + (status,)
                self.termination_func(*params)
            except TypeError:
                pass
        finally:
            self.tail_thread = None


    def _start_thread(self):
        self.tail_thread = threading.Thread(target=self._tail,
                                            name="tail_thread_%s" % self.id)
        self.tail_thread.start()


    def _join_thread(self):
        # Wait for the tail thread to exit
        # (it's done this way because self.tail_thread may become None at any
        # time)
        t = self.tail_thread
        if t:
            t.join()


class Expect(Tail):
    """
    This class runs a child process in the background and provides expect-like
    services.

    It also provides all of Tail's functionality.
    """

    def __init__(self, command=None, id=None, auto_close=True, echo=False,
                 linesep="\n", termination_func=None, termination_params=(),
                 output_func=None, output_params=(), output_prefix=""):
        """
        Initialize the class and run command as a child process.

        @param command: Command to run, or None if accessing an already running
                server.
        @param id: ID of an already running server, if accessing a running
                server, or None if starting a new one.
        @param auto_close: If True, close() the instance automatically when its
                reference count drops to zero (default False).
        @param echo: Boolean indicating whether echo should be initially
                enabled for the pseudo terminal running the subprocess.  This
                parameter has an effect only when starting a new server.
        @param linesep: Line separator to be appended to strings sent to the
                child process by sendline().
        @param termination_func: Function to call when the process exits.  The
                function must accept a single exit status parameter.
        @param termination_params: Parameters to send to termination_func
                before the exit status.
        @param output_func: Function to call whenever a line of output is
                available from the STDOUT or STDERR streams of the process.
                The function must accept a single string parameter.  The string
                does not include the final newline.
        @param output_params: Parameters to send to output_func before the
                output line.
        @param output_prefix: String to prepend to lines sent to output_func.
        """
        # Add a reader
        self._add_reader("expect")

        # Init the superclass
        Tail.__init__(self, command, id, auto_close, echo, linesep,
                      termination_func, termination_params,
                      output_func, output_params, output_prefix)


    def __getinitargs__(self):
        return Tail.__getinitargs__(self)


    def read_nonblocking(self, timeout=None):
        """
        Read from child until there is nothing to read for timeout seconds.

        @param timeout: Time (seconds) to wait before we give up reading from
                the child process, or None to use the default value.
        """
        if timeout is None:
            timeout = 0.1
        fd = self._get_fd("expect")
        data = ""
        while True:
            try:
                r, w, x = select.select([fd], [], [], timeout)
            except:
                return data
            if fd in r:
                new_data = os.read(fd, 1024)
                if not new_data:
                    return data
                data += new_data
            else:
                return data


    def match_patterns(self, str, patterns):
        """
        Match str against a list of patterns.

        Return the index of the first pattern that matches a substring of str.
        None and empty strings in patterns are ignored.
        If no match is found, return None.

        @param patterns: List of strings (regular expression patterns).
        """
        for i in range(len(patterns)):
            if not patterns[i]:
                continue
            if re.search(patterns[i], str):
                return i


    def read_until_output_matches(self, patterns, filter=lambda x: x,
                                  timeout=60, internal_timeout=None,
                                  print_func=None):
        """
        Read using read_nonblocking until a match is found using match_patterns,
        or until timeout expires. Before attempting to search for a match, the
        data is filtered using the filter function provided.

        @brief: Read from child using read_nonblocking until a pattern
                matches.
        @param patterns: List of strings (regular expression patterns)
        @param filter: Function to apply to the data read from the child before
                attempting to match it against the patterns (should take and
                return a string)
        @param timeout: The duration (in seconds) to wait until a match is
                found
        @param internal_timeout: The timeout to pass to read_nonblocking
        @param print_func: A function to be used to print the data being read
                (should take a string parameter)
        @return: Tuple containing the match index and the data read so far
        @raise ExpectTimeoutError: Raised if timeout expires
        @raise ExpectProcessTerminatedError: Raised if the child process
                terminates while waiting for output
        @raise ExpectError: Raised if an unknown error occurs
        """
        fd = self._get_fd("expect")
        o = ""
        end_time = time.time() + timeout
        while True:
            try:
                r, w, x = select.select([fd], [], [],
                                        max(0, end_time - time.time()))
            except (select.error, TypeError):
                break
            if not r:
                raise ExpectTimeoutError(patterns, o)
            # Read data from child
            data = self.read_nonblocking(internal_timeout)
            if not data:
                break
            # Print it if necessary
            if print_func:
                for line in data.splitlines():
                    print_func(line)
            # Look for patterns
            o += data
            match = self.match_patterns(filter(o), patterns)
            if match is not None:
                return match, o

        # Check if the child has terminated
        if virt_utils.wait_for(lambda: not self.is_alive(), 5, 0, 0.1):
            raise ExpectProcessTerminatedError(patterns, self.get_status(), o)
        else:
            # This shouldn't happen
            raise ExpectError(patterns, o)


    def read_until_last_word_matches(self, patterns, timeout=60,
                                     internal_timeout=None, print_func=None):
        """
        Read using read_nonblocking until the last word of the output matches
        one of the patterns (using match_patterns), or until timeout expires.

        @param patterns: A list of strings (regular expression patterns)
        @param timeout: The duration (in seconds) to wait until a match is
                found
        @param internal_timeout: The timeout to pass to read_nonblocking
        @param print_func: A function to be used to print the data being read
                (should take a string parameter)
        @return: A tuple containing the match index and the data read so far
        @raise ExpectTimeoutError: Raised if timeout expires
        @raise ExpectProcessTerminatedError: Raised if the child process
                terminates while waiting for output
        @raise ExpectError: Raised if an unknown error occurs
        """
        def get_last_word(str):
            if str:
                return str.split()[-1]
            else:
                return ""

        return self.read_until_output_matches(patterns, get_last_word,
                                              timeout, internal_timeout,
                                              print_func)


    def read_until_last_line_matches(self, patterns, timeout=60,
                                     internal_timeout=None, print_func=None):
        """
        Read using read_nonblocking until the last non-empty line of the output
        matches one of the patterns (using match_patterns), or until timeout
        expires. Return a tuple containing the match index (or None if no match
        was found) and the data read so far.

        @brief: Read using read_nonblocking until the last non-empty line
                matches a pattern.

        @param patterns: A list of strings (regular expression patterns)
        @param timeout: The duration (in seconds) to wait until a match is
                found
        @param internal_timeout: The timeout to pass to read_nonblocking
        @param print_func: A function to be used to print the data being read
                (should take a string parameter)
        @return: A tuple containing the match index and the data read so far
        @raise ExpectTimeoutError: Raised if timeout expires
        @raise ExpectProcessTerminatedError: Raised if the child process
                terminates while waiting for output
        @raise ExpectError: Raised if an unknown error occurs
        """
        def get_last_nonempty_line(str):
            nonempty_lines = [l for l in str.splitlines() if l.strip()]
            if nonempty_lines:
                return nonempty_lines[-1]
            else:
                return ""

        return self.read_until_output_matches(patterns, get_last_nonempty_line,
                                              timeout, internal_timeout,
                                              print_func)


class ShellSession(Expect):
    """
    This class runs a child process in the background.  It it suited for
    processes that provide an interactive shell, such as SSH and Telnet.

    It provides all services of Expect and Tail.  In addition, it
    provides command running services, and a utility function to test the
    process for responsiveness.
    """

    def __init__(self, command=None, id=None, auto_close=True, echo=False,
                 linesep="\n", termination_func=None, termination_params=(),
                 output_func=None, output_params=(), output_prefix="",
                 prompt=r"[\#\$]\s*$", status_test_command="echo $?"):
        """
        Initialize the class and run command as a child process.

        @param command: Command to run, or None if accessing an already running
                server.
        @param id: ID of an already running server, if accessing a running
                server, or None if starting a new one.
        @param auto_close: If True, close() the instance automatically when its
                reference count drops to zero (default True).
        @param echo: Boolean indicating whether echo should be initially
                enabled for the pseudo terminal running the subprocess.  This
                parameter has an effect only when starting a new server.
        @param linesep: Line separator to be appended to strings sent to the
                child process by sendline().
        @param termination_func: Function to call when the process exits.  The
                function must accept a single exit status parameter.
        @param termination_params: Parameters to send to termination_func
                before the exit status.
        @param output_func: Function to call whenever a line of output is
                available from the STDOUT or STDERR streams of the process.
                The function must accept a single string parameter.  The string
                does not include the final newline.
        @param output_params: Parameters to send to output_func before the
                output line.
        @param output_prefix: String to prepend to lines sent to output_func.
        @param prompt: Regular expression describing the shell's prompt line.
        @param status_test_command: Command to be used for getting the last
                exit status of commands run inside the shell (used by
                cmd_status_output() and friends).
        """
        # Init the superclass
        Expect.__init__(self, command, id, auto_close, echo, linesep,
                        termination_func, termination_params,
                        output_func, output_params, output_prefix)

        # Remember some attributes
        self.prompt = prompt
        self.status_test_command = status_test_command


    def __getinitargs__(self):
        return Expect.__getinitargs__(self) + (self.prompt,
                                               self.status_test_command)


    def set_prompt(self, prompt):
        """
        Set the prompt attribute for later use by read_up_to_prompt.

        @param: String that describes the prompt contents.
        """
        self.prompt = prompt


    def set_status_test_command(self, status_test_command):
        """
        Set the command to be sent in order to get the last exit status.

        @param status_test_command: Command that will be sent to get the last
                exit status.
        """
        self.status_test_command = status_test_command


    def is_responsive(self, timeout=5.0):
        """
        Return True if the process responds to STDIN/terminal input.

        Send a newline to the child process (e.g. SSH or Telnet) and read some
        output using read_nonblocking().
        If all is OK, some output should be available (e.g. the shell prompt).
        In that case return True.  Otherwise return False.

        @param timeout: Time duration to wait before the process is considered
                unresponsive.
        """
        # Read all output that's waiting to be read, to make sure the output
        # we read next is in response to the newline sent
        self.read_nonblocking(timeout=0)
        # Send a newline
        self.sendline()
        # Wait up to timeout seconds for some output from the child
        end_time = time.time() + timeout
        while time.time() < end_time:
            time.sleep(0.5)
            if self.read_nonblocking(timeout=0).strip():
                return True
        # No output -- report unresponsive
        return False


    def read_up_to_prompt(self, timeout=60, internal_timeout=None,
                          print_func=None):
        """
        Read using read_nonblocking until the last non-empty line of the output
        matches the prompt regular expression set by set_prompt, or until
        timeout expires.

        @brief: Read using read_nonblocking until the last non-empty line
                matches the prompt.

        @param timeout: The duration (in seconds) to wait until a match is
                found
        @param internal_timeout: The timeout to pass to read_nonblocking
        @param print_func: A function to be used to print the data being
                read (should take a string parameter)

        @return: The data read so far
        @raise ExpectTimeoutError: Raised if timeout expires
        @raise ExpectProcessTerminatedError: Raised if the shell process
                terminates while waiting for output
        @raise ExpectError: Raised if an unknown error occurs
        """
        m, o = self.read_until_last_line_matches([self.prompt], timeout,
                                                 internal_timeout, print_func)
        return o


    def cmd_output(self, cmd, timeout=60, internal_timeout=None,
                   print_func=None):
        """
        Send a command and return its output.

        @param cmd: Command to send (must not contain newline characters)
        @param timeout: The duration (in seconds) to wait for the prompt to
                return
        @param internal_timeout: The timeout to pass to read_nonblocking
        @param print_func: A function to be used to print the data being read
                (should take a string parameter)

        @return: The output of cmd
        @raise ShellTimeoutError: Raised if timeout expires
        @raise ShellProcessTerminatedError: Raised if the shell process
                terminates while waiting for output
        @raise ShellError: Raised if an unknown error occurs
        """
        def remove_command_echo(str, cmd):
            if str and str.splitlines()[0] == cmd:
                str = "".join(str.splitlines(True)[1:])
            return str

        def remove_last_nonempty_line(str):
            return "".join(str.rstrip().splitlines(True)[:-1])

        logging.debug("Sending command: %s" % cmd)
        self.read_nonblocking(timeout=0)
        self.sendline(cmd)
        try:
            o = self.read_up_to_prompt(timeout, internal_timeout, print_func)
        except ExpectError, e:
            o = remove_command_echo(e.output, cmd)
            if isinstance(e, ExpectTimeoutError):
                raise ShellTimeoutError(cmd, o)
            elif isinstance(e, ExpectProcessTerminatedError):
                raise ShellProcessTerminatedError(cmd, e.status, o)
            else:
                raise ShellError(cmd, o)

        # Remove the echoed command and the final shell prompt
        return remove_last_nonempty_line(remove_command_echo(o, cmd))


    def cmd_status_output(self, cmd, timeout=60, internal_timeout=None,
                          print_func=None):
        """
        Send a command and return its exit status and output.

        @param cmd: Command to send (must not contain newline characters)
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
        o = self.cmd_output(cmd, timeout, internal_timeout, print_func)
        try:
            # Send the 'echo $?' (or equivalent) command to get the exit status
            s = self.cmd_output(self.status_test_command, 10, internal_timeout)
        except ShellError:
            raise ShellStatusError(cmd, o)

        # Get the first line consisting of digits only
        digit_lines = [l for l in s.splitlines() if l.strip().isdigit()]
        if digit_lines:
            return int(digit_lines[0].strip()), o
        else:
            raise ShellStatusError(cmd, o)


    def cmd_status(self, cmd, timeout=60, internal_timeout=None,
                   print_func=None):
        """
        Send a command and return its exit status.

        @param cmd: Command to send (must not contain newline characters)
        @param timeout: The duration (in seconds) to wait for the prompt to
                return
        @param internal_timeout: The timeout to pass to read_nonblocking
        @param print_func: A function to be used to print the data being read
                (should take a string parameter)

        @return: The exit status of cmd
        @raise ShellTimeoutError: Raised if timeout expires
        @raise ShellProcessTerminatedError: Raised if the shell process
                terminates while waiting for output
        @raise ShellStatusError: Raised if the exit status cannot be obtained
        @raise ShellError: Raised if an unknown error occurs
        """
        s, o = self.cmd_status_output(cmd, timeout, internal_timeout,
                                      print_func)
        return s


    def cmd(self, cmd, timeout=60, internal_timeout=None, print_func=None):
        """
        Send a command and return its output. If the command's exit status is
        nonzero, raise an exception.

        @param cmd: Command to send (must not contain newline characters)
        @param timeout: The duration (in seconds) to wait for the prompt to
                return
        @param internal_timeout: The timeout to pass to read_nonblocking
        @param print_func: A function to be used to print the data being read
                (should take a string parameter)

        @return: The output of cmd
        @raise ShellTimeoutError: Raised if timeout expires
        @raise ShellProcessTerminatedError: Raised if the shell process
                terminates while waiting for output
        @raise ShellError: Raised if the exit status cannot be obtained or if
                an unknown error occurs
        @raise ShellStatusError: Raised if the exit status cannot be obtained
        @raise ShellError: Raised if an unknown error occurs
        @raise ShellCmdError: Raised if the exit status is nonzero
        """
        s, o = self.cmd_status_output(cmd, timeout, internal_timeout,
                                      print_func)
        if s != 0:
            raise ShellCmdError(cmd, s, o)
        return o


    def get_command_output(self, cmd, timeout=60, internal_timeout=None,
                           print_func=None):
        """
        Alias for cmd_output() for backward compatibility.
        """
        return self.cmd_output(cmd, timeout, internal_timeout, print_func)


    def get_command_status_output(self, cmd, timeout=60, internal_timeout=None,
                                  print_func=None):
        """
        Alias for cmd_status_output() for backward compatibility.
        """
        return self.cmd_status_output(cmd, timeout, internal_timeout,
                                      print_func)


    def get_command_status(self, cmd, timeout=60, internal_timeout=None,
                           print_func=None):
        """
        Alias for cmd_status() for backward compatibility.
        """
        return self.cmd_status(cmd, timeout, internal_timeout, print_func)
