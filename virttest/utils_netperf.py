import os
import logging
import re
from autotest.client import utils
import remote
import aexpect
import data_dir


class NetperfError(Exception):
    pass


class NetperfPackageError(NetperfError):

    def __init__(self, error_info):
        NetperfError.__init__(self)
        self.error_info = error_info

    def __str__(self):
        e_msg = "Packeage Error: %s" % self.error_info
        return e_msg


class NetserverError(NetperfError):

    def __init__(self, error_info):
        NetperfError.__init__(self)
        self.error_info = error_info

    def __str__(self):
        e_msg = "Netserver Error: %s" % self.error_info
        return e_msg


class NetperfTestError(NetperfError):

    def __init__(self, error_info):
        NetperfError.__init__(self)
        self.error_info = error_info

    def __str__(self):
        e_msg = "Netperf test error: %s" % self.error_info
        return e_msg


class NetperfPackage(remote.Remote_Package):

    def __init__(self, address, netperf_path, md5sum="", local_path="",
                 client="ssh", port="22", username="root", password="redhat"):
        """
        Class NetperfPackage just represent the netperf package
        Init NetperfPackage class.

        :param address: Remote host or guest address
        :param netperf_path: Remote netperf path
        :param me5sum: Local netperf package me5sum
        :param local_path: Local netperf (path or link) path
        :param client: The client to use ('ssh', 'telnet' or 'nc')
        :param port: Port to connect to
        :param username: Username (if required)
        :param password: Password (if required)
        """
        super(NetperfPackage, self).__init__(address, client, username,
                                             password, port, netperf_path)

        self.local_netperf = local_path
        self.pack_suffix = ""
        if client == "nc":
            self.prompt = r"^\w:\\.*>\s*$"
            self.linesep = "\r\n"
        else:
            self.prompt = "^\[.*\][\#\$]\s*$"
            self.linesep = "\n"
            if self.remote_path.endswith("tar.bz2"):
                self.pack_suffix = ".tar.bz2"
                self.decomp_cmd = "tar jxvf"
            elif self.remote_path.endswith("tar.gz"):
                self.pack_suffix = ".tar.gz"
                self.decomp_cmd = "tar zxvf"

            self.netperf_dir = self.remote_path.rstrip(self.pack_suffix)
            self.netperf_base_dir = os.path.dirname(self.remote_path)
            self.netperf_exec = os.path.basename(self.remote_path)

        if utils.is_url(local_path):
            logging.debug("Download URL file to local path")
            tmp_dir = data_dir.get_download_dir()
            self.local_netperf = utils.unmap_url_cache(tmp_dir, local_path,
                                                       md5sum)
        self.push_file(self.local_netperf)

        logging.debug("Create remote session")
        self.session = remote.remote_login(self.client, self.address,
                                           self.port, self.username,
                                           self.password, self.prompt,
                                           self.linesep, timeout=360)

    def __del__(self):
        self.env_cleanup()

    def env_cleanup(self, clean_all=True):
        clean_cmd = "rm -rf %s" % self.netperf_dir
        if clean_all:
            clean_cmd += " rm -rf %s" % self.remote_path
        self.session.cmd(clean_cmd, ignore_all_errors=True)

    def pack_compile(self, compile_option=""):
        pre_setup_cmd = "cd %s " % self.netperf_base_dir
        pre_setup_cmd += " && %s %s" % (self.decomp_cmd, self.netperf_exec)
        netperf_dir = self.session.cmd("tar -tf %s | sed -n 1p" %
                                       self.remote_path).strip()
        self.netperf_dir = os.path.join(self.netperf_base_dir, netperf_dir)
        pre_setup_cmd += " && cd %s " % self.netperf_dir
        setup_cmd = "./configure %s > /dev/null " % compile_option
        setup_cmd += " && make > /dev/null"
        self.env_cleanup(clean_all=False)
        cmd = "%s && %s " % (pre_setup_cmd, setup_cmd)
        try:
            self.session.cmd(cmd)
        except aexpect.ShellError, e:
            raise NetperfPackageError("Compile failed: %s" % e)


