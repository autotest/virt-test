"""
connection tools to manage kinds of connection.
"""

import signal, logging, time, os, shutil, re
from autotest.client import utils, os_dep
from virttest import aexpect, propcan, remote

class ConnectionError(Exception):
    """
    The base error in connection.
    """
    pass

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

class TLSError(ConnectionError):
    """
    Base Error in TLS connection.
    """
    pass

class TLSSetupError(TLSError):
    """
    Error in setup TLS connection.
    """
    pass

class TLSCheckError(TLSError):
    """
    Error in check TLS connection.
    """
    pass

class TLSSetupPrivKeyError(TLSSetupError):
    """
    Error in building private key with certtool command.
    """
    def __init__(self, key, output):
        TLSSetupError.__init__(self)
        self.key = key
        self.output = output
    
    def __str__(self):
        return ("Failed to build private key file(%s).\n"
               "output: %s .\n" % (self.key, self.output))

class TLSSetupCertError(TLSSetupError):
    """
    Error in building certificate file with certtool command.
    """
    def __init__(self, cert, output):
        TLSSetupError.__init__(self)
        self.cert = cert
        self.output = output
    
    def __str__(self):
        return ("Failed to build certificate file (%s).\n"
               "output: %s .\n" % (self.cert, self.output))

class TLSSetupMkdirError(TLSSetupError):
    """
    Error in making directory.
    """
    def __init__(self, dir, output):
        TLSSetupError.__init__(self)
        self.dir = dir
        self.output = output

    def __str__(self):
        return ("Failed to make directory %s \n"
               "output: %s.\n" % (self.dir, self.output))

class TLSSCPError(TLSSetupError):
    """
    Base error in SCP.
    """
    def __init__(self, filename, e):
        TLSSetupError.__init__(self)
        self.filename = filename
        self.e = e

class TLSSCPClientError(TLSSCPError):
    """
    Error in coping file to client.
    """
    def __str__(self):
        return ("Failed scp %s to client.\n"
               "error: %s." % (self.filename, self.e))

class TLSSCPServerError(TLSSCPError):
    """
    Error in coping file to server.
    """
    def __str__(self):
        return ("Failed scp %s to Server.\n"
               "error: %s." % (self.filename, self.e))

class TLSSetupClientEditHostsConfigError(TLSSetupError):
    """
    Error in editing config file /etc/hosts on client.
    """
    def __init__(self, output):
        TLSSetupError.__init__(self)
        self.output = output
    def __str__(self):
        return ("Failed to edit /etc/hosts on client.\n"
               "output: %s.\n" % (self.output))

class TLSSetupServerConfigError(TLSSetupError):
    """
    Error in editing config file /etc/sysconfig/libvirtd on server.
    """
    def __init__(self, output):
        TLSSetupError.__init__(self)
        self.output = output
    def __str__(self):
        return ("Failed to edit /etc/sysconfig/libvirtd on server.\n"
               "output: %s.\n" % (self.output))

class TLSSetupServerRestartError(TLSSetupError):
    """
    Error in restarting libvirtd on server.
    """
    def __init__(self, output):
        TLSSetupError.__init__(self)
        self.output = output
    def __str__(self):
        return ("Failed to restart libvirtd service on server.\n"
               "output: %s.\n" % (self.output))

class TLSCheckFailedError(TLSCheckError):
    """
    Error in checking TLS connection.
    """
    def __init__(self, e):
        TLSSetupError.__init__(self)
        self.e = e
    def __str__(self):
        return ("Failed to check connection between server and client.\n"
               "Error: %s.\n" % (self.e))
    

