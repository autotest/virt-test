"""
connection tools to manage kinds of connection.
"""

import logging, time, os, shutil, re
from autotest.client import utils, os_dep
from virttest import aexpect, propcan, remote, utils_libvirtd


class ConnectionError(Exception):
    """
    The base error in connection.
    """
    pass


class ConnForbiddenError(ConnectionError):
    """
    Error in forbidden operation.
    """
    def __init__(self, detail):
        ConnectionError.__init__(self)
        self.detail = detail

    def __str__(self):
        return ('Operation is forbidden.\n'
                'Message: %s' % self.detail)


class ConnCopyError(ConnectionError):
    """
    Error in coping file.
    """
    def __init__(self, src_path, dest_path):
        ConnectionError.__init__(self)
        self.src_path = src_path
        self.dest_path = dest_path

    def __str__(self):
        return ('Copy file from %s to %s failed.'
                % (self.src_path, self.dest_path))


class ConnNotImplementedError(ConnectionError):
    def __init__(self, method_type, class_type):
        ConnectionError.__init__(self)
        self.method_type = method_type
        self.class_type = class_type

    def __str__(self):
        return ('Method %s is not implemented in class %s\n'
                % (self.method_type, self.class_type))

class ConnLoginError(ConnectionError):
    """
    Error in login.
    """
    def __init__(self, dest, e):
        ConnectionError.__init__(self)
        self.dest = dest
        self.e = e

    def __str__(self):
        return ("Got a error when login to %s.\n"
               "Error: %s\n" % (self.dest, self.e))

class ConnToolNotFoundError(ConnectionError):
    """
    Error in not found tools.
    """
    def __init__(self, tool, e):
        ConnectionError.__init__(self)
        self.tool = tool
        self.e = e

    def __str__(self):
        return ("Got a error when access the tool (%s).\n"
               "Error: %s\n" % (self.tool, self.e))


class ConnSCPError(ConnectionError):
    """
    Error in SCP.
    """
    def __init__(self, src_ip, src_path, dest_ip, dest_path, e):
        ConnectionError.__init__(self)
        self.src_ip = src_ip
        self.src_path = src_path
        self.dest_ip = dest_ip
        self.dest_path = dest_path
        self.e = e

    def __str__(self):
        return ("Failed scp from %s on %s to %s on %s.\n"
                "error: %s.\n" %
                (self.src_path, self.src_ip, self.dest_path,
                                        self.dest_ip, self.e))


class SSHCheckError(ConnectionError):
    """
    Base Error in check of SSH connection.
    """
    def __init__(self, server_ip, output):
        ConnectionError.__init__(self)
        self.server_ip = server_ip
        self.output = output

    def __str__(self):
        return ("SSH to %s failed.\n"
                "output: %s " % (self.server_ip, self.output))


class ConnCmdClientError(ConnectionError):
    """
    Error in executing cmd on client.
    """
    def __init__(self, cmd, output):
        ConnectionError.__init__(self)
        self.cmd = cmd
        self.output = output

    def __str__(self):
        return ("Execute command '%s' on client failed.\n"
                "output: %s" % (self.cmd, self.output))


class ConnPrivKeyError(ConnectionError):
    """
    Error in building private key with certtool command.
    """
    def __init__(self, key, output):
        ConnectionError.__init__(self)
        self.key = key
        self.output = output

    def __str__(self):
        return ("Failed to build private key file(%s).\n"
               "output: %s .\n" % (self.key, self.output))


class ConnCertError(ConnectionError):
    """
    Error in building certificate file with certtool command.
    """
    def __init__(self, cert, output):
        ConnectionError.__init__(self)
        self.cert = cert
        self.output = output

    def __str__(self):
        return ("Failed to build certificate file (%s).\n"
               "output: %s .\n" % (self.cert, self.output))


class ConnMkdirError(ConnectionError):
    """
    Error in making directory.
    """
    def __init__(self, dir, output):
        ConnectionError.__init__(self)
        self.dir = dir
        self.output = output

    def __str__(self):
        return ("Failed to make directory %s \n"
               "output: %s.\n" % (self.dir, self.output))


class ConnClientEditHostsConfigError(ConnectionError):
    """
    Error in editing config file /etc/hosts on client.
    """
    def __init__(self, output):
        ConnectionError.__init__(self)
        self.output = output
    def __str__(self):
        return ("Failed to edit /etc/hosts on client.\n"
               "output: %s.\n" % (self.output))


class ConnServerConfigError(ConnectionError):
    """
    Error in editing config file /etc/sysconfig/libvirtd on server.
    """
    def __init__(self, output):
        ConnectionError.__init__(self)
        self.output = output
    def __str__(self):
        return ("Failed to edit /etc/sysconfig/libvirtd on server.\n"
               "output: %s.\n" % (self.output))


class ConnServerRestartError(ConnectionError):
    """
    Error in restarting libvirtd on server.
    """
    def __init__(self, output):
        ConnectionError.__init__(self)
        self.output = output
    def __str__(self):
        return ("Failed to restart libvirtd service on server.\n"
               "output: %s.\n" % (self.output))


