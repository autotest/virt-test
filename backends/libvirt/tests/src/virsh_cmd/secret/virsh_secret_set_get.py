import os
import re
import base64
import logging
from tempfile import mktemp

from virttest import virsh
from autotest.client import utils
from autotest.client.shared import error
from virttest.libvirt_xml.secret_xml import SecretXML


_VIRT_SECRETS_PATH = "/etc/libvirt/secrets"


def check_secret(params):
    """
    Check specified secret value with decoded secret from
    _VIRT_SECRETS_PATH/$uuid.base64
    :params: the parameter dictionary
    """
    secret_decoded_string = ""

    uuid = params.get("secret_uuid")
    secret_string = params.get("secret_base64_no_encoded")
    change_parameters = params.get("change_parameters", "no")

    base64_file = os.path.join(_VIRT_SECRETS_PATH, "%s.base64" % uuid)

    if os.access(base64_file, os.R_OK):
        base64_encoded_string = open(base64_file, 'r').read().strip()
        secret_decoded_string = base64.b64decode(base64_encoded_string)
    else:
        logging.error("Did not find base64_file: %s", base64_file)
        return False

    if secret_string and secret_string != secret_decoded_string:
        logging.error("To expect %s value is %s",
                      secret_string, secret_decoded_string)
        return False

    return True


def create_secret_volume(params):
    """
    Define a secret of the volume
    :params: the parameter dictionary
    """
    private = params.get("secret_private", "no")
    desc = params.get("secret_desc", "my secret")
    ephemeral = params.get("secret_ephemeral", "no")
    usage_volume = params.get("secret_usage_volume")
    usage_type = params.get("secret_usage", "volume")

    if not usage_volume:
        raise error.TestFail("secret_usage_volume is required")

    sec_xml = """
<secret ephemeral='%s' private='%s'>
    <description>%s</description>
    <usage type='%s'>
        <volume>%s</volume>
    </usage>
</secret>
""" % (ephemeral, private, desc, usage_type, usage_volume)

    logging.debug("Prepare the secret XML: %s", sec_xml)
    sec_file = mktemp()
    xml_object = open(sec_file, 'w')
    xml_object.write(sec_xml)
    xml_object.close()

    result = virsh.secret_define(sec_file)
    status = result.exit_status

    # Remove temprorary file
    os.unlink(sec_file)

    if status:
        raise error.TestFail(result.stderr)


def get_secret_value(params):
    """
    Get the secret value
    :params: the parameter dictionary
    """
    base64_file = ""

    uuid = params.get("secret_uuid")
    options = params.get("secret_options")
    status_error = params.get("status_error", "no")

    result = virsh.secret_get_value(uuid, options)
    status = result.exit_status

    # Get secret XML by UUID
    secret_xml_obj = SecretXML()
    secret_xml = secret_xml_obj.get_secret_details_by_uuid(uuid)

    # If secret is private then get secret failure is an expected error
    if secret_xml.get("secret_private", "no") == "yes":
        status_error = "yes"

    if uuid:
        base64_file = os.path.join(_VIRT_SECRETS_PATH, "%s.base64" % uuid)

    # Check status_error
    if status_error == "yes":
        if status:
            logging.info("It's an expected %s", result.stderr)
        else:
            # Only raise error when the /path/to/$uuid.base64 file
            # doesn't exist
            if not os.access(base64_file, os.R_OK):
                raise error.TestFail("%d not a expected command "
                                     "return value", status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            # Check secret value
            if base64_file and check_secret(params):
                logging.info(result.stdout)
            else:
                raise error.TestFail("The secret value "
                                     "mismatch with result")


def set_secret_value(params):
    """
    Set the secet value
    :params: the parameter dictionary
    """
    uuid = params.get("secret_uuid")
    options = params.get("secret_options")
    status_error = params.get("status_error", "no")
    secret_string = params.get("secret_base64_no_encoded")

    # Encode secret string if it exists
    if secret_string:
        secret_string = base64.b64encode(secret_string)

    result = virsh.secret_set_value(uuid, secret_string, options)
    status = result.exit_status

    # Check status_error
    if status_error == "yes":
        if status:
            logging.info("It's an expected %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value", status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            # Check secret value
            if check_secret(params):
                logging.info(result.stdout)
            else:
                raise error.TestFail("The secret value "
                                     "mismatch with result")


def cleanup(params):
    """
    Cleanup secret and volume
    :params: the parameter dictionary
    """
    uuid = params.get("secret_uuid")
    usage_volume = params.get("secret_usage_volume")
    cleanup_volume = params.get("cleanup_volume", "no")
    undefine_secret = params.get("secret_undefine", "no")

    if usage_volume and cleanup_volume == "yes":
        os.unlink(usage_volume)

    if uuid and undefine_secret == "yes":
        result = virsh.secret_undefine(uuid)
        status = result.exit_status
        if status:
            raise error.TestFail(result.stderr)


def run(test, params, env):
    """
    Test set/get secret value for a volume

    1) Positive testing
       1.1) define or undefine a private or public secret
       1.2) get the public secret value
       1.3) set the private or public secret value
    2) Negative testing
       2.1) get private secret
       2.2) get secret without setting secret value
       2.3) get or set secret with invalid options
       2.4) set secret with doesn't exist UUID
    """

    # Run test case
    uuid = ""
    no_specified_uuid = False

    usage_volume = params.get("secret_usage_volume")
    define_secret = params.get("secret_define", "no")
    change_parameters = params.get("secret_change_parameters", "no")

    # If storage volume doesn't exist then create it
    if usage_volume and not os.path.isfile(usage_volume):
        utils.run("dd if=/dev/zero of=%s bs=1 count=1 seek=1M" % usage_volume)

    # Define secret based on storage volume
    if usage_volume and define_secret == "yes":
        create_secret_volume(params)

    # Get secret UUID from secret list
    if not no_specified_uuid:
        output = virsh.secret_list().stdout.strip()
        sec_list = re.findall(r"\n(.+\S+)\ +\S+\ +(.+\S+)", output)
        logging.debug("Secret list is %s", sec_list)
        if usage_volume and sec_list:
            for sec in sec_list:
                if usage_volume in sec[1]:
                    uuid = sec[0].lstrip()
                    no_specified_uuid = True
            logging.debug("Secret uuid is %s", uuid)

    uuid = params.get("secret_uuid", uuid)

    # Update parameters dictionary with automatically generated UUID
    if no_specified_uuid:
        params['secret_uuid'] = uuid

    # If only define secret then don't need to run the following cases

    # positive and negative testing #########

    if define_secret == "no":
        if change_parameters == "no":
            try:
                try:
                    get_secret_value(params)
                except error.TestFail, detail:
                    raise error.TestFail("Failed to get secret value.\n"
                                         "Detail: %s." % detail)
            finally:
                cleanup(params)
        else:
            try:
                try:
                    set_secret_value(params)
                except error.TestFail, detail:
                    raise error.TestFail("Failed to set secret value.\n"
                                         "Detail: %s." % detail)
            finally:
                cleanup(params)