class ConnectionBase(propcan.PropCanBase):
    """
    Base class of a connection between server and client.
    """
    __slots__ = ('server_ip', 'server_user', 'server_pwd',
                 'client_ip', 'client_user', 'client_pwd',
                 'server_session_id', 'client_session_id')

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
        super(ConnectionBase, self).__init__(init_dict)

    def __del__(self):
        """
        Clean up any leftover sessions
        """
        self.close_session()

    def close_session(self):
        """
        If some session exists, close it down.
        """
        session_id_list = ['client_session_id', 'server_session_id']
        for session_id_key in session_id_list:
            try:
                session_id = self.dict_get(session_id_key)
                if session_id:
                    try:
                        existing = aexpect.ShellSession(a_id=session_id)
                        self.dict_del(session_id_key)
                    except aexpect.ShellStatusError:
                        self.dict_del(session_id_key)
                        continue 
                    if existing.is_alive():
                        existing.close()
                        if existing.is_alive():
                            existing.close(sig=signal.SIGTERM)
                        self.dict_del(session_id_key)
            except KeyError:
                continue 

    def conn_setup(self):
        """
        waiting for implemented by subclass.
        """
        pass

    def get_client_session(self):
        """
        If the client session exists,return it.
        else create a session to client and set client_session_id.
        """
        try:
            client_session_id = self.dict_get('client_session_id')
        except KeyError:
            client_session_id = None
        if not client_session_id is None:
            client_session = aexpect.ShellSession(a_id=client_session_id)
            return client_session

        transport = 'ssh'
        host = self.get('client_ip')
        port = 22
        username = self.get('client_user')
        password = self.get('client_pwd')
        prompt = '#'
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

        session_id = client_session.a_id
        self.dict_set('client_session_id', session_id)
        return client_session

    def get_server_session(self):
        """
        If the server session exists,return it.
        else create a session to server and set server_session_id.
        """
        try:
            server_session_id = self.dict_get('server_session_id')
        except KeyError:
            server_session_id = None
        if not server_session_id is None:
            server_session = aexpect.ShellSession(a_id=server_session_id)
            return server_session

        transport = 'ssh'
        host = self.get('server_ip')
        port = 22
        username = self.get('server_user')
        password = self.get('server_pwd')
        prompt = '#'
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

        session_id = server_session.a_id
        self.dict_set('server_session_id', session_id)
        return server_session
        

