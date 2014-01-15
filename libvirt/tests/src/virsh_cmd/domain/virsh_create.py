import time
import commands
import logging
from autotest.client.shared import error
from virttest import aexpect, utils_test, virsh


def run(test, params, env):
    """
    Test virsh create command including parameters except --pass-fds
    because it is used in lxc.

    Basic test scenarios:
    1. --console with all combination(with other options)
    2. --autodestroy with left combination
    3. --paused itself
    """
    vm_name = params.get("main_vm")
    options = params.get("create_options", "")
    status_error = ("yes" == params.get("status_error", "no"))
    c_user = params.get("create_login_user", "root")
    readonly = params.get("readonly", False)
    if c_user == "root":
        c_passwd = params.get("password")
    else:
        c_passwd = params.get("create_login_password_nonroot")

    vm = env.get_vm(vm_name)
    if vm.exists():
        if vm.is_alive():
            vm.destroy()
        xmlfile = vm.backup_xml()
        vm.undefine()
    else:
        xmlfile = params.get("create_domain_xmlfile")
        if xmlfile is None:
            raise error.TestFail("Please provide domain xml file for create or"
                                 " existing domain name with main_vm = xx")
        #get vm name from xml file
        xml_cut = commands.getoutput("grep '<name>.*</name>' %s" % xmlfile)
        vm_name = xml_cut.strip(' <>').strip("name").strip("<>/")
        logging.debug("vm_name is %s", vm_name)
        vm = env.get_vm(vm_name)

    try:
        def create_status_check(vm):
            """
            check guest status
            1. if have options --paused: check status and resume
            2. check if guest is running after 1
            """
            # sleep to make sure guest is paused
            time.sleep(2)
            if "--paused" in options:
                if not vm.is_paused():
                    raise error.TestFail("Guest status is not paused with"
                                         "options %s, state is %s" %
                                         (options, vm.state()))
                else:
                    logging.info("Guest status is paused.")
                vm.resume()

            if vm.state() == "running":
                logging.info("Guest is running now.")
            else:
                raise error.TestFail("Fail to create guest, guest state is %s"
                                     % vm.state())

        def create_autodestroy_check(vm):
            """
            check if guest will disappear with --autodestroy
            """
            if vm.exists():
                raise error.TestFail("Guest still exist with options %s" %
                                     options)
            else:
                logging.info("Guest does not exist after session closed.")

        try:
            if status_error:
                output = virsh.create(xmlfile, options, readonly=readonly)
                if output.exit_status:
                    logging.info("Fail to create guest as expect:%s",
                                 output.stderr)
                if vm.state() == "running":
                    raise error.TestFail("Expect fail, but succeed indeed")
            elif "--console" in options:
                # Use session for console
                command = "virsh create %s %s" % (xmlfile, options)
                session = aexpect.ShellSession(command)
                # check domain status including paused and running
                create_status_check(vm)
                status = utils_test.libvirt.verify_virsh_console(
                    session, c_user, c_passwd, timeout=90, debug=True)
                if not status:
                    raise error.TestFail("Fail to verify console")

                session.close()
                # check if domain exist after session closed
                if "--autodestroy" in options:
                    create_autodestroy_check(vm)

            elif "--autodestroy" in options:
                # Use session for virsh interactive mode because
                # guest will be destroyed after virsh exit
                command = "virsh"
                session = aexpect.ShellSession(command)
                while True:
                    match, text = session.read_until_any_line_matches(
                        [r"Domain \S+ created from %s" % xmlfile, r"virsh # "],
                        timeout=10, internal_timeout=1)
                    if match == -1:
                        logging.info("Run create %s %s", xmlfile, options)
                        command = "create %s %s" % (xmlfile, options)
                        session.sendline(command)
                    elif match == -2:
                        logging.info("Domain created from %s", xmlfile)
                        break
                create_status_check(vm)
                logging.info("Close session!")
                session.close()
                # check if domain exist after session closed
                create_autodestroy_check(vm)
            else:
                # have --paused option or none options
                output = virsh.create(xmlfile, options)
                if output.exit_status:
                    raise error.TestFail("Fail to create domain:%s" %
                                         output.stderr)
                create_status_check(vm)

        except (aexpect.ShellError, aexpect.ExpectError), detail:
            log = session.get_output()
            session.close()
            vm.define(xmlfile)
            raise error.TestFail("Verify create failed:\n%s\n%s" %
                                 (detail, log))
    finally:
        #Guest recovery
        vm.define(xmlfile)
