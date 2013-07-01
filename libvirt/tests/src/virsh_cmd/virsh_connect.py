import logging, os, re, shutil
from autotest.client.shared import error
from virttest import libvirt_vm, utils_libvirtd, virsh, utils_conn


class VshConnectError(Exception):
    """
    Error in connecting to uri.
    """
    def __init__(self, uri, output):
        Exception.__init__(self)
        self.uri = uri
        self.output = output

    def __str__(self):
        return str("Connect to %s Failed.\n"
                    "Output:%s"
                    % (self.uri,self.output))


def do_virsh_connect(uri, options, vsh_session, username=None,
                     password=None, prompt=r"virsh\s*[\#\>]\s*"):
    """
    Execute connect command in a virsh session and return the uri
    of this virsh session after connect.

    Throws a VshConnectError if execute virsh connect command failed.

    @param uri: argument of virsh connect command.
    @param options: options pass to command connect.
    @param vsh_session: the session which the connect command to be execute in.
    @param username: username to login remote host, it's necessary to connect
                   to remote uri.
    @param password: username to login remote host, it's necessary to connect
                   to remote uri.
    @param prompt: prompt of virsh session.

    @return: the uri of the virsh session after connect.

    """
    dargs = {}
    dargs["session_id"] = vsh_session.get_id()
    dargs["ignore_status"] = "True"
    try:
        result = virsh.connect(uri, options, **dargs)
    except Exception, e:
        raise VshConnectError(uri, e)

    if result.exit_status:
        raise VshConnectError(uri, result.stdout.rstrip())

    uri_result = virsh.canonical_uri(**dargs)
    logging.debug("uri after connect is %s." % uri_result)
    return uri_result


