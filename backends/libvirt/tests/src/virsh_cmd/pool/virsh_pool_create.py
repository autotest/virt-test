import os
import logging
from autotest.client.shared import error
from virttest import virsh, xml_utils, libvirt_storage, libvirt_xml


def pool_check(pool_name, pool_ins):
    """
    Check the pool from given pool xml.
    """
    if not pool_ins.is_pool_active(pool_name):
        logging.debug("Can't find the active pool: %s", pool_name)
        return False
    logging.info(pool_name)
    pool_type = libvirt_xml.PoolXML.get_type(pool_name)
    pool_detail = libvirt_xml.PoolXML.get_pool_details(pool_name)
    logging.debug("Pool detail: %s", pool_detail)
    return True


def run(test, params, env):
    """
    Test command: virsh pool-create.

    Create a libvirt pool from an XML file.
    1) Use xml file from test parameters to create pool.
    2) Dump the exist pool to create pool.
    3) Negatively create pool(invalid option, no file, invalid file, duplicate
       pool name, and create pool under readonly mode).
    """

    pool_xml = params.get("pool_create_xml_file")
    pool_name = params.get("pool_create_name")
    option = params.get("pool_create_extra_option", "")
    use_exist_pool = "yes" == params.get("pool_create_use_exist_pool", "no")
    exist_pool_name = params.get("pool_create_exist_pool_name", "default")
    undefine_exist_pool = "yes" == params.get(
        "pool_create_undefine_exist_pool", "no")
    readonly_mode = "yes" == params.get("pool_create_readonly_mode", "no")
    status_error = "yes" == params.get("status_error", "no")

    # Deal with each parameters
    # backup the exist pool
    pool_ins = libvirt_storage.StoragePool()
    if use_exist_pool:
        if not pool_ins.pool_exists(exist_pool_name):
            raise error.TestFail("Require pool: %s exist", exist_pool_name)
        backup_xml = libvirt_xml.PoolXML.backup_xml(exist_pool_name)
        pool_xml = backup_xml

    # Delete the exist pool
    start_pool = False
    if undefine_exist_pool:
        poolxml = libvirt_xml.PoolXML.new_from_dumpxml(exist_pool_name)
        poolxml.name = pool_name
        pool_xml = poolxml.xml
        if pool_ins.is_pool_active(exist_pool_name):
            start_pool = True
        if not pool_ins.delete_pool(exist_pool_name):
            raise error.TestFail("Delete pool: %s fail", exist_pool_name)

    # Create an invalid pool xml file
    if pool_xml == "invalid-pool-xml":
        tmp_xml = xml_utils.TempXMLFile()
        tmp_xml.write('"<pool><<<BAD>>><\'XML</name\>'
                      '!@#$%^&*)>(}>}{CORRUPTE|>!</pool>')
        tmp_xml.flush()
        pool_xml = tmp_xml.name
        logging.info(pool_xml)

    # Readonly mode
    ro_flag = False
    if readonly_mode:
        logging.debug("Readonly mode test")
        ro_flag = True

    # Run virsh test
    if os.path.isfile(pool_xml):
        logging.debug("Create pool from file:\n %s", open(pool_xml, 'r').read())
    try:
        cmd_result = virsh.pool_create(
            pool_xml,
            option,
            ignore_status=True,
            debug=True,
            readonly=ro_flag)
        err = cmd_result.stderr.strip()
        status = cmd_result.exit_status
        if not status_error:
            if status:
                raise error.TestFail(err)
            elif not pool_check(pool_name, pool_ins):
                raise error.TestFail("Pool check fail")
        elif status_error and status == 0:
            raise error.TestFail("Expect fail, but run successfully.")
    finally:
        # Recover env
        if pool_ins.is_pool_active(pool_name):
            virsh.pool_destroy(pool_name)
        if undefine_exist_pool and not pool_ins.pool_exists(exist_pool_name):
            virsh.pool_define(backup_xml)
            if start_pool:
                pool_ins.start_pool(exist_pool_name)
