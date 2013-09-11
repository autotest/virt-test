"""
rv_connect.py - connect with remote-viewer to remote target

Requires: binaries remote-viewer, Xorg, netstat
          Use example kickstart RHEL-6-spice.ks

"""
import logging
import sys
import socket
from virttest.aexpect import ShellStatusError
from virttest.aexpect import ShellProcessTerminatedError
from virttest import utils_net, utils_spice, remote, utils_misc
from autotest.client.shared import error


def str_input(client_vm, ticket):
    """
    sends spice_password trough vm.send_key()
    :param client_session - vm() object
    :param ticket - use params.get("spice_password")
    """
    logging.info("Passing ticket '%s' to the remote-viewer.", ticket)
    char_mapping = {":": "shift-semicolon",
                    ",": "comma",
                    ".": "dot",
                    "/": "slash",
                    "?": "shift-slash",
                    "=": "equal"}
    for character in ticket:
        if character in char_mapping:
            character = char_mapping[character]
        client_vm.send_key(character)

    client_vm.send_key("kp_enter")  # send enter


def print_rv_version(client_session, rv_binary):
    """
    prints remote-viewer and spice-gtk version available inside client_session
    :param client_session - vm.wait_for_login()
    :param rv_binary - remote-viewer binary
    """
    logging.info("remote-viewer version: %s",
                 client_session.cmd(rv_binary + " -V"))
    logging.info("spice-gtk version: %s",
                 client_session.cmd(rv_binary + " --spice-gtk-version"))