def run_virsh_connect(test, params, env):
    """
    Test command: virsh connect.
    """
    def unix_transport_setup():
        """
        """
        shutil.copy(libvirtd_conf_path, libvirtd_conf_bak_path)

        libvirtdconf_file = open(libvirtd_conf_path, 'r')
        line_list = libvirtdconf_file.readlines()
        conf_dict = {r'auth_unix_rw\s*=':'auth_unix_rw="none"\n',}
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
        libvirtdconf_file = open(libvirtd_conf_path, 'w')
        libvirtdconf_file.writelines(line_list)
        libvirtdconf_file.close()

        #restart libvirtd service
        utils_libvirtd.libvirtd_restart()

    def unix_transport_recover():
        """
        """
        if os.path.exists(libvirtd_conf_bak_path):
            shutil.copy(libvirtd_conf_bak_path, libvirtd_conf_path)
            utils_libvirtd.libvirtd_restart()

    #get the params from subtests.
    #params for general.
    connect_arg = params.get("connect_arg", "")
    connect_opt = params.get("connect_opt", "")
    status_error = params.get("status_error", "no")

    #params for transport connect.
    local_ip = params.get("local_ip", "ENTER.YOUR.LOCAL.IP")
    local_pwd = params.get("local_pwd", "ENTER.YOUR.LOCAL.ROOT.PASSWORD")
    transport_type = params.get("connect_transport_type", "local")
    transport = params.get("connect_transport", "ssh")
    client_ip = local_ip
    client_pwd = local_pwd
    server_ip = local_ip
    server_pwd = local_pwd

    #params special for tls connect.
    server_cn = params.get("connect_server_cn", "TLSServer")
    client_cn = params.get("connect_client_cn", "TLSClient")
    tls_listen = params.get("tls_listen", "yes")

    #params special for tcp connect.
    tcp_port = params.get("tcp_port", '16509')

    #params special for unix transport.
    libvirtd_conf_path = '/etc/libvirt/libvirtd.conf'
    libvirtd_conf_bak_path = '%s/libvirtd.conf.bak' % test.tmpdir

    #check the config
    if (connect_arg == "transport" and
                            transport_type == "remote" and
                            local_ip.count("ENTER")):
        raise error.TestNAError("Parameter local_ip is not configured"
                                                    "in remote test.")
    if (connect_arg == "transport" and
                            transport_type == "remote" and
                            local_pwd.count("ENTER")):
        raise error.TestNAError("Parameter local_pwd is not configured"
                                                    "in remote test.")
    if (connect_arg.count("lxc") and
                (not os.path.exists("/var/run/libvirt/lxc"))):
        raise error.TestNAError("Connect test of lxc:/// is not suggested on "
                                    "the host with no lxc driver.")
    if connect_arg.count("xen") and (not os.path.exists("/var/run/xend")):
        raise error.TestNAError("Connect test of xen:/// is not suggested on "
                                    "the host with no xen driver.")
    if (connect_arg.count("qemu") and
                (not os.path.exists("/var/run/libvirt/qemu"))):
        raise error.TestNAError("Connect test of qemu:/// is not suggested on "
                                    "the host with no qemu driver.")

    if connect_arg == "transport":
        #get the canonical uri on remote host.
        session = virsh.VirshSession("virsh", remote_ip=server_ip,
                                     remote_pwd=server_pwd)

        dargs = {}
        dargs["session_id"] = session.get_id()
        canonical_uri_type = virsh.driver(**dargs)
        session.close()

        if transport == "ssh":
            ssh_connection = utils_conn.SSHConnection(server_ip=server_ip,
                                        server_pwd=server_pwd,
                                        client_ip=client_ip,
                                        client_pwd=client_pwd,
                                        tmp_dir=test.tmpdir)
            try:
                ssh_connection.conn_check()
            except utils_conn.ConnectionError:
                ssh_connection.conn_setup()
                ssh_connection.conn_check()

            connect_uri = libvirt_vm.get_uri_with_transport(
                                        uri_type=canonical_uri_type,
                                        transport=transport, dest_ip=server_ip)
        elif transport == "tls":
            tls_connection = utils_conn.TLSConnection(server_ip=server_ip,
                                        server_pwd=server_pwd,
                                        client_ip=client_ip,
                                        client_pwd=client_pwd,
                                        server_cn = server_cn,
                                        client_cn=client_cn,
                                        tmp_dir=test.tmpdir)
            tls_connection.conn_setup()

            connect_uri = libvirt_vm.get_uri_with_transport(
                                        uri_type=canonical_uri_type,
                                        transport=transport, dest_ip=server_cn)
        elif transport == "tcp":
            tcp_connection = utils_conn.TCPConnection(server_ip=server_ip,
                                        server_pwd=server_pwd,
                                        tcp_port=tcp_port,
                                        tmp_dir=test.tmpdir)
            tcp_connection.conn_setup()

            connect_uri = libvirt_vm.get_uri_with_transport(
                                        uri_type=canonical_uri_type,
                                        transport=transport,
                                        dest_ip="%s:%s" % (server_ip, tcp_port))
        elif transport == "unix":
            unix_transport_setup()
            connect_uri = libvirt_vm.get_uri_with_transport(
                                        uri_type=canonical_uri_type,
                                        transport=transport,
                                        dest_ip="")
        else:
            raise error.TestNAError("Configuration of transport=%s is "
                                    "not recognized." % transport)
    else:
        connect_uri = connect_arg

    #build a virsh session to execute connect command.
    session = None
    try:
        try:
            session = virsh.VirshSession('virsh')
            uri = do_virsh_connect(connect_uri, connect_opt, session, "root",
                                   server_pwd)
            #connect sucessfully
            if status_error == "yes":
                raise error.TestFail("Connect sucessfully in the "
                                     "case expected to fail.")
            #get the expect uri when connect argument is ""
            if connect_uri == "":
                connect_uri = virsh.canonical_uri().split()[-1]

            logging.debug("expected uri is: %s" % connect_uri)
            logging.debug("actual uri after connect is: %s" % uri)
            if not uri == connect_uri:
                raise error.TestFail("Command exit normally but the uri is "
                                     "not setted as expected.")
        except VshConnectError, e:
            if status_error == "no":
                raise error.TestFail("Connect failed in the case expected"
                                     "to success.\n"
                                     "Error: %s" % e)
    finally:
        #clean up
        if session is not None:
            session.close()

        if transport == "unix":
            unix_transport_recover()
