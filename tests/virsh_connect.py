import logging, os, re
from autotest.client.shared import error
from virttest import libvirt_vm, aexpect, virsh, remote, utils_conn


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
                     password=None, prompt=r"virsh\s*\#\s*"):
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
    dargs["session_id"] = vsh_session.a_id
    dargs["ignore_status"] = "True"
    if re.search("//..*/", uri):
        try:
            vsh_session.sendline("connect %s %s" % (uri, options))
            remote.handle_prompts(vsh_session, username, password, prompt)
        except Exception, e:
            raise VshConnectError(uri, e)
    else:
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
    #get the params from subtests.
    #params for general.
    libvirtd = params.get("libvirtd", "on")
    connect_arg = params.get("connect_arg", "")
    connect_opt = params.get("connect_opt", "")
    status_error = params.get("status_error", "no")
    
    #params for remote connect.
    remote_ip = params.get("remote_ip", "ENTER.YOUR.REMOTE.HOST.IP")
    remote_root_password = params.get("remote_root_password", 
                                      "ENTER.YOUR.REMOTE.ROOT.PASSWORD")
    local_ip = params.get("local_ip", "ENTER.YOUR.REMOTE.IP")
    local_root_password = params.get("local_root_password", 
                                     "ENTER.YOUR.LOCAL.ROOT.PASSWORD")
    transport = params.get("transport", "ssh")
    remote_libvirtd = params.get("remote_libvirtd", "on")
    
    #params special for tls connect.
    server_cn = params.get("server_cn", "TLSServer")
    client_cn = params.get("client_cn", "TLSClient")
    tls_listen = params.get("tls_listen", "yes")

    #check the config
    if connect_arg == "remote" and (remote_ip.count("ENTER.YOUR.") or
                                    remote_root_password.count("ENTER.YOUR") or
                                    local_ip.count("ENTER.YOUR")or
                                    local_root_password.count("ENTER.YOUR")):
        raise error.TestNAError("Remote test parameters not configured")
    if (connect_arg.count("lxc") and 
                (not os.path.exists("/var/run/libvirt/lxc"))):
        raise error.TestNAError("Connect test of lxc:/// is not suggested on \
                                    the host with no lxc driver.")
    if connect_arg.count("xen") and (not os.path.exists("/var/run/xend")):
        raise error.TestNAError("Connect test of xen:/// is not suggested on \
                                    the host with no xen driver.")
    if (connect_arg.count("qemu") and 
                (not os.path.exists("/var/run/libvirt/qemu"))):
        raise error.TestNAError("Connect test of qemu:/// is not suggested on \
                                    the host with no qemu driver.")
    
    #prepare before do connect 
    if libvirtd == "on" and (not os.path.exists("/var/run/libvirtd.pid")):
        libvirt_vm.libvirtd_start()
    elif libvirtd == "off" and (os.path.exists("/var/run/libvirtd.pid")):
        libvirt_vm.libvirtd_stop()
    elif (not libvirtd == "on") and (not libvirtd == "off"):
        raise error.TestNAError("Configuration of libvirtd=%s is \
                                not recognized." % libvirtd)
    else:
        pass

    if connect_arg == "remote":
        #get the canonical uri on remote host.
        session = virsh.VirshSession("virsh", remote_ip=remote_ip, 
                                     remote_pwd=remote_root_password)

        dargs = {}
        dargs["session_id"] = session.a_id
        canonical_uri = virsh.canonical_uri(**dargs)

        #build the remote uri to connect
        uri_partitions = canonical_uri.partition(":")
        uri_type = uri_partitions[0]
        uri_colon = uri_partitions[1]
        uri_dest = uri_partitions[2]

        if transport == "ssh":
            remote_uri_type = uri_type+"+ssh"
            remote_uri_colon = uri_colon
            dest_partitions = uri_dest.partition("//")
            remote_uri_dest = (dest_partitions[0]+dest_partitions[1]+
                              remote_ip+dest_partitions[2])
        elif transport == "tls":
            tls_connection = utils_conn.TLSConnection(server_ip=remote_ip, 
                                        server_pwd=remote_root_password, 
                                        client_ip=local_ip, 
                                        client_pwd=local_root_password, 
                                        server_cn = server_cn, 
                                        client_cn=client_cn)
            tls_connection.conn_setup()
            remote_uri_type = uri_type+"+tls"
            remote_uri_colon = uri_colon
            dest_partitions = uri_dest.partition("//")
            remote_uri_dest = (dest_partitions[0]+dest_partitions[1]+
                                        server_cn+dest_partitions[2])
        else:
            raise error.TestNAError("Configuration of transport=%s is \
                                    not recognized." % transport)

        connect_uri = (remote_uri_type+remote_uri_colon+remote_uri_dest)

    else:
        connect_uri = connect_arg

    #build a virsh session to execute connect command.
    try:
        session = virsh.VirshSession('virsh')
        uri = do_virsh_connect(connect_uri, connect_opt, session, "root", 
                               remote_root_password)
        session.close()
        #connect sucessfully
        if status_error == "yes":
            raise error.TestFail("Connect sucessfully in the \
                                 case expected to fail.")
        #get the expect uri when connect argument is ""
        if connect_uri == "":
            connect_uri = virsh.canonical_uri().split()[-1]

        logging.debug("expected uri is: %s" % connect_uri)
        logging.debug("actual uri after connect is: %s" % uri)
        if not uri == connect_uri:
            raise error.TestFail("Command exit normally but the uri is \
                                 not setted as expected.")
    except VshConnectError, e:
        if status_error == "no":
            logging.debug("error:%s." % e)
            raise error.TestFail("Connect failed in the case expected \
                                 to success.")
    except aexpect.ShellStatusError, e:
        if libvirtd == "off":
            pass
        else:
            logging.debug("error:%s." % e)
            raise error.TestFail("Initialization of VirshSession failed \
                                 with libvirtd on.")
    finally:
        #clean up
        if libvirtd == "off":
            libvirt_vm.libvirtd_start()