def launch_rv(client_vm, guest_vm, params):
    """
    Launches rv_binary with args based on spice configuration
    inside client_session on background.
    remote-viewer will try to connect from vm1 from vm2

    :param client_vm - vm object
    :param guest_vm - vm object
    :param params
    """
    rv_binary = params.get("rv_binary", "remote-viewer")
    host_ip = utils_net.get_host_ip_address(params)
    if guest_vm.get_spice_var("listening_addr") == "ipv6":
        host_ip = "[" + utils_misc.convert_ipv4_to_ipv6(host_ip) + "]"
    check_spice_info = params.get("spice_info")
    ssltype = params.get("ssltype")
    test_type = params.get("test_type")
    host_port = None
    full_screen = params.get("full_screen")
    disable_audio = params.get("disable_audio", "no")
    display = params.get("display")
    ticket = None
    ticket_send = params.get("spice_password_send")
    qemu_ticket = params.get("qemu_password")
    gencerts = params.get("gencerts")
    certdb = params.get("certdb")
    smartcard = params.get("smartcard")
    menu = params.get("rv_menu", None)
    # cmd var keeps final remote-viewer command line to be executed on client
    cmd = rv_binary + " --display=:0.0"

    # If qemu_ticket is set, set the password of the VM using the qemu-monitor
    if qemu_ticket:
        guest_vm.monitor.cmd("set_password spice %s" % qemu_ticket)
        logging.info("Sending to qemu monitor: set_password spice %s"
                     % qemu_ticket)

    client_session = client_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))

    if display == "spice":
        ticket = guest_vm.get_spice_var("spice_password")

        if guest_vm.get_spice_var("spice_ssl") == "yes":
            host_tls_port = guest_vm.get_spice_var("spice_tls_port")
            host_port = guest_vm.get_spice_var("spice_port")
            cacert = "%s/%s" % (guest_vm.get_spice_var("spice_x509_prefix"),
                                guest_vm.get_spice_var("spice_x509_cacert_file"))
            # cacert subj is in format for create certificate(with '/' delimiter)
            # remote-viewer needs ',' delimiter. And also is needed to remove
            # first character (it's '/')
            host_subj = guest_vm.get_spice_var("spice_x509_server_subj")
            host_subj = host_subj.replace('/', ',')[1:]
            if ssltype == "invalid_explicit_hs":
                host_subj = "Invalid Explicit HS"
            else:
                host_subj += host_ip

            # If it's invalid implicit, a remote-viewer connection
            # will be attempted with the hostname, since ssl certs were
            # generated with the ip address
            hostname = socket.gethostname()
            if ssltype == "invalid_implicit_hs":
                spice_url = " spice://%s?tls-port=%s\&port=%s" % (hostname,
                                                                  host_tls_port, host_port)
            else:
                spice_url = " spice://%s?tls-port=%s\&port=%s" % (host_ip,
                                                                  host_tls_port, host_port)

            if menu == "yes":
                line = spice_url
            else:
                cmd += spice_url

            cmd += " --spice-ca-file=%s" % cacert

            if params.get("spice_client_host_subject") == "yes":
                cmd += " --spice-host-subject=\"%s\"" % host_subj

            # client needs cacert file
            client_session.cmd("rm -rf %s && mkdir -p %s" % (
                               guest_vm.get_spice_var("spice_x509_prefix"),
                               guest_vm.get_spice_var("spice_x509_prefix")))
            remote.copy_files_to(client_vm.get_address(), 'scp',
                                 params.get("username"),
                                 params.get("password"),
                                 params.get("shell_port"),
                                 cacert, cacert)
        else:
            host_port = guest_vm.get_spice_var("spice_port")
            if menu == "yes":
                # line to be sent through monitor once r-v is started
                # without spice url
                line = "spice://%s?port=%s" % (host_ip, host_port)
            else:
                cmd += " spice://%s?port=%s" % (host_ip, host_port)

    elif display == "vnc":
        raise NotImplementedError("remote-viewer vnc")

    else:
        raise Exception("Unsupported display value")

    # Check to see if the test is using the full screen option.
    if full_screen == "yes":
        logging.info("Remote Viewer Set to use Full Screen")
        cmd += " --full-screen"

    if disable_audio == "yes":
        logging.info("Remote Viewer Set to disable audio")
        cmd += " --spice-disable-audio"

    # Check to see if the test is using a smartcard.
    if smartcard == "yes":
        logging.info("remote viewer Set to use a smartcard")
        cmd += " --spice-smartcard"

        if certdb is not None:
            logging.debug("Remote Viewer set to use the following certificate"
                          " database: " + certdb)
            cmd += " --spice-smartcard-db " + certdb

        if gencerts is not None:
            logging.debug("Remote Viewer set to use the following certs: " +
                          gencerts)
            cmd += " --spice-smartcard-certificates " + gencerts

    cmd = "nohup " + cmd + " &> /dev/null &"  # Launch it on background

    # Launching the actual set of commands
    try:
        print_rv_version(client_session, rv_binary)
    except ShellStatusError, ShellProcessTerminatedError:
        # Sometimes It fails with Status error, ingore it and continue.
        # It's not that important to have printed versions in the log.
        logging.debug("Ignoring a Status Exception that occurs from calling "
                      "print versions of remote-viewer or spice-gtk")

    logging.info("Launching %s on the client (virtual)", cmd)
    try:
        client_session.cmd(cmd)
    except ShellStatusError:
        logging.debug("Ignoring a status exception, will check connection of"
                      "remote-viewer later")

    # Send command line through monitor since r-v was started without spice url
    if menu == "yes":
        utils_spice.wait_timeout(1)
        str_input(client_vm, line)
        client_vm.send_key("tab")
        client_vm.send_key("tab")
        client_vm.send_key("tab")
        client_vm.send_key("kp_enter")

    # client waits for user entry (authentication) if spice_password is set
    # use qemu monitor password if set, else check if the normal password is
    # set
    if qemu_ticket:
        # Wait for remote-viewer to launch
        utils_spice.wait_timeout(5)
        str_input(client_vm, qemu_ticket)
    elif ticket:
        if ticket_send:
            ticket = ticket_send

        utils_spice.wait_timeout(5)  # Wait for remote-viewer to launch
        str_input(client_vm, ticket)

    utils_spice.wait_timeout(5)  # Wait for conncetion to establish
    is_rv_connected = True
    try:
        utils_spice.verify_established(
            client_vm, host_ip, host_port, rv_binary)
    except utils_spice.RVConnectError:
        if test_type == "negative":
            logging.info("remote-viewer connection failed as expected")
            if ssltype in ("invalid_implicit_hs", "invalid_explicit_hs"):
                # Check the qemu process output to verify what is expected
                qemulog = guest_vm.process.get_output()
                if "SSL_accept failed" in qemulog:
                    return
                else:
                    raise error.TestFail("SSL_accept failed not shown in qemu" +
                                         "process as expected.")
            is_rv_connected = False
        else:
            raise error.TestFail("remote-viewer connection failed")

    if test_type == "negative" and is_rv_connected:
        raise error.TestFail("remote-viewer connection was established when" +
                             " it was supposed to be unsuccessful")

    # Get spice info
    output = guest_vm.monitor.cmd("info spice")
    logging.debug("INFO SPICE")
    logging.debug(output)

    # Check to see if ipv6 address is reported back from qemu monitor
    if (check_spice_info == "ipv6"):
        logging.info("Test to check if ipv6 address is reported"
                     " back from the qemu monitor")
        # Remove brackets from ipv6 host ip
        if (host_ip[1:len(host_ip) - 1] in output):
            logging.info("Reported ipv6 address found in output from"
                         " 'info spice'")
        else:
            raise error.TestFail("ipv6 address not found from qemu monitor"
                                 " command: 'info spice'")
    else:
        logging.info("Not checking the value of 'info spice'"
                     " from the qemu monitor")

    # prevent from kill remote-viewer after test finish
    cmd = "disown -ar"
    client_session.cmd(cmd)


def run_rv_connect(test, params, env):
    """
    Simple test for Remote Desktop connection
    Tests expectes that Remote Desktop client (spice/vnc) will be executed
    from within a second guest so we won't be limited to Linux only clients

    The plan is to support remote-viewer at first place

    :param test: QEMU test object.  :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    guest_vm = env.get_vm(params["guest_vm"])
    guest_vm.verify_alive()
    guest_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))

    client_vm = env.get_vm(params["client_vm"])
    client_vm.verify_alive()
    client_session = client_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))

    utils_spice.wait_timeout(15)

    launch_rv(client_vm, guest_vm, params)

    client_session.close()
    guest_session.close()
