"""
connection tools to manage kinds of connection.
"""

import logging

from autotest.client import utils, os_dep
from autotest.client.shared import error
from virttest import propcan, remote


class SASL(propcan.PropCanBase):

    """
    Base class of a connection between server and client.
    """
    __slots__ = ("sasl_pwd_cmd", "sasl_user_pwd", "sasl_user_cmd",
                 "auto_cleanup", "linesep", "remote_prompt", "session",
                 "server_ip", "server_user", "server_port", "client")

    def __init__(self, *args, **dargs):
        """
        Initialize instance
        """
        init_dict = dict(*args, **dargs)
        init_dict["sasl_pwd_cmd"] = os_dep.command("saslpasswd2")
        init_dict["sasl_user_cmd"] = os_dep.command("sasldblistusers2")
        init_dict["sasl_user_pwd"] = init_dict.get("sasl_user_pwd")
        init_dict["auto_cleanup"] = init_dict.get("auto_cleanup", False)
        init_dict["client"] = init_dict.get("client", "ssh")
        init_dict["port"] = init_dict.get("server_port", "22")
        init_dict["linesep"] = init_dict.get("linesep", "\n")
        init_dict["prompt"] = init_dict.get("prompt", r"[\#\$]\s*$")
        init_dict["session"] = remote.remote_login(init_dict["client"],
                                                   init_dict["server_ip"],
                                                   init_dict["port"],
                                                   init_dict["server_user"],
                                                   init_dict["server_pwd"],
                                                   init_dict["prompt"],
                                                   init_dict["linesep"],
                                                   timeout=360)
        super(SASL, self).__init__(init_dict)

    def __del__(self):
        """
        Close opened session and clear test environment
        """
        self.close_session()
        if self.auto_cleanup:
            try:
                self.cleanup()
            except:
                raise error.TestError("Failed to clean up test environment!")

    def setup(self):
        """
        Create sasl users with password
        """
        for sasl_user, sasl_pwd in eval(self.sasl_user_pwd):
            cmd = "echo %s |%s -p -a libvirt %s" % (sasl_pwd,
                                                    self.sasl_pwd_cmd,
                                                    sasl_user)
            try:
                if self.session:
                    self.session.cmd(cmd)
                else:
                    utils.system(cmd)
            except error.CmdError:
                logging.error("Failed to set a user's sasl password %s", cmd)

    def list_users(self, sasldb_path="/etc/libvirt/passwd.db"):
        """
        List users in sasldb
        """
        cmd = "%s -f %s" % (self.sasl_user_cmd, sasldb_path)
        try:
            if self.session:
                return self.session.cmd_output(cmd)
            else:
                return utils.system_output(cmd)
        except error.CmdError:
            logging.error("Failed to set a user's sasl password %s", cmd)

    def cleanup(self):
        """
        Clear created sasl users
        """
        for sasl_user, sasl_pwd in eval(self.sasl_user_pwd):
            cmd = "%s -a libvirt -d %s" % (self.sasl_pwd_cmd, sasl_user)
            try:
                if self.session:
                    self.session.cmd(cmd)
                else:
                    utils.system(cmd)
            except error.CmdError:
                logging.error("Failed to disable a user's access %s", cmd)

    def close_session(self):
        """
        If session exists then close it
        """
        if self.session:
            self.session.close()