class NetperfServer(NetperfPackage):

    def __init__(self, address, netperf_path, md5sum="", local_path="",
                 client="ssh", port="22", username="root", password="redhat",
                 compile_option="--enable-demo=yes"):
        """
        Init NetperfServer class.

        :param address: Remote host or guest address
        :param netperf_path: Remote netperf path
        :param me5sum: Local netperf package me5sum
        :param local_path: Local netperf (path or link) with will transfer to
                           remote
        :param client: The client to use ('ssh', 'telnet' or 'nc')
        :param port: Port to connect to
        :param username: Username (if required)
        :param password: Password (if required)
        """
        super(NetperfServer, self).__init__(address, netperf_path, md5sum,
                                            local_path, client, port, username,
                                            password)

        if self.pack_suffix:
            logging.debug("Compile netperf src")
            self.pack_compile(compile_option)
            self.netserver_dir = os.path.join(self.netperf_dir,
                                              "src/netserver")
        else:
            self.netserver_dir = self.remote_path

    def start(self, restart=False):
        """
        Start/Restart netserver

        :param restart: if restart=True, will restart the netserver
        """

        logging.info("Start netserver ...")
        server_cmd = ""
        if self.client == "nc":
            server_cmd += "start /b %s" % self.netserver_dir
        else:
            server_cmd = self.netserver_dir

        if restart:
            self.stop()
        if not self.is_server_running():
            logging.debug("Start netserver with cmd: '%s'" % server_cmd)
            self.session.cmd_output_safe(server_cmd)

        if not self.is_server_running():
            raise NetserverError("Can not start netperf server!")
        logging.info("Netserver start successfully")

    def is_server_running(self):
        if self.client == "nc":
            check_reg = re.compile(r"NETSERVER.*EXE", re.I)
            if check_reg.findall(self.session.cmd_output("tasklist")):
                return True
        else:
            status_cmd = "pidof netserver"
            if not self.session.cmd_status(status_cmd):
                return True
        return False

    def stop(self):
        if self.client == "nc":
            stop_cmd = "taskkill /F /IM netserver*"
        else:
            stop_cmd = "killall netserver"
        if self.is_server_running():
            self.session.cmd(stop_cmd, ignore_all_errors=True)
        if self.is_server_running():
            raise NetserverError("Cannot stop the netserver")
        logging.info("Stop netserver successfully")


class NetperfClient(NetperfPackage):

    def __init__(self, address, netperf_path, md5sum="", local_path="",
                 client="ssh", port="22", username="root", password="redhat",
                 compile_option=""):
        """
        Init NetperfClient class.

        :param address: Remote host or guest address
        :param netperf_path: Remote netperf path
        :param me5sum: Local netperf package me5sum
        :param local_path: Local netperf (path or link) with will transfer to
                           remote
        :param client: The client to use ('ssh', 'telnet' or 'nc')
        :param port: Port to connect to
        :param username: Username (if required)
        :param password: Password (if required)
        """
        super(NetperfClient, self).__init__(address, netperf_path, md5sum,
                                            local_path, client, port, username,
                                            password)

        if self.pack_suffix:
            logging.debug("Compile netperf src for client")
            self.pack_compile(compile_option)
            self.client_dir = os.path.join(self.netperf_dir, "src/netperf")
        else:
            self.client_dir = self.remote_path

    def start(self, server_address, test_option="", timeout=1200,
              cmd_prefix=""):
        """
        Run netperf test

        :param server_address: Remote netserver address
        :param netperf_path: netperf test option (global/test option)
        :param timeout: Netperf test timeout(-l)
        :return: return test result
        """
        netperf_cmd = "%s %s -H %s %s " % (cmd_prefix, self.client_dir,
                                           server_address, test_option)
        logging.debug("Start netperf with cmd: '%s'" % netperf_cmd)
        (status, output) = self.session.cmd_status_output(netperf_cmd,
                                                          timeout=timeout)
        if status:
            raise NetperfTestError("Run netperf error. %s" % output)
        self.result = output
        return self.result

    def bg_start(self, server_address, test_option="", session_num=1,
                 cmd_prefix=""):
        """
        Run netperf background, for stress test, Only support linux now
        Have no output

        :param server_address: Remote netserver address
        :param netperf_path: netperf test option (global/test option)
        :param timeout: Netperf test timeout(-l)
        """
        if self.client == "nc":
            raise NetperfTestError("Currently only support linux client")

        netperf_cmd = "%s %s -H %s %s " % (cmd_prefix, self.client_dir,
                                           server_address, test_option)
        logging.debug("Start %s sessions netperf background with cmd: '%s'" %
                      (session_num, netperf_cmd))
        for _ in xrange(int(session_num)):
            self.session.cmd_output_safe("%s &" % netperf_cmd)
        return

    def stop(self):
        if self.client == "nc":
            kill_cmd = "taskkill /F /IM netperf*"
        else:
            kill_cmd = "killall netperf"
        self.session.cmd(kill_cmd, ignore_all_errors=True)

    def is_test_running(self):
        if self.client == "nc":
            check_reg = re.compile(r"NETPERF.*EXE", re.I)
            if check_reg.findall(self.session.cmd_output("tasklist")):
                return True
        else:
            status_cmd = "pidof netperf"
            if not self.session.cmd_status(status_cmd):
                return True
        return False