class ConnectionBase(propcan.PropCanBase):
    """
    Base class of a connection between server and client.
    """
    __slots__ = ('server_ip', 'server_user', 'server_pwd',
                 'client_ip', 'client_user', 'client_pwd',
                 'server_session', 'client_session',
                 'tmp_dir')

    def __init__(self, *args, **dargs):
        """
        Initialize instance with server info and client info.
        """
        init_dict = dict(*args, **dargs)
        init_dict['server_ip'] = init_dict.get('server_ip', 'SERVER.IP')
        init_dict['server_user'] = init_dict.get('server_user', 'root')
        init_dict['server_pwd'] = init_dict.get('server_pwd', None)
        init_dict['client_ip'] = init_dict.get('client_ip', 'CLIENT.IP')
        init_dict['client_user'] = init_dict.get('client_user', 'root')
        init_dict['client_pwd'] = init_dict.get('client_pwd', None)
        init_dict['tmp_dir'] = init_dict.get('tmp_dir', None)
        super(ConnectionBase, self).__init__(init_dict)

        self.dict_set('client_session', None)
        self.dict_set('server_session', None)

        #make a tmp dir as a workspace
        tmp_dir = self.dict_get('tmp_dir')
        if tmp_dir is None:
            current_time = time.time()
            tmp_dir = "/tmp/%s" % current_time
            try:
                os.makedirs(tmp_dir)
            except OSError, e:
                raise ConnMkdirError(tmp_dir, e)
            self.tmp_dir = tmp_dir


    def __del__(self):
        """
        Clean up any leftover sessions and tmp_dir.
        """
        self.close_session()
        try:
            self.conn_finish()
        except ConnNotImplementedError:
            pass

        tmp_dir = self.tmp_dir
        if (tmp_dir is not None) and (os.path.exists(tmp_dir)):
            shutil.rmtree(tmp_dir)


    def close_session(self):
        """
        If some session exists, close it down.
        """
        session_list = ['client_session', 'server_session']
        for session_name in session_list:
            session = self.dict_get(session_name)
            if session is not None:
                session.close()
            else:
                continue

    def conn_setup(self):
        """
        waiting for implemented by subclass.
        """
        raise ConnNotImplementedError('conn_setup', self.__class__)

    def conn_check(self):
        """
        waiting for implemented by subclass.
        """
        raise ConnNotImplementedError('conn_check', self.__class__)

    def conn_finish(self):
        """
        waiting for implemented by subclass.
        """
        raise ConnNotImplementedError('conn_finish', self.__class__)

    def _new_client_session(self):
        """
        """
        transport = 'ssh'
        host = self.client_ip
        port = 22
        username = self.client_user
        password = self.client_pwd
        prompt = r"[\#\$]\s*$"
        try:
            client_session = remote.wait_for_login(transport, host, port,
                                               username, password, prompt)
        except remote.LoginTimeoutError, e:
            raise ConnLoginError("Got a timeout error when login to client.")
        except remote.LoginAuthenticationError, e:
            raise ConnLoginError("Authentication failed to login to client.")
        except remote.LoginProcessTerminatedError, e:
            raise ConnLoginError("Host terminates during login to client.")
        except remote.LoginError, e:
            raise ConnLoginError("Some error occurs login to client failed.")

        return client_session


    def get_client_session(self):
        """
        If the client session exists,return it.
        else create a session to client and set client_session.
        """
        client_session = self.dict_get('client_session')

        if client_session is not None:
            return client_session
        else:
            client_session = self._new_client_session()

        self.dict_set('client_session', client_session)
        return client_session

    def set_client_session(self, value):
        raise ConnForbiddenError('Forbide to set client_session')

    def del_client_session(self):
        raise ConnForbiddenError('Forbide to del client_session')

    def _new_server_session(self):
        """
        """
        transport = 'ssh'
        host = self.server_ip
        port = 22
        username = self.server_user
        password = self.server_pwd
        prompt = r"[\#\$]\s*$"
        try:
            server_session = remote.wait_for_login(transport, host, port,
                                               username, password, prompt)
        except remote.LoginTimeoutError, e:
            raise ConnLoginError("Got a timeout error when login to server.")
        except remote.LoginAuthenticationError, e:
            raise ConnLoginError("Authentication failed to login to server.")
        except remote.LoginProcessTerminatedError, e:
            raise ConnLoginError("Host terminates during login to server.")
        except remote.LoginError, e:
            raise ConnLoginError("Some error occurs login to client server.")

        return server_session


    def get_server_session(self):
        """
        If the server session exists,return it.
        else create a session to server and set server_session.
        """
        server_session = self.dict_get('server_session')

        if not server_session is None:
            return server_session
        else:
            server_session = self._new_server_session()

        self.dict_set('server_session', server_session)
        return server_session


    def set_server_session(self, value):
        raise ConnForbiddenError('Forbide to set server_session')


    def del_server_session(self):
        raise ConnForbiddenError('Forbide to del server_session')


