import re, logging
from autotest_lib.client.common_lib import error
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import logging_manager
import aexpect
import virt_utils

class QemuIOError(Exception):
    """
    Base exception for qemu-io command.
    """
    pass


class QemuIO():
    """
    A class for execute qemu-io command
    """

    def __init__(self, test, image_name, blkdebug_cfg="",
                 prompt=r"qemu-io>\s*$", log_filename=None, io_options=""):
        if log_filename:
            log_filename += "-" + virt_utils.generate_random_string(4)
            self.output_func = virt_utils.log_line
            self.output_params = (log_filename,)
        else:
            self.output_func = None
            self.output_params = ()
        self.output_prefix = ""
        self.prompt=prompt
        self.blkdebug_cfg=blkdebug_cfg

        self.qemu_io_cmd = virt_utils.get_path(test.bindir, "qemu-io")

    def cmd_output(self, command):
        """
        Run a command in qemu-io
        """
        pass

    def close(self):
        """
        Clean up
        """
        pass

class QemuIOShellSession(QemuIO):
    """
    Use a shell session to execute qemu-io command
    """
    def __init__(self, test, image_name, blkdebug_cfg="",
                 prompt=r"qemu-io>\s*$", log_filename=None, io_options=""):
        QemuIO.__init__(self, test, image_name, blkdebug_cfg, prompt,
                        log_filename, io_options)

        self.type = "shell"
        ignore_option = ["h", "help", "V", "version", "c", "cmd"]
        qemu_io_cmd = self.qemu_io_cmd

        if io_options:
            for io_option in re.split(",", io_options):
                if io_option in ignore_option:
                    raise QemuIOError("Opion %s should not be here."
                                      % io_option)
                else:
                    if len(io_option) == 1:
                        qemu_io_cmd += " -%s" % io_option
                    else:
                        qemu_io_cmd += " --%s" % io_option

        if image_name:
            qemu_io_cmd += " "
            if blkdebug_cfg:
                qemu_io_cmd += "blkdebug:%s:" %  blkdebug_cfg
            qemu_io_cmd += image_name

        self.qemu_io_cmd = qemu_io_cmd
        self.create_session = True
        self.session = None


    @error.context_aware
    def cmd_output(self, command, timeout=60):
        """
        Get output from shell session. If the create flag is True, init the
        shell session and set the create flag to False.
        @param command: command to execute in qemu-io
        @param timeout: timeout for execute the command
        """
        qemu_io_cmd = self.qemu_io_cmd
        prompt = self.prompt
        output_func = self.output_func
        output_params = self.output_params
        output_prefix = self.output_prefix
        if self.create_session:
            error.context("Running command: %s" % qemu_io_cmd, logging.info)
            self.session = aexpect.ShellSession(qemu_io_cmd, prompt=prompt,
                                                 output_func=output_func,
                                                 output_params=output_params,
                                                 output_prefix=output_prefix)
            self.create_session = False
            # Get the reaction from session
            self.session.cmd_output("\n")

        error.context("Executing command: %s" % command, logging.info)
        return self.session.cmd_output(command, timeout=timeout)


    def close(self):
        """
        Close the shell session for qemu-io
        """
        self.session.close()


class QemuIOSystem(QemuIO):
    """
    Run qemu-io with a command line which will return immediately
    """
    def __init__(self, test, image_name, blkdebug_cfg="",
                 prompt=r"qemu-io>\s*$", log_filename=None, io_options=""):
        QemuIO.__init__(self, test, image_name, blkdebug_cfg, prompt,
                        log_filename, io_options)
        no_warning_option = ["h", "help", "V", "version", "c", "cmd"]
        ignore_option = ["c", "cmd"]
        qemu_io_cmd = self.qemu_io_cmd

        warning_flag = True
        self.run_command = False
        for io_option in re.split(",", io_options):
            if io_option in no_warning_option:
                warning_flag = False
            if io_option in ignore_option:
                self.run_command = True
            else:
                if len(io_option) == 1:
                    qemu_io_cmd += " -%s" % io_option
                else:
                    qemu_io_cmd += " --%s" % io_option

        if warning_flag:
            raise error.QemuIOError("The qemu-io command will not return"
                                    " immedirately with this "
                                    "option %s" % io_options)

        if image_name:
            qemu_io_cmd += " "
            if blkdebug_cfg:
                qemu_io_cmd += "blkdebug:%s:" %  blkdebug_cfg
            qemu_io_cmd += image_name

        self.qemu_io_cmd = qemu_io_cmd

    @error.context_aware
    def cmd_output(self, command, timeout=60):
        """
        Get output from system_output. Add the command to the qemu-io command
        line with -c and record the output in the log file.
        @param command: command to execute in qemu-io
        @param timeout: timeout for execute the command
        """
        qemu_io_cmd = self.qemu_io_cmd
        if self.run_command:
            qemu_io_cmd += " -c '%s'" % command

        error.context("Running command: %s" % qemu_io_cmd, logging.info)
        output = utils.system_output(qemu_io_cmd, timeout=timeout)

        params = self.output_params + (output,)
        self.output_func(*params)

        return output

    def close(self):
        """
        To keep the the same interface with QemuIOShellSession
        """
        pass
