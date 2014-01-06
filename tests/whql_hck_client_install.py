import logging
import time
import os
from autotest.client.shared import error
from virttest import utils_misc, utils_test, remote
from virttest import rss_client

@error.context_aware
def run_whql_hck_client_install(test, params, env):
    """
    WHQL HCK client installation:
    1) Login to the guest and setup the domain env in it
    2) Install packages needed

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)


    server_address = params["server_address"]
    server_shell_port = int(params["server_shell_port"])
    server_username = params["server_username"]
    server_password = params["server_password"]
    client_username = params["client_username"]
    client_password = params["client_password"]
    server_domname = params["server_domname"]

    server_session = remote.remote_login("nc", server_address,
                                         server_shell_port, "", "",
                                         session.prompt, session.linesep)
    client_name =  session.cmd_output("echo %computername%").strip()
    install_timeout = float(params.get("install_timeout", 1800))

    services_installed = session.cmd_output("wmic service get")
    if "HCKcommunication" in services_installed:
        logging.info("HCK client already installed.")
        exit()

    # Join the server's workgroup
    if params.get("join_domain") == "yes":
        error.context("Join the workgroup", logging.info)
        cmd = ("netdom join %s /domain:%s /UserD:%s "
               "/PasswordD:%s" % (client_name, server_domname,
                                  client_username, client_password))
        session.cmd(cmd, timeout=600)

    error.context("Setting up auto logon for user '%s'" % client_username,
                  logging.info)
    cmd = ('reg add '
           '"HKLM\\Software\\Microsoft\\Windows NT\\CurrentVersion\\winlogon"'
           ' /v "%s" /d "%s" /t REG_SZ /f')
    session.cmd(cmd % ("AutoAdminLogon", "1"))
    session.cmd(cmd % ("DefaultUserName", server_username))
    session.cmd(cmd % ("DefaultPassword", server_password))

    session = vm.reboot(session)

    if params.get("pre_hck_install"):
        error.context("Install some program before install HCK client.",
                      logging.info)
        install_cmd = params.get("pre_hck_install")
        session.cmd(install_cmd, timeout=install_timeout)

    install_cmd = params["install_cmd"]
    error.context("Installing HCK client (timeout=%ds)" % install_timeout,
                  logging.info)
    session.cmd(install_cmd, timeout=install_timeout)
    reboot_timeout = login_timeout + 1500
    session = vm.reboot(session, timeout=reboot_timeout)
    session.close()
    server_session.close()