class SSHConnection(ConnectionBase):
    """
    Connection of SSH transport.
    """
    __slots__ = ConnectionBase.__slots__ + ('ssh_rsa_pub_path',
                                'ssh_id_rsa_path', 'SSH_KEYGEN',
                                'SSH_ADD', 'SSH_COPY_ID',
                                'SSH_AGENT', 'SHELL', 'SSH')

    def __init__(self, *args, **dargs):
        """
        Initialization of SSH connection.

        (1). Call __init__ of class ConnectionBase.
        (2). Initialize tools will be used in conn setup.
        """
        init_dict = dict(*args, **dargs)
        init_dict['ssh_rsa_pub_path'] = init_dict.get('ssh_rsa_pub_path',
                                                    '/root/.ssh/id_rsa.pub')
        init_dict['ssh_id_rsa_path'] = init_dict.get('ssh_id_rsa_path',
                                                    '/root/.ssh/id_rsa')
        super(SSHConnection, self).__init__(init_dict)
        #set the tool for ssh setup.
        tool_dict = {'SSH_KEYGEN':'ssh-keygen',
                     'SSH_ADD':'ssh-add',
                     'SSH_COPY_ID':'ssh-copy-id',
                     'SSH_AGENT':'ssh-agent',
                     'SHELL':'sh',
                     'SSH':'ssh'}

        for key in tool_dict:
            toolName = tool_dict[key]
            try:
                tool = os_dep.command(toolName)
            except ValueError:
                logging.debug("%s executable not set or found on path,"
                              "some fucntion of connection will fail." %
                              (toolName))
                tool = '/bin/true'
            self.dict_set(key, tool)

    def conn_check(self):
        """
        Check the SSH connection.

        (1).Initialize some variables.
        (2).execute ssh command to check conn.
        """
        client_session = self.client_session
        server_user = self.server_user
        server_ip = self.server_ip
        ssh = self.SSH
        if ssh is '/bin/true':
            raise ConnToolNotFoundError('ssh',
                    "executable not set or found on path, ")

        cmd = "%s %s@%s exit 0" % (ssh, server_user, server_ip)
        try:
            status, output = client_session.cmd_status_output(cmd, timeout=5)
        except aexpect.ShellError, e:
            raise SSHCheckError(server_ip, e)
        logging.debug("Check the SSH to %s OK." % server_ip)

    def conn_finish(self):
        """
        It's ok to ignore finish work for ssh connection.
        """
        pass

    def conn_setup(self):
        """
        Setup of SSH connection.

        (1).Initialization of some variables.
        (2).Check tools.
        (3).Initialization of id_rsa.
        (4).set a ssh_agent.
        (5).copy pub key to server.
        """
        client_session = self.client_session
        ssh_rsa_pub_path = self.ssh_rsa_pub_path
        ssh_id_rsa_path = self.ssh_id_rsa_path
        server_user = self.server_user
        server_ip = self.server_ip
        server_pwd = self.server_pwd
        ssh_keygen = self.SSH_KEYGEN
        ssh_add = self.SSH_ADD
        ssh_copy_id = self.SSH_COPY_ID
        ssh_agent = self.SSH_AGENT
        shell = self.SHELL

        tool_dict = {'ssh_keygen':ssh_keygen,
                     'ssh_add':ssh_add,
                     'ssh_copy_id':ssh_copy_id,
                     'ssh_agent':ssh_agent,
                     'shell':shell}
        for tool_name in tool_dict:
            tool = tool_dict[tool_name]
            if tool is '/bin/true':
                raise ConnToolNotFoundError(tool_name,
                        "executable not set or found on path,")

        if os.path.exists("/root/.ssh/id_rsa"):
            pass
        else:
            cmd = "%s -t rsa -f /root/.ssh/id_rsa -N '' " % (ssh_keygen)
            status, output = client_session.cmd_status_output(cmd)
            if status:
                raise ConnCmdClientError(cmd, output)

        cmd = "%s %s" % (ssh_agent, shell)
        status, output = client_session.cmd_status_output(cmd)
        if status:
            raise ConnCmdClientError(cmd, output)

        cmd = "%s %s" % (ssh_add, ssh_id_rsa_path)
        status, output = client_session.cmd_status_output(cmd)
        if status:
            raise ConnCmdClientError(cmd, output)

        cmd = "%s -i %s %s@%s" % (ssh_copy_id, ssh_rsa_pub_path,
                                        server_user, server_ip)
        try:
            client_session.sendline(cmd)
            remote.handle_prompts(client_session, server_user,
                                        server_pwd, prompt = r"[\#\$]\s*$")
        except Exception, e:
            raise ConnCmdClientError(cmd, e)

        logging.debug("SSH connection setup successfully.")


