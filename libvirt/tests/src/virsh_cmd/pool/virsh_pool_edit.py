import os
import logging
from autotest.client.shared import error
from virttest import virsh, libvirt_storage, data_dir, remote, aexpect
from virttest.libvirt_xml import pool_xml


def edit_pool(pool, edit_cmd):
    """
    Edit libvirt storage pool.

    :param pool: pool name or uuid.
    :param edit_cmd : edit commad line.
    """
    session = aexpect.ShellSession("sudo -s")
    try:
        session.sendline("virsh pool-edit %s" % pool)
        for cmd in edit_cmd:
            session.sendline(cmd)
        session.send('\x1b')
        session.send('ZZ')
        remote.handle_prompts(session, None, None, r"[\#\$]\s*$")
        session.close()
        logging.info("Succeed to do pool edit.")
    except (aexpect.ShellError, aexpect.ExpectError), details:
        log = session.get_output()
        session.close()
        raise error.TestFail("Failed to do pool edit: %s\n%s"
                             % (details, log))


def check_target_path(pool_name, edit_path):
    """
    Check if the pool target path equal to the given path.

    :param pool_name: name of the pool.
    :param edit_path: target path for pool edit.
    """
    target_path = pool_xml.PoolXML.new_from_dumpxml(pool_name).target_path
    if target_path == edit_path:
        logging.debug("New target path take effect.")
        return True
    else:
        logging.debug("New target path does not take effect.")
        return False


def run(test, params, env):
    """
    Test command: virsh pool-edit.

    Edit the XML configuration for a storage pool('dir' type as default).
    1) Edit the target path(mkdir).
    2) Delete uuid, edit name and target(define a new pool).
    """

    pool_ref = params.get("pool_ref", "name")
    pool_name = params.get("pool_name", "default")
    pool_uuid = params.get("pool_uuid", "")
    new_pool_name = params.get("new_pool_name", "new_edit_pool")
    pool_exist = "yes" == params.get("pool_exist", "yes")
    status_error = "yes" == params.get("status_error", "no")
    pool = pool_name
    # A flag for delete pool if it defined automatically
    del_pool_flag = False
    if pool_ref == "uuid":
        pool = pool_uuid
    if pool_exist and not status_error:
        pool = pool_name
        libvirt_pool = libvirt_storage.StoragePool()
        if libvirt_pool.pool_exists(pool_name):
            logging.debug("Find pool '%s' to edit.", pool_name)
            if not pool_uuid and pool_ref == "uuid":
                pool = libvirt_pool.get_pool_uuid(pool_name)
        else:
            logging.debug("Pool '%s' not exist, will define it automatically.")
            result = virsh.pool_define_as(pool_name, 'dir', '/tmp')
            if result.exit_status:
                raise error.TestFail("Fail to define pool '%s'" % pool_name)
            else:
                del_pool_flag = True
        try:
            ori_xml = pool_xml.PoolXML.backup_xml(pool_name)
            ori_poolxml = pool_xml.PoolXML()
            ori_poolxml.xml = ori_xml
            logging.debug("Before edit pool:")
            # format 2 positive tests
            edit_test1 = {}
            edit_test2 = {}
            # edit test 1: Edit target path
            edit_path1 = os.path.join(data_dir.get_tmp_dir(), "edit_pool")
            os.mkdir(edit_path1)
            edit_test1['type'] = "edit"
            edit_test1['edit_cmd'] = [":%s/<path>.*</<path>" +
                                      edit_path1.replace('/', '\/') + "<"]

            # edit test 2: Delete uuid, edit pool name and target path
            edit_path2 = os.path.join(data_dir.get_tmp_dir(), "new_pool")
            os.mkdir(edit_path2)
            edit_test2['type'] = "define"
            edit_cmd = []
            edit_cmd.append(":g/<uuid>/d")
            edit_cmd.append(":%s/<path>.*</<path>" +
                            edit_path2.replace('/', '\/') + "<")
            edit_cmd.append(":%s/<name>.*</<name>" + new_pool_name + "<")
            edit_test2['edit_cmd'] = edit_cmd
            # run test
            for edit_test in [edit_test1, edit_test2]:
                edit_pool(pool, edit_test['edit_cmd'])
                if edit_test['type'] == "edit":
                    edit_path = edit_path1
                    if libvirt_pool.is_pool_active(pool_name):
                        libvirt_pool.destroy_pool(pool_name)
                if edit_test['type'] == "define":
                    pool = new_pool_name
                    edit_path = edit_path2
                edit_xml = pool_xml.PoolXML.backup_xml(pool)
                edit_poolxml = pool_xml.PoolXML()
                edit_poolxml.xml = edit_xml
                logging.debug("After %s pool:", edit_test['type'])
                edit_poolxml.debug_xml()
                if check_target_path(pool, edit_path):
                    logging.info("Check pool target path pass.")
                else:
                    logging.debug("Check pool target path fail.")
                if not libvirt_pool.start_pool(pool):
                    raise error.TestFail("Fail to start pool after edit it.")
        finally:
            if libvirt_pool.pool_exists(new_pool_name):
                libvirt_pool.delete_pool(new_pool_name)
            libvirt_pool.delete_pool(pool_name)
            if not del_pool_flag:
                ori_poolxml.pool_define()
            os.rmdir(edit_path1)
            os.rmdir(edit_path2)
    elif not pool_exist and not status_error:
        raise error.TestFail("Conflict condition: pool not exist and expect "
                             "pool edit succeed.")
    else:
        # negative test
        output = virsh.pool_edit(pool)
        if output.exit_status:
            logging.info("Fail to do pool edit as expect: %s",
                         output.stderr.strip())
        else:
            raise error.TestFail("Expect fail but do pool edit succeed.")
