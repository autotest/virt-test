import logging
import re
import os
import shutil
from autotest.client.shared import error
from virttest import virsh, utils_libvirtd


def run(test, params, env):
    """
    Test the virsh pool commands

    (1) Define a 'dir' type pool(temp) and check for success
    (2) Undefine the pool and check for success
    (3) Repeat Step1
    (4) Start the pool(temp) and check for success
    (5) Check on pool list whether the start is active and autostart is 'no'
    (6) Mark the pool(temp) for autostart and check for the success
    (7) Check on pool-list whether autostart is 'yes'
    (7.a) Restart the libvirt service
    (7.b) Check on pool-list whether autostart is still 'yes'
    (8) Undefine the pool(temp) and check for the proper error message
    (9) Create the volume(tmp) on the pool(temp) anc check for success
    (10) Destroy the pool(temp) and check for success
    (11) Check volume list on pool(temp) and check for failure
    (12) Repeat Step4
    (13) Check volume list on pool(temp) and check for volume(tmp)
    (14) Delete the volume(tmp) on pool(temp)
    (15) Check volume list on pool(temp) and check for volume(tmp) not present
    (16) Destroy the pool(temp) and check for success
    (17) Undefine the pool(temp) and check for success
    TODO: To support the tests for multiple pool types
    TODO: Add more negative cases during libvirt service stopped
    TODO: Test autostart of the pool after system reboot
    """

    def check_list_state(pool_name, state="active"):
        """
        Check pool from the list
        """

        found = False
        # Get the list stored in a variable
        output = virsh.pool_list(option="--all", ignore_status=True)
        if output.exit_status != 0:
            error.TestFail("Virsh pool list command failed:\n%s" %
                           output.stdout)
        result = re.findall(r"(\w+)\s+(\w+)\s+(\w+)", str(output.stdout))
        for item in result:
            if pool_name in item[0]:
                found = True
                if not state == item[1]:
                    logging.debug("State: %s of a given pool: %s"
                                  " is not shown in the list", state, pool_name)
                    return False
        if found:
            return True
        else:
            logging.debug("Pool: %s is not found in the list", pool_name)
            return False

    def check_list_autostart(pool_name, autostart="no"):
        """
        Check pool from the list
        """

        found = False
        # Get the list stored in a variable
        output = virsh.pool_list(option="--all", ignore_status=True)
        if output.exit_status != 0:
            error.TestFail("Virsh pool list command failed:\n%s" %
                           output.stdout)
        result = re.findall(r"(\w+)\s+(\w+)\s+(\w+)", str(output))
        for item in result:
            if pool_name in item[0]:
                found = True
                if not autostart in item[2]:
                    raise error.TestFail("%s pool shouldn't be marked as "
                                         "autostart=%s", item[0], item[2])
        if found:
            return True
        else:
            logging.debug("Pool: %s is not found in the list", pool_name)
            return False

    def check_vol_list(vol_name, pool_name, pool_target):
        """
        Check volume from the list
        """

        found = False
        # Get the volume list stored in a variable
        output = virsh.vol_list(pool_name, ignore_status=True)
        if output.exit_status != 0:
            return False

        result = re.findall(r"(\w+)\s+(%s/%s)" % (pool_target, vol_name),
                            str(output.stdout))
        for item in result:
            if vol_name in item[0]:
                found = True
        if found:
            return True
        else:
            return False

    def define_pool(pool_name, pool_type, pool_target):
        """
        To define a pool
        """
        if 'dir' in pool_type:
            try:
                os.makedirs(pool_target)
            except OSError, details:
                raise error.TestFail("Check the target path:\n%s" % details)

            result = virsh.pool_define_as(pool_name, pool_type, pool_target,
                                          ignore_status=True)
            if result.exit_status != 0:
                raise error.TestFail("Command virsh pool-define-as"
                                     "failed:\n%s" % result.stdout)
            else:
                logging.debug("%s type pool: %s defined successfully",
                              pool_type, pool_name)
        else:
            raise error.TestFail("pool type %s has not yet been"
                                 "supported in the test" % pool_type)

    # Initialize the variables
    pool_name = params.get("pool_name")
    pool_type = params.get("pool_type")
    pool_target = params.get("pool_target")
    if os.path.dirname(pool_target) is "":
        pool_target = os.path.join(test.tmpdir, pool_target)
    vol_name = params.get("vol_name")

    logging.info("\n\tPool Name: %s\n\tPool Type: %s\n\tPool Target: %s\n\t"
                 "Volume Name:%s", pool_name, pool_type,
                 pool_target, vol_name)
    # Run Testcase
    try:
        # Step (1)
        define_pool(pool_name, pool_type, pool_target)

        # Step (2)
        result = virsh.pool_undefine(pool_name, ignore_status=True)
        if result.exit_status != 0:
            raise error.TestFail("Command virsh pool-undefine failed:\n%s" %
                                 result.stdout)
        else:
            logging.debug("Pool: %s successfully undefined", pool_name)
            shutil.rmtree(pool_target)

        # Step (3)
        define_pool(pool_name, pool_type, pool_target)

        # Step (4)
        result = virsh.pool_start(pool_name, ignore_status=True)
        if result.exit_status != 0:
            raise error.TestFail("Command virsh pool-start failed:\n%s" %
                                 result.stdout)
        else:
            logging.debug("Pool: %s successfully started", pool_name)

        # Step (5)

        if not check_list_state(pool_name, "active"):
            raise error.TestFail("State of the pool: %s is marked inactive"
                                 "instead of active" % pool_name)
        if not check_list_autostart(pool_name, "no"):
            raise error.TestFail("Autostart of the pool: %s marked as yes"
                                 "instead of no" % pool_name)

        # Step (6)
        result = virsh.pool_autostart(pool_name, ignore_status=True)
        if result.exit_status != 0:
            raise error.TestFail("Command virsh autostart is failed:\n%s" %
                                 result.stdout)
        else:
            logging.debug("Pool: %s marked for autostart successfully",
                          pool_name)

        # Step (7)
        if not check_list_state(pool_name, "active"):
            raise error.TestFail("State of pool: %s marked as inactive"
                                 "instead of active" % pool_name)
        if not check_list_autostart(pool_name, "yes"):
            raise error.TestFail("Autostart of pool: %s marked as no"
                                 "instead of yes" % pool_name)

        # Step (7.a)
        utils_libvirtd.libvirtd_stop()
        # TODO: Add more negative cases after libvirtd stopped
        utils_libvirtd.libvirtd_start()

        # Step (7.b)
        if not check_list_state(pool_name, "active"):
            raise error.TestFail("State of pool: %s marked as inactive"
                                 "instead of active" % pool_name)
        if not check_list_autostart(pool_name, "yes"):
            raise error.TestFail("Autostart of pool: %s marked as no"
                                 "instead of yes" % pool_name)

        # Step (8)
        result = virsh.pool_undefine(pool_name, ignore_status=True)
        if result.exit_status == 0:
            raise error.TestFail("Command virsh pool-undefine succeeded"
                                 " with pool still active and running")
        else:
            logging.debug("Active pool: %s undefine failed as expected",
                          pool_name)

        # Step (9)
        result = virsh.vol_create_as(vol_name, pool_name, "1048576",
                                     "1048576", "raw", ignore_status=True)
        if result.exit_status != 0:
            raise error.TestFail("Command virsh vol-create-as failed:\n%s" %
                                 result.stdout)
        else:
            logging.debug("Volume: %s successfully created on pool: %s",
                          vol_name, pool_name)

        if not check_vol_list(vol_name, pool_name, pool_target):
            raise error.TestFail("Volume %s is not found in the "
                                 "output of virsh vol-list" % vol_name)

        # Step (10)
        if not virsh.pool_destroy(pool_name):
            raise error.TestFail("Command virsh pool-destroy failed")
        else:
            logging.debug("Pool: %s destroyed successfully", pool_name)

        if not check_list_state(pool_name, "inactive"):
            raise error.TestFail("State of pool: %s marked as active"
                                 "instead of inactive" % pool_name)
        if not check_list_autostart(pool_name, "yes"):
            raise error.TestFail("Autostart of pool: %s marked as no"
                                 "instead of yes" % pool_name)

        # Step (11)
        if check_vol_list(vol_name, pool_name, pool_target):
            raise error.TestFail("Command virsh vol-list succeeded"
                                 " on an inactive pool")
        # Step (12)
        result = virsh.pool_start(pool_name, ignore_status=True)
        if result.exit_status != 0:
            raise error.TestFail("Command virsh pool-start failed:\n%s" %
                                 result.stdout)
        else:
            logging.debug("Pool: %s started successfully", pool_name)

        # Step (13)
        if not check_vol_list(vol_name, pool_name, pool_target):
            raise error.TestFail("Volume %s is not found in the "
                                 "output of virsh vol-list" % vol_name)

        # Step (14)
        result = virsh.vol_delete(vol_name, pool_name)
        if result.exit_status != 0:
            raise error.TestFail("Command virsh vol-delete failed:\n%s" %
                                 result.stdout)
        else:
            logging.debug("Volume: %s deleted successfully", vol_name)

        # Step (15)
        if check_vol_list(vol_name, pool_name, pool_target):
            raise error.TestFail("Command virsh vol-list shows deleted volume"
                                 " % for a pool %s" % vol_name, pool_name)

        # Step (16)
        if not virsh.pool_destroy(pool_name):
            raise error.TestFail("Command virsh pool-destroy failed")
        else:
            logging.debug("Pool: %s destroyed successfully", pool_name)

        # Step (17)
        result = virsh.pool_undefine(pool_name)
        if result.exit_status != 0:
            raise error.TestFail("Command virsh pool-undefine failed:\n%s" %
                                 result.stdout)
        else:
            logging.debug("Pool: %s undefined successfully", pool_name)

    finally:
        if check_list_state(pool_name, "active"):
            if not virsh.pool_destroy(pool_name):
                raise error.TestFail("Command virsh pool-destroy failed")
            result = virsh.pool_undefine(pool_name)
            if result.exit_status != 0:
                raise error.TestFail(
                    "Command virsh pool-undefine failed:\n%s" %
                    result.stdout)
        elif check_list_state(pool_name, "inactive"):
            result = virsh.pool_undefine(pool_name, ignore_status=True)
            if result.exit_status != 0:
                raise error.TestFail(
                    "Command virsh pool-undefine failed:\n%s" %
                    result.stdout)

        try:
            logging.debug(
                "Deleting the pool target: %s directory", pool_target)
            shutil.rmtree(pool_target)
        except OSError, detail:
            raise error.TestFail("Failed to delete the pool target directory"
                                 "%s:\n %s" % (pool_target, detail))