class TLSConnection(ConnectionBase):
    """
    Connection of TLS transport.
    """
    __slots__ = ConnectionBase.__slots__+('server_cn', 'client_cn', 
                                 'CERTTOOL', 'tmp_dir', 'pki_CA_dir',
                                 'libvirt_pki_dir', 'libvirt_pki_private_dir')
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
        #check and set CERTTOOL in slots
        try:
            CERTTOOL = os_dep.command("certtool")
        except ValueError:
            logging.warning("certtool executable not set or found on path, "
                            "TLS connection will not setup normally")
            CERTTOOL = '/bin/true'
        self.dict_set('CERTTOOL', CERTTOOL)
        
        #make a tmp dir as a workspace
        current_time = time.time()
        tmp_dir = "/tmp/%s" % current_time
        os.mkdir(tmp_dir)
        self.dict_set('tmp_dir', tmp_dir)
        #set some pki related dir values
        self.dict_set('pki_CA_dir', '/etc/pki/CA/')
        self.dict_set('libvirt_pki_dir', '/etc/pki/libvirt/')
        self.dict_set('libvirt_pki_private_dir', '/etc/pki/libvirt/private/')

    def __del__(self):
        """
        remove the tmp directory built in init func.
        """
        try:
            tmp_dir = self.dict_get('tmp_dir')
        except KeyError:
            return
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        super(TLSConnection, self).__del__()
            
    def conn_setup(self):
        """
        setup a TLS connection between server and client.
        At first check the certtool needed to setup.
        Then call some setup functions to complete connection setup.
        """
        if self.dict_get('CERTTOOL') == '/bin/true':
            raise ConnToolNotFoundError("No certtool is available to \
                                            setup TLS verification.")

        self.CA_setup()
        self.server_setup()
        self.client_setup()


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
        certtool = self.dict_get('CERTTOOL')
        tmp_dir = self.dict_get('tmp_dir')
        cakey_path = '%s/tcakey.pem' % tmp_dir
        cainfo_path = '%s/ca.info' % tmp_dir
        cacert_path = '%s/cacert.pem' % tmp_dir

        #make a private key
        cmd = "%s --generate-privkey > %s " % (certtool, cakey_path)
        CmdResult = utils.run(cmd, ignore_status=True)
        if CmdResult.exit_status:
            raise TLSSetupPrivKeyError(CmdResult.stderr)
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
            raise TLSSetupCertError(CmdResult.stderr)


    def server_setup(self):
        """
        setup private key and certificate file for server.

        (1).initialization for variables.
        (2).make a private key with certtool command.
        (3).prepare a info file.
        (4).make a certificate file with certtool command.
        (5).copy files to server.
        (6).edit /etc/sysconfig/libvirtd on server.
        (7).restart libvirtd service on server.
        """
        #initialize variables
        certtool = self.dict_get('CERTTOOL')
        tmp_dir = self.dict_get('tmp_dir')
        cakey_path = '%s/tcakey.pem' % tmp_dir
        cacert_path = '%s/cacert.pem' % tmp_dir
        serverkey_path = '%s/serverkey.pem' % tmp_dir
        servercert_path = '%s/servercert.pem' % tmp_dir
        serverinfo_path = '%s/server.info' % tmp_dir
        sysconfig_libvirtd_path = '/etc/sysconfig/libvirtd'
        tmp_syslibvirtd_path = '%s/libvirtd' % tmp_dir

        #make a private key
        cmd = "%s --generate-privkey > %s" % (certtool, serverkey_path)
        CmdResult = utils.run(cmd, ignore_status=True)
        if CmdResult.exit_status:
            raise TLSSetupPrivKeyError(CmdResult.stderr)

        #prepare a info file to build servercert and serverkey
        serverinfo_file = open(serverinfo_path, "w")
        serverinfo_file.write("organization = AUTOTEST.VIRT\n")
        serverinfo_file.write("cn = %s\n" % (self.dict_get('server_cn')))
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
            raise TLSSetupCertError(CmdResult.stderr)

        #scp cacert.pem, servercert.pem and serverkey.pem to server.
        server_session = self.get_server_session()
        cmd = "mkdir -p %s" % self.get('libvirt_pki_private_dir')
        status, output = server_session.cmd_status_output(cmd)
        if status:
            raise TLSSetupMkdirError(output)

        scp_dict = {cacert_path:self.get('pki_CA_dir'),
                    servercert_path:self.get('libvirt_pki_dir'), 
                    serverkey_path:self.get('libvirt_pki_private_dir')}

        for key in scp_dict:
            local_path = key
            remote_path = scp_dict[key]
            try:
                remote.copy_files_to(self.get('server_ip'), 'scp', 
                                     self.get('server_user'),
                                     self.get('server_pwd'), '22', 
                                     local_path, remote_path)
            except remote.SCPError, e:
                raise TLSSCPServerError(local_path, e)
        
        #edit the /etc/sysconfig/libvirtd to add --listen args in libvirtd
        try:
            remote.copy_files_from(self.get('server_ip'), 'scp', 
                                   self.get('server_user'), 
                                   self.get('server_pwd'), '22', 
                                   sysconfig_libvirtd_path, 
                                   tmp_syslibvirtd_path)
        except remote.SCPError, e:
            raise TLSSCPServerError(sysconfig_libvirtd_path, e)
        syslibvirtd_file = open(tmp_syslibvirtd_path, 'r')
        line_list = syslibvirtd_file.readlines()
        flag = False
        for index in range(len(line_list)):
            line = line_list[index]
            if not re.search(r"LIBVIRTD_ARGS\s*=\s*\"\s*--listen\s*\"", line):
                continue
            if (line.count('#') and 
                    (line.index('#') < line.index('LIBVIRTD_ARGS'))):
                line_list[index] = "LIBVIRTD_ARGS=\"--listen\""
            flag = True
            break
        if not flag is True:
            line_list.append("LIBVIRTD_ARGS=\"--listen\"")

        syslibvirtd_file.close()
        syslibvirtd_file = open(tmp_syslibvirtd_path, 'w')
        syslibvirtd_file.writelines(line_list)
        syslibvirtd_file.close()
        try:
            remote.copy_files_to(self.get('server_ip'), 'scp', 
                                 self.get('server_user'), 
                                 self.get('server_pwd'), '22', 
                                 tmp_syslibvirtd_path,
                                 sysconfig_libvirtd_path)
        except remote.SCPError, e:
            raise TLSSCPServerError(tmp_syslibvirtd_path, e)
        
        #restart libvirtd service on server
        cmd = "service libvirtd restart"
        status, output = server_session.cmd_status_output(cmd)
        if status:
            raise TLSSetupServerRestartError(output)

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
        certtool = self.dict_get('CERTTOOL')
        tmp_dir = self.dict_get('tmp_dir')
        cakey_path = '%s/tcakey.pem' % tmp_dir
        cacert_path = '%s/cacert.pem' % tmp_dir
        clientkey_path = '%s/clientkey.pem' % tmp_dir
        clientcert_path = '%s/clientcert.pem' % tmp_dir
        clientinfo_path = '%s/client.info' % tmp_dir
        hosts_path = '/etc/hosts'
        tmp_hosts_path = '%s/hosts' % tmp_dir

        #make a private key.
        cmd = "%s --generate-privkey > %s" % (certtool, clientkey_path)
        CmdResult = utils.run(cmd, ignore_status=True)
        if CmdResult.exit_status:
            raise TLSSetupPrivKeyError(CmdResult.stderr)

        #prepare a info file to build clientcert.
        clientinfo_file = open(clientinfo_path, "w")
        clientinfo_file.write("organization = AUTOTEST.VIRT\n")
        clientinfo_file.write("cn = %s\n" % (self.dict_get('client_cn')))
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
            raise TLSSetupCertError(CmdResult.stderr)
        #scp cacert.pem, clientcert.pem and clientkey.pem to client.
        client_session = self.get_client_session()
        cmd = "mkdir -p %s" % self.get('libvirt_pki_private_dir')
        status, output = client_session.cmd_status_output(cmd)
        if status:
            raise TLSSetupMkdirError(output)

        scp_dict = {cacert_path:self.get('pki_CA_dir'),
                    clientcert_path:self.get('libvirt_pki_dir'), 
                    clientkey_path:self.get('libvirt_pki_private_dir')}

        for key in scp_dict:
            local_path = key
            remote_path = scp_dict[key]
            try:
                remote.copy_files_to(self.get('client_ip'), 'scp', 
                                     self.get('client_user'),
                                     self.get('client_pwd'), '22', 
                                     local_path, remote_path)
            except remote.SCPError, e:
                raise TLSSCPClientError(local_path, e)

        #edit /etc/hosts on client 
        try:
            remote.copy_files_from(self.get('client_ip'), 'scp', 
                                   self.get('client_user'),
                                   self.get('client_pwd'), '22', 
                                   hosts_path, tmp_hosts_path)
        except remote.SCPError, e:
            raise TLSSCPClientError(hosts_path, e)

        hosts_file = open(tmp_hosts_path, 'r')
        line_list = hosts_file.readlines()
        flag = False
        for index in range(len(line_list)):
            line = line_list[index]
            if not re.search(r"%s" % (self.dict_get('server_cn')), line):
                #no relation with the tls line
                continue
            else:
                line_list[index] = "%s %s" % (self.dict_get('server_ip'), 
                                              self.dict_get('server_cn'))
                flag = True
                break
        if not flag is True:
            line_list.append("\n%s %s\n" % (self.dict_get('server_ip'), 
                                            self.dict_get('server_cn')))
        hosts_file.close()
        hosts_file = open(tmp_hosts_path, 'w')
        hosts_file.writelines(line_list)
        hosts_file.close()
        try:
            remote.copy_files_to(self.get('client_ip'), 'scp', 
                                 self.get('client_user'), 
                                 self.get('client_pwd'), '22', 
                                 tmp_hosts_path, hosts_path)
        except remote.SCPError, e:
            raise TLSSCPClientError(tmp_hosts_path, e)