class TCPConnection(ConnectionBase):
    __slots__ = ConnectionBase.__slots__ + ('tcp_port',
                                'sysconfig_libvirtd_path',
                                'libvirtd_conf_path')

    def __init__(self, *args, **dargs):
        """
        init params for TCP connection and init tmp_dir.
        """
        init_dict = dict(*args, **dargs)
        init_dict['tcp_port'] = init_dict.get('tcp_port', '16509')
        super(TCPConnection, self).__init__(init_dict)
        #set paths of config file on server.
        self.dict_set('sysconfig_libvirtd_path', '/etc/sysconfig/libvirtd')
        self.dict_set('libvirtd_conf_path', '/etc/libvirt/libvirtd.conf')

        #make a tmp dir as a workspace
        tmp_dir = self.tmp_dir
        if tmp_dir is None:
            current_time = time.time()
            tmp_dir = "/tmp/%s" % current_time
            os.mkdir(tmp_dir)
            self.dict_set('tmp_dir', tmp_dir)

    def conn_finish(self):
        """
        Clean up for TCP connection.

        (1).initialize variables.
        (2).scp backup file to server.
        (3).restart libvirtd on server.
        """
        #initialize variables
        server_ip = self.server_ip
        server_user = self.server_user
        server_pwd = self.server_pwd
        tmp_dir = self.tmp_dir
        sysconfig_libvirtd_path = self.sysconfig_libvirtd_path
        tmp_syslibvirtd_bak_path = '%s/libvirtd.bak' % tmp_dir
        libvirtd_conf_path = self.libvirtd_conf_path
        tmp_libvirtdconf_bak_path = '%s/libvirtd.conf.bak' % tmp_dir

        #scp backup file to server.
        server_bak_dict = {tmp_syslibvirtd_bak_path:sysconfig_libvirtd_path,
                            tmp_libvirtdconf_bak_path:libvirtd_conf_path}

        for key in server_bak_dict:
            bak_file = key
            remote_path = server_bak_dict[key]
            if not os.path.exists(bak_file):
                continue
            try:
                remote.copy_files_to(server_ip, 'scp', server_user,
                                server_pwd, "22", bak_file,
                                remote_path)
            except remote.SCPError, e:
                raise ConnSCPError('AdminHost', bak_file,
                                    server_ip, remote_path, e)

        #restart libvirtd service on server
        try:
            utils_libvirtd.libvirtd_restart(server_ip=server_ip,
                                            server_user=server_user,
                                            server_pwd=server_pwd,)
        except utils_libvirtd.LibvirtdError, e:
            raise ConnServerRestartError(e)

        logging.debug("TCP connection recover successfully.")


    def conn_setup(self):
        """
        Enable tcp connect of libvirtd on server.

        (1).initialization for variables.
        (2).edit /etc/sysconfig/libvirtd on server.
        (3).edit /etc/libvirt/libvirtd.conf on server.
        (4).restart libvirtd service on server.
        """
        #initialize variables
        server_ip = self.server_ip
        server_user = self.server_user
        server_pwd = self.server_pwd
        tmp_dir = self.tmp_dir
        sysconfig_libvirtd_path = self.sysconfig_libvirtd_path
        tmp_syslibvirtd_path = '%s/libvirtd' % tmp_dir
        tmp_syslibvirtd_bak_path = '%s.bak' % tmp_syslibvirtd_path
        libvirtd_conf_path = self.libvirtd_conf_path
        tmp_libvirtdconf_path = '%s/libvirtd.conf' % tmp_dir
        tmp_libvirtdconf_bak_path = '%s.bak' % tmp_libvirtdconf_path
        tcp_port = self.tcp_port

        #edit the /etc/sysconfig/libvirtd to add --listen args in libvirtd
        #scp from server.
        try:
            remote.copy_files_from(server_ip, 'scp', server_user,
                            server_pwd, '22', sysconfig_libvirtd_path,
                            tmp_syslibvirtd_path)
        except remote.SCPError, e:
            raise ConnSCPError(server_ip, sysconfig_libvirtd_path,
                                'AdminHost', tmp_syslibvirtd_path, e)
        #copy a backup for recover.
        try:
            shutil.copy(tmp_syslibvirtd_path, tmp_syslibvirtd_bak_path)
        except OSError, e:
            raise ConnCopyError(tmp_syslibvirtd_path, tmp_syslibvirtd_bak_path)

        #edit file.
        syslibvirtd_file = open(tmp_syslibvirtd_path, 'r')
        line_list = syslibvirtd_file.readlines()
        flag = False
        for index in range(len(line_list)):
            line = line_list[index]
            if not re.search(r"LIBVIRTD_ARGS\s*=\s*\"\s*--listen\s*\"", line):
                continue
            if (line.count('#') and
                    (line.index('#') < line.index('LIBVIRTD_ARGS'))):
                line_list[index] = "LIBVIRTD_ARGS=\"--listen\"\n"
            flag = True
            break
        if not flag is True:
            line_list.append("LIBVIRTD_ARGS=\"--listen\"\n")

        syslibvirtd_file.close()
        syslibvirtd_file = open(tmp_syslibvirtd_path, 'w')
        syslibvirtd_file.writelines(line_list)
        syslibvirtd_file.close()
        #scp to server.
        try:
            remote.copy_files_to(server_ip, 'scp', server_user,
                            server_pwd, "22", tmp_syslibvirtd_path,
                            sysconfig_libvirtd_path)
        except remote.SCPError, e:
            raise ConnSCPError('AdminHost', tmp_syslibvirtd_path,
                                server_ip, sysconfig_libvirtd_path, e)

        #edit the /etc/libvirt/libvirtd.conf
        #listen_tcp=1, tcp_port=$tcp_port, auth_tcp="none"
        #scp from server.
        try:
            remote.copy_files_from(server_ip, 'scp', server_user,
                            server_pwd, '22', libvirtd_conf_path,
                            tmp_libvirtdconf_path)
        except remote.SCPError, e:
            raise ConnSCPError(server_ip, libvirtd_conf_path,
                                'AdminHost', tmp_libvirtdconf_path, e)
        #copy a backup for recover.
        try:
            shutil.copy(tmp_libvirtdconf_path, tmp_libvirtdconf_bak_path)
        except OSError, e:
            raise ConnCopyError(tmp_libvirtdconf_path,
                                tmp_libvirtdconf_bak_path)
        #edit file.
        libvirtdconf_file = open(tmp_libvirtdconf_path, 'r')
        line_list = libvirtdconf_file.readlines()
        conf_dict = {r"listen_tcp\s*=":'listen_tcp=1\n',
                     r"tcp_port\s*=":'tcp_port="%s"\n' % (tcp_port),
                     r'auth_tcp\s*=':'auth_tcp="none"\n'}
        for key in conf_dict:
            pattern = key
            conf_line = conf_dict[key]
            flag = False
            for index in range(len(line_list)):
                line = line_list[index]
                if not re.search(pattern, line):
                    continue
                else:
                    line_list[index] = conf_line
                    flag = True
                break
            if not flag is True:
                line_list.append(conf_line)

        libvirtdconf_file.close()
        libvirtdconf_file = open(tmp_libvirtdconf_path, 'w')
        libvirtdconf_file.writelines(line_list)
        libvirtdconf_file.close()
        #scp to server.
        try:
            remote.copy_files_to(server_ip, 'scp', server_user,
                            server_pwd, "22", tmp_libvirtdconf_path,
                            libvirtd_conf_path)
        except remote.SCPError, e:
            raise ConnSCPError('AdminHost', tmp_libvirtdconf_path,
                                server_ip, libvirtd_conf_path, e)

        #restart libvirtd service on server
        try:
            utils_libvirtd.libvirtd_restart(server_ip=server_ip,
                                            server_user=server_user,
                                            server_pwd=server_pwd,)
        except utils_libvirtd.LibvirtdError, e:
            raise ConnServerRestartError(e)

        logging.debug("TCP connection setup successfully.")

