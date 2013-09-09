"""
smartcard_setup.py - Used as a setup test for smartcard tests.

Before doing a remote viewer connection there is some setup required
for smartcard tests:

On the client, certs that will be put into the smartcard will need
to be generated.

"""
import logging
from virttest import utils_misc, utils_spice, aexpect
from autotest.client.shared import error


def run_smartcard_setup(test, params, env):
    """
    Simple setup test to create certs on the client to be passed to VM's
    smartcard.

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    # Get necessary params
    cert_list = params.get("gencerts").split(",")
    cert_db = params.get("certdb")
    self_sign = params.get("self_sign")
    cert_trustargs = params.get("trustargs")

    logging.debug("Cert List:")
    for cert in cert_list:
        logging.debug(cert)
        logging.debug(cert_trustargs)
        logging.debug("CN=" + cert)
        logging.debug(cert_db)

    client_vm = env.get_vm(params["client_vm"])
    client_vm.verify_alive()

    client_session = client_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)),
        username="root", password="123456")

    # generate a random string, used to create a random key for the certs
    randomstring = utils_misc.generate_random_string(2048)
    cmd = "echo '" + randomstring + "' > /tmp/randomtext.txt"
    output = client_session.cmd(cmd)
    #output2 = client_session.cmd("cat /tmp/randomtext.txt")
    utils_spice.wait_timeout(5)

    # for each cert listed by the test, create it on the client
    for cert in cert_list:
        cmd = "certutil "
        if self_sign:
            cmd += " -x "
        cmd += "-t '" + cert_trustargs + "' -S -s " + "'CN=" + cert
        cmd += "' -n '" + cert + "' -d " + cert_db
        cmd += " -z " + "/tmp/randomtext.txt"
        logging.debug(cmd)
        output = client_session.cmd(cmd)
        logging.debug("Cert Created: " + output)

    cmd = "certutil -L -d " + cert_db
    output = client_session.cmd(cmd)
    logging.info("Listing all certs on the client: " + output)

    # Verify that all the certs have been generated on the client
    for cert in cert_list:
        if not(cert in output):
            raise error.TestFail("Certificate %s not found" % cert)

    client_session.close()