class TLSConnection(ConnectionBase):
    """
    Connection of TLS transport.
    """
    __slots__ = ConnectionBase.__slots__ + ('server_cn', 'client_cn',
                            'CERTTOOL', 'pki_CA_dir',
                            'libvirt_pki_dir', 'libvirt_pki_private_dir',
                            'sysconfig_libvirtd_path','libvirtd_conf_path',
                            'hosts_path')

    def __init__(self, *args, **dargs):
        """
        Initialization of TLSConnection.

        (1).call the init func in ConnectionBase.
        (2).check and set CERTTOOL.
        (3).make a tmp directory as a workspace.
        (4).set values of pki related.
        """
        init_dict = dict(*args, **dargs)
        init_dict['server_cn'] = init_dict.get('server_cn', 'TLSServer')
        init_dict['client_cn'] = init_dict.get('client_cn', 'TLSClient')
        super(TLSConnection, self).__init__(init_dict)
        self.sysconfig_libvirtd_path = ('/etc/sysconfig/libvirtd')
        self.libvirtd_conf_path = ('/etc/libvirt/libvirtd.conf')
        self.hosts_path = ('/etc/hosts')
        #check and set CERTTOOL in slots
        try:
            CERTTOOL = os_dep.command("certtool")
        except ValueError:
            logging.warning("certtool executable not set or found on path, "
                            "TLS connection will not setup normally")
            CERTTOOL = '/bin/true'
        self.CERTTOOL = CERTTOOL
        #set some pki related dir values
        self.pki_CA_dir = ('/etc/pki/CA/')
        self.libvirt_pki_dir = ('/etc/pki/libvirt/')
        self.libvirt_pki_private_dir = ('/etc/pki/libvirt/private/')

    def conn_finish(self):
        """
        Do the clean up work.

        (1).initialize variables.
        (2).recover server.
        (3).recover client.
        """
        #initialize variables
        server_ip = self.server_ip
        server_user = self.server_user
        server_pwd = self.server_pwd
        client_ip = self.client_ip
        client_user = self.client_user
        client_pwd = self.client_pwd
        tmp_dir = self.tmp_dir
        hosts_path = self.hosts_path
        tmp_hosts_bak_path = '%s/hosts.bak' % tmp_dir
        sysconfig_libvirtd_path = self.sysconfig_libvirtd_path
        tmp_syslibvirtd_bak_path = '%s/libvirtd.bak' % tmp_dir
        libvirtd_conf_path = self.libvirtd_conf_path
        tmp_libvirtdconf_bak_path = '%s/libvirtd.conf.bak' % tmp_dir

        #scp backup file to server.
        server_bak_dict = {tmp_syslibvirtd_bak_path:sysconfig_libvirtd_path,
                            tmp_libvirtdconf_bak_path:libvirtd_conf_path}

        for key in server_bak_dict:
            bak_file = key
            remote_path = server_bak_dict[key]
            if not os.path.exists(bak_file):
                continue
            try:
                remote.copy_files_to(server_ip, 'scp', server_user,
                                server_pwd, "22", bak_file,
                                remote_path)
            except remote.SCPError, e:
                raise ConnSCPError('AdminHost', bak_file,
                                    server_ip, remote_path, e)

        #restart libvirtd service on server
        try:
            utils_libvirtd.libvirtd_restart(server_ip=server_ip,
                                            server_user=server_user,
                                            server_pwd=server_pwd,)
        except utils_libvirtd.LibvirtdError, e:
            raise ConnServerRestartError(e)

        #scp backup file to client.
        client_bak_dict = {tmp_hosts_bak_path:hosts_path}

        for key in client_bak_dict:
            bak_file = key
            remote_path = client_bak_dict[key]
            if not os.path.exists(bak_file):
                continue
            try:
                remote.copy_files_to(client_ip, 'scp', client_user,
                                client_pwd, "22", bak_file,
                                remote_path)
            except remote.SCPError, e:
                raise ConnSCPError('AdminHost', bak_file,
                                    client_ip, remote_path, e)

        logging.debug("TLS connection recover successfully.")

    def conn_setup(self):
        """
        setup a TLS connection between server and client.
        At first check the certtool needed to setup.
        Then call some setup functions to complete connection setup.
        """
        if self.CERTTOOL == '/bin/true':
            raise ConnToolNotFoundError('certtool',
                    "certtool executable not set or found on path.")

        self.CA_setup()
        self.server_setup()
        self.client_setup()

        logging.debug("TLS connection setup successfully.")


    def CA_setup(self):
        """
        setup private key and certificate file which are needed to build.
        certificate file for client and server.
        (1).initialization for variables.
        (2).make a private key with certtool command.
        (3).prepare a info file.
        (4).make a certificate file with certtool command.
        """
        #initialize variables
        certtool = self.CERTTOOL
        tmp_dir = self.tmp_dir
        cakey_path = '%s/tcakey.pem' % tmp_dir
        cainfo_path = '%s/ca.info' % tmp_dir
        cacert_path = '%s/cacert.pem' % tmp_dir

        #make a private key
        cmd = "%s --generate-privkey > %s " % (certtool, cakey_path)
        CmdResult = utils.run(cmd, ignore_status=True)
        if CmdResult.exit_status:
            raise ConnPrivKeyError(CmdResult.stderr)
        #prepare a info file to build certificate file
        cainfo_file = open(cainfo_path,"w")
        cainfo_file.write("cn = AUTOTEST.VIRT\n")
        cainfo_file.write("ca\n")
        cainfo_file.write("cert_signing_key\n")
        cainfo_file.close()

        #make a certificate file to build clientcert and servercert
        cmd = ("%s --generate-self-signed --load-privkey %s\
               --template %s --outfile %s" %
               (certtool, cakey_path, cainfo_path, cacert_path))
        CmdResult = utils.run(cmd, ignore_status=True)
        if CmdResult.exit_status:
            raise ConnCertError(CmdResult.stderr)


    def server_setup(self):
        """
        setup private key and certificate file for server.

        (1).initialization for variables.
        (2).make a private key with certtool command.
        (3).prepare a info file.
        (4).make a certificate file with certtool command.
        (5).copy files to server.
        (6).edit /etc/sysconfig/libvirtd on server.
        (7).edit /etc/libvirt/libvirtd.conf on server.
        (8).restart libvirtd service on server.
        """
        #initialize variables
        certtool = self.CERTTOOL
        tmp_dir = self.tmp_dir
        cakey_path = '%s/tcakey.pem' % tmp_dir
        cacert_path = '%s/cacert.pem' % tmp_dir
        serverkey_path = '%s/serverkey.pem' % tmp_dir
        servercert_path = '%s/servercert.pem' % tmp_dir
        serverinfo_path = '%s/server.info' % tmp_dir
        sysconfig_libvirtd_path = self.sysconfig_libvirtd_path
        tmp_syslibvirtd_path = '%s/libvirtd' % tmp_dir
        tmp_syslibvirtd_bak_path = '%s.bak' % tmp_syslibvirtd_path
        libvirtd_conf_path = self.libvirtd_conf_path
        tmp_libvirtdconf_path = '%s/libvirtd.conf' % tmp_dir
        tmp_libvirtdconf_bak_path = '%s.bak' % tmp_libvirtdconf_path
        server_ip = self.server_ip
        server_user = self.server_user
        server_pwd = self.server_pwd

        #make a private key
        cmd = "%s --generate-privkey > %s" % (certtool, serverkey_path)
        CmdResult = utils.run(cmd, ignore_status=True)
        if CmdResult.exit_status:
            raise ConnPrivKeyError(CmdResult.stderr)

        #prepare a info file to build servercert and serverkey
        serverinfo_file = open(serverinfo_path, "w")
        serverinfo_file.write("organization = AUTOTEST.VIRT\n")
        serverinfo_file.write("cn = %s\n" % (self.server_cn))
        serverinfo_file.write("tls_www_server\n")
        serverinfo_file.write("encryption_key\n")
        serverinfo_file.write("signing_key\n")
        serverinfo_file.close()

        #make a server certificate file and a server key file
        cmd = ("%s --generate-certificate --load-privkey %s \
               --load-ca-certificate %s --load-ca-privkey %s \
               --template %s --outfile %s" %
               (certtool, serverkey_path, cacert_path,
                cakey_path, serverinfo_path, servercert_path))
        CmdResult = utils.run(cmd, ignore_status=True)
        if CmdResult.exit_status:
            raise ConnCertError(CmdResult.stderr)

        #scp cacert.pem, servercert.pem and serverkey.pem to server.
        server_session = self.server_session
        cmd = "mkdir -p %s" % self.libvirt_pki_private_dir
        status, output = server_session.cmd_status_output(cmd)
        if status:
            raise ConnMkdirError(self.libvirt_pki_private_dir, output)

        scp_dict = {cacert_path:self.pki_CA_dir,
                    servercert_path:self.libvirt_pki_dir,
                    serverkey_path:self.libvirt_pki_private_dir}

        for key in scp_dict:
            local_path = key
            remote_path = scp_dict[key]
            try:
                remote.copy_files_to(server_ip, 'scp', server_user,
                         server_pwd, '22', local_path, remote_path)
            except remote.SCPError, e:
                raise ConnSCPError('AdminHost', local_path,
                                        server_ip, remote_path, e)

        #edit the /etc/sysconfig/libvirtd to add --listen args in libvirtd
        try:
            remote.copy_files_from(server_ip, 'scp', server_user,
                            server_pwd, '22', sysconfig_libvirtd_path,
                            tmp_syslibvirtd_path)
        except remote.SCPError, e:
            raise ConnSCPError(server_ip, sysconfig_libvirtd_path,
                                'AdminHost', tmp_syslibvirtd_path, e)
        #copy backup file for recover.
        try:
            shutil.copy(tmp_syslibvirtd_path, tmp_syslibvirtd_bak_path)
        except OSError, e:
            raise ConnCopyError(tmp_syslibvirtd_path, tmp_syslibvirtd_bak_path)
        #edit file.
        syslibvirtd_file = open(tmp_syslibvirtd_path, 'r')
        line_list = syslibvirtd_file.readlines()
        flag = False
        for index in range(len(line_list)):
            line = line_list[index]
            if not re.search(r"LIBVIRTD_ARGS\s*=\s*\"\s*--listen\s*\"", line):
                continue
            if (line.count('#') and
                    (line.index('#') < line.index('LIBVIRTD_ARGS'))):
                line_list[index] = "LIBVIRTD_ARGS=\"--listen\"\n"
            flag = True
            break
        if not flag is True:
            line_list.append("LIBVIRTD_ARGS=\"--listen\"\n")

        syslibvirtd_file.close()
        syslibvirtd_file = open(tmp_syslibvirtd_path, 'w')
        syslibvirtd_file.writelines(line_list)
        syslibvirtd_file.close()
        try:
            remote.copy_files_to(server_ip, 'scp', server_user,
                            server_pwd, "22", tmp_syslibvirtd_path,
                            sysconfig_libvirtd_path)
        except remote.SCPError, e:
            raise ConnSCPError('AdminHost', tmp_syslibvirtd_path,
                                server_ip, sysconfig_libvirtd_path, e)
        #edit the /etc/libvirt/libvirtd.conf to add listen_tls=1
        try:
            remote.copy_files_from(server_ip, 'scp', server_user,
                            server_pwd, '22', libvirtd_conf_path,
                            tmp_libvirtdconf_path)
        except remote.SCPError, e:
            raise ConnSCPError(server_ip, libvirtd_conf_path,
                                'AdminHost', tmp_libvirtdconf_path, e)
        #copy backup file for recover.
        try:
            shutil.copy(tmp_libvirtdconf_path, tmp_libvirtdconf_bak_path)
        except OSError, e:
            raise ConnCopyError(tmp_libvirtdconf_path,
                                tmp_libvirtdconf_bak_path)

        libvirtdconf_file = open(tmp_libvirtdconf_path, 'r')
        line_list = libvirtdconf_file.readlines()
        flag = False
        for index in range(len(line_list)):
            line = line_list[index]
            if not re.search(r"listen_tls\s*=\s*", line):
                continue
            else:
                line_list[index] = "listen_tls=1\n"
                flag = True
            break
        if not flag is True:
            line_list.append("listen_tls=1\n")

        libvirtdconf_file.close()
        libvirtdconf_file = open(tmp_libvirtdconf_path, 'w')
        libvirtdconf_file.writelines(line_list)
        libvirtdconf_file.close()
        try:
            remote.copy_files_to(server_ip, 'scp', server_user,
                            server_pwd, "22", tmp_libvirtdconf_path,
                            libvirtd_conf_path)
        except remote.SCPError, e:
            raise ConnSCPError('AdminHost', tmp_libvirtdconf_path,
                                server_ip, libvirtd_conf_path, e)

        #restart libvirtd service on server
        try:
            utils_libvirtd.libvirtd_restart(server_ip=server_ip,
                                            server_user=server_user,
                                            server_pwd=server_pwd,)
        except utils_libvirtd.LibvirtdError, e:
            raise ConnServerRestartError(e)

    def client_setup(self):
        """
        setup private key and certificate file for client.

        (1).initialization for variables.
        (2).make a private key with certtool command.
        (3).prepare a info file.
        (4).make a certificate file with certtool command.
        (5).copy files to client.
        (6).edit /etc/hosts on client.
        """
        #initialize variables
        certtool = self.CERTTOOL
        tmp_dir = self.tmp_dir
        cakey_path = '%s/tcakey.pem' % tmp_dir
        cacert_path = '%s/cacert.pem' % tmp_dir
        clientkey_path = '%s/clientkey.pem' % tmp_dir
        clientcert_path = '%s/clientcert.pem' % tmp_dir
        clientinfo_path = '%s/client.info' % tmp_dir
        hosts_path = self.hosts_path
        tmp_hosts_path = '%s/hosts' % tmp_dir
        tmp_hosts_bak_path = '%s.bak' % tmp_hosts_path
        client_ip = self.client_ip
        client_user = self.client_user
        client_pwd = self.client_pwd

        #make a private key.
        cmd = "%s --generate-privkey > %s" % (certtool, clientkey_path)
        CmdResult = utils.run(cmd, ignore_status=True)
        if CmdResult.exit_status:
            raise ConnPrivKeyError(CmdResult.stderr)

        #prepare a info file to build clientcert.
        clientinfo_file = open(clientinfo_path, "w")
        clientinfo_file.write("organization = AUTOTEST.VIRT\n")
        clientinfo_file.write("cn = %s\n" % (self.client_cn))
        clientinfo_file.write("tls_www_client\n")
        clientinfo_file.write("encryption_key\n")
        clientinfo_file.write("signing_key\n")
        clientinfo_file.close()

        #make a client certificate file and a client key file.
        cmd = ("%s --generate-certificate --load-privkey %s \
               --load-ca-certificate %s --load-ca-privkey %s \
               --template %s --outfile %s" %
               (certtool, clientkey_path, cacert_path,
                cakey_path, clientinfo_path, clientcert_path))
        CmdResult = utils.run(cmd, ignore_status=True)
        if CmdResult.exit_status:
            raise ConnCertError(CmdResult.stderr)
        #scp cacert.pem, clientcert.pem and clientkey.pem to client.
        client_session = self.client_session
        cmd = "mkdir -p %s" % self.libvirt_pki_private_dir
        status, output = client_session.cmd_status_output(cmd)
        if status:
            raise ConnMkdirError(self.libvirt_pki_private_dir, output)

        scp_dict = {cacert_path:self.pki_CA_dir,
                    clientcert_path:self.libvirt_pki_dir,
                    clientkey_path:self.libvirt_pki_private_dir}

        for key in scp_dict:
            local_path = key
            remote_path = scp_dict[key]
            try:
                remote.copy_files_to(client_ip, 'scp', client_user,
                            client_pwd, '22', local_path, remote_path)
            except remote.SCPError, e:
                raise ConnSCPError('AdminHost', local_path,
                                        client_ip, remote_path, e)

        #edit /etc/hosts on client
        try:
            remote.copy_files_from(client_ip, 'scp', client_user,
                        client_pwd, '22', hosts_path, tmp_hosts_path)
        except remote.SCPError, e:
            raise ConnSCPError(client_ip, hosts_path,
                                'AdminHost', tmp_hosts_path, e)

        #copy backup file for recover.
        try:
            shutil.copy(tmp_hosts_path, tmp_hosts_bak_path)
        except OSError, e:
            raise ConnCopyError(tmp_hosts_path, tmp_hosts_bak_path)

        hosts_file = open(tmp_hosts_path, 'r')
        line_list = hosts_file.readlines()
        flag = False
        for index in range(len(line_list)):
            line = line_list[index]
            if not re.search(r"%s" % (self.server_cn), line):
                #no relation with the tls line
                continue
            else:
                line_list[index] = "%s %s\n" % (self.server_ip,
                                              self.server_cn)
                flag = True
                break
        if not flag is True:
            line_list.append("\n%s %s\n" % (self.server_ip,
                                            self.server_cn))
        hosts_file.close()
        hosts_file = open(tmp_hosts_path, 'w')
        hosts_file.writelines(line_list)
        hosts_file.close()
        try:
            remote.copy_files_to(client_ip, 'scp', client_user,
                    client_pwd, '22', tmp_hosts_path, hosts_path)
        except remote.SCPError, e:
            raise ConnSCPError('AdminHost', tmp_hosts_path,
                                        client_ip, hosts_path, e)
