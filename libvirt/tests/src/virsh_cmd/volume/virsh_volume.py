import os
import re
import shutil
import logging
from autotest.client.shared import utils, error
from virttest import utils_misc, virsh
from virttest.libvirt_xml import vol_xml


def run(test, params, env):
    """
    1. Create a pool
    2. Create n number of volumes(vol-create-as)
    3. Check the volume details from the following commands
       vol-info
       vol-key
       vol-list
       vol-name
       vol-path
       vol-pool
       qemu-img info
    4. Delete the volume and check in vol-list
    5. Repeat the steps for number of volumes given
    6. Delete the pool and target
    TODO: Handle negative testcases
    """

    def define_start_pool(pool_name, pool_type, pool_target):
        """
        To define a pool
        """
        if 'dir' in pool_type:
            if not os.path.isdir(pool_target):
                os.makedirs(pool_target)
            result = virsh.pool_define_as(pool_name, pool_type, pool_target)
            if result.exit_status != 0:
                raise error.TestFail("Command virsh pool-define-as"
                                     " failed:\n%s" % result.stderr.strip())
            else:
                logging.debug(
                    "%s type pool: %s defined successfully", pool_type, pool_name)
            result = virsh.pool_start(pool_name, ignore_status=True)
            if result.exit_status != 0:
                raise error.TestFail("Command virsh pool-start failed:\n%s" %
                                     result.stderr)
            else:
                logging.debug("Pool: %s successfully started", pool_name)
        else:
            raise error.TestNAError("pool type %s has not yet been"
                                    " supported in the test" % pool_type)
        return True

    def cleanup_pool(pool_name, pool_target):
        """
        Destroys, undefines and delete the pool target
        """
        result = virsh.pool_destroy(pool_name, ignore_status=True)
        if not result:
            raise error.TestFail("Command virsh pool-destroy failed")
        result = virsh.pool_undefine(pool_name, ignore_status=True)
        if result.exit_status != 0:
            raise error.TestFail("Command virsh pool-undefine failed:\n%s" %
                                 result.stderr.strip())
        try:
            logging.debug(
                "Deleting the pool target: %s directory", pool_target)
            shutil.rmtree(pool_target)
        except OSError, detail:
            raise error.TestFail("Failed to delete the pool target directory"
                                 "%s:\n %s" % (pool_target, detail))

    def create_volume(expected_vol):
        """
        Creates Volume
        """

        result = virsh.vol_create_as(expected_vol['name'],
                                     expected_vol['pool_name'],
                                     expected_vol['capacity'],
                                     expected_vol['allocation'],
                                     expected_vol['format'],
                                     ignore_status=True)
        if result.exit_status != 0:
            raise error.TestFail("Command virsh vol-create-as failed:\n%s" %
                                 result.stderr.strip())
        else:
            logging.info("Volume: %s successfully created on pool: %s",
                         expected_vol['name'], expected_vol['pool_name'])

        return True

    def delete_volume(expected_vol):
        """
        Deletes Volume
        """
        result = virsh.vol_delete(expected_vol['name'],
                                  expected_vol['pool_name'],
                                  ignore_status=True)
        if result.exit_status != 0:
            raise error.TestFail("Command virsh vol-delete failed:\n%s" %
                                 result.stderr.strip())
        else:
            logging.debug("Volume: %s successfully created on pool: %s",
                          expected_vol['name'], expected_vol['pool_name'])

    def get_vol_list(pool_name, vol_name):
        """
        Parse the volume list
        """
        output = virsh.vol_list(pool_name, "--details")
        rg = re.compile(
            r'^(\S+)\s+(\S+)\s+(\S+)\s+(\d+.\d+\s\S+)\s+(\d+.\d+.*)')
        vol = {}
        vols = []
        volume_detail = None
        found = False
        for line in output.stdout.splitlines():
            match = re.search(rg, line.lstrip())
            if match is not None:
                vol['name'] = match.group(1)
                vol['path'] = match.group(2)
                vol['type'] = match.group(3)
                vol['capacity'] = match.group(4)
                vol['allocation'] = match.group(5)
                vols.append(vol)
                vol = {}
        for volume in vols:
            if volume['name'] == vol_name:
                volume_detail = volume
                found = True
        return (found, volume_detail)

    def get_vol_info(pool_name, vol_name):
        """
        Parse the volume info
        """
        output = virsh.vol_info(vol_name, pool_name)
        reg1 = re.compile(r'Name:\s+(\S+)')
        reg2 = re.compile(r'Type:\s+(\S+)')
        reg3 = re.compile(r'Capacity:\s+(\S+.*)')
        reg4 = re.compile(r'Allocation:\s+(\S+.*)')
        vol_info = {}
        for line in output.stdout.splitlines():
            match1 = re.search(reg1, line)
            match2 = re.search(reg2, line)
            match3 = re.search(reg3, line)
            match4 = re.search(reg4, line)
            if match1 is not None:
                vol_info['name'] = match1.group(1)
            if match2 is not None:
                vol_info['type'] = match2.group(1)
            if match3 is not None:
                vol_info['capacity'] = match3.group(1)
            if match4 is not None:
                vol_info['allocation'] = match4.group(1)
        return vol_info

    def get_image_info(image_name):
        """
        Get the details of the volume(image) from qemu-img info
        """
        qemu_img = utils_misc.get_path(test.bindir,
                                       params.get("qemu_img_binary"))
        if not os.path.exists(qemu_img):
            raise error.TestError("Binary of 'qemu-img' not found")

        cmd = "%s info %s" % (qemu_img, image_name)
        format_vol = utils.system_output(cmd)
        reg1 = re.compile(r'image:\s+(\S+)')
        reg2 = re.compile(r'file format:\s+(\S+)')
        reg3 = re.compile(r'virtual size:\s+(\S+.*)')
        reg4 = re.compile(r'disk size:\s+(\S+.*)')
        image_info = {}
        for line in format_vol.splitlines():
            match1 = re.search(reg1, line)
            match2 = re.search(reg2, line)
            match3 = re.search(reg3, line)
            match4 = re.search(reg4, line)
            if match1 is not None:
                image_info['name'] = match1.group(1)
            if match2 is not None:
                image_info['format'] = match2.group(1)
            if match3 is not None:
                image_info['capacity'] = match3.group(1)
            if match4 is not None:
                image_info['allocation'] = match4.group(1)
        return image_info

    def norm_capacity(capacity):
        """
        Normalize the capacity values to bytes
        """
        # Normaize all values to bytes
        norm_capacity = {}
        des = {'B': 'B', 'bytes': 'B', 'b': 'B', 'kib': 'K',
               'KiB': 'K', 'K': 'K', 'k': 'K', 'KB': 'K',
               'mib': 'M', 'MiB': 'M', 'M': 'M', 'm': 'M',
               'MB': 'M', 'gib': 'G', 'GiB': 'G', 'G': 'G',
               'g': 'G', 'GB': 'G', 'Gb': 'G', 'tib': 'T',
               'TiB': 'T', 'TB': 'T', 'T': 'T', 't': 'T'
               }
        val = {'B': 1,
               'K': 1024,
               'M': 1048576,
               'G': 1073741824,
               'T': 1099511627776
               }

        reg_list = re.compile(r'(\S+)\s(\S+)')
        match_list = re.search(reg_list, capacity['list'])
        if match_list is not None:
            mem_value = float(match_list.group(1))
            norm = val[des[match_list.group(2)]]
            norm_capacity['list'] = int(mem_value * norm)
        else:
            raise error.TestFail("Error in parsing capacity value in"
                                 " virsh vol-list")

        match_info = re.search(reg_list, capacity['info'])
        if match_info is not None:
            mem_value = float(match_info.group(1))
            norm = val[des[match_list.group(2)]]
            norm_capacity['info'] = int(mem_value * norm)
        else:
            raise error.TestFail("Error in parsing capacity value "
                                 "in virsh vol-info")

        reg_qemu = re.compile(r'\S+\s\((\d+)\s\S+\)')
        match_qemu = re.search(reg_qemu, capacity['qemu_img'])
        if match_qemu is not None:
            norm_capacity['qemu_img'] = int(match_qemu.group(1))
        else:
            raise error.TestFail("Error in parsing capacity value "
                                 "in qemu-img info")

        norm_capacity['xml'] = int(capacity['xml'])

        return norm_capacity

    def check_vol(expected, avail=True):
        """
        Checks the expected volume details with actual volume details from
        vol-dumpxml
        vol-list
        vol-info
        vol-key
        vol-path
        qemu-img info
        """
        error_count = 0
        volume_xml = {}
        (isavail, actual_list) = get_vol_list(expected['pool_name'],
                                              expected['name'])
        actual_info = get_vol_info(expected['pool_name'],
                                   expected['name'])
        if not avail:
            if isavail:
                error_count += 1
                logging.error("Deleted vol: %s is still shown in vol-list",
                              expected['name'])
            else:
                logging.info("Volume %s checked successfully for deletion",
                             expected['name'])
                return error_count
        else:
            if not isavail:
                logging.error("Volume list does not show volume %s",
                              expected['name'])
                logging.error("Volume creation failed")
                error_count += 1

        # Get values from vol-dumpxml
        volume_xml = vol_xml.VolXML.get_vol_details_by_name(expected['name'],
                                                            expected['pool_name'])

        # Check against virsh vol-key
        vol_key = virsh.vol_key(expected['name'], expected['pool_name'])
        if vol_key.stdout.strip() != volume_xml['key']:
            logging.error("Volume key is mismatch \n%s"
                          "Key from xml: %s\n Key from command: %s", expected['name'], volume_xml['key'], vol_key)
            error_count += 1
        else:
            logging.debug("virsh vol-key for volume: %s successfully"
                          " checked against vol-dumpxml", expected['name'])

        # Check against virsh vol-path
        vol_path = virsh.vol_path(expected['name'], expected['pool_name'])
        if expected['path'] != vol_path.stdout.strip():
            logging.error("Volume path mismatch for volume: %s\n"
                          "Expected path: %s\n Output of vol-path: %s\n",
                          expected['name'],
                          expected['path'], vol_path)
            error_count += 1
        else:
            logging.debug("virsh vol-path for volume: %s successfully checked"
                          " against created volume path", expected['name'])

        # Check path against virsh vol-list
        if isavail:
            if expected['path'] != actual_list['path']:
                logging.error("Volume path mismatch for volume:%s\n"
                              "Expected Path: %s\n Path from virsh vol-list: %s", expected[
                                  'name'], expected['path'],
                              actual_list['path'])
                error_count += 1
            else:
                logging.debug("Path of volume: %s from virsh vol-list "
                              "successfully checked against created "
                              "volume path", expected['name'])

        # Check path against virsh vol-dumpxml
        if expected['path'] != volume_xml['path']:
            logging.error("Volume path mismatch for volume: %s\n"
                          "Expected Path: %s\n Path from virsh vol-dumpxml: %s", expected['name'], expected['path'], volume_xml['path'])
            error_count += 1

        else:
            logging.debug("Path of volume: %s from virsh vol-dumpxml "
                          "successfully checked against created volume path",
                          expected['name'])

        # Check type against virsh vol-list
        if isavail:
            if expected['type'] != actual_list['type']:
                logging.error("Volume type mismatch for volume: %s\n"
                              "Expected Type: %s\n Type from vol-list: %s",
                              expected['name'],
                              expected['type'], actual_list['type'])
                error_count += 1
            else:
                logging.debug("Type of volume: %s from virsh vol-list "
                              "successfully checked against the created "
                              "volume type", expected['name'])

        # Check type against virsh vol-info
        if expected['type'] != actual_info['type']:
            logging.error("Volume type mismatch for volume: %s\n"
                          "Expected Type: %s\n Type from vol-info: %s",
                          expected['name'], expected['type'],
                          actual_info['type'])
            error_count += 1
        else:
            logging.debug("Type of volume: %s from virsh vol-info successfully"
                          " checked against the created volume type",
                          expected['name'])

        # Check name against virsh vol-info
        if expected['name'] != actual_info['name']:
            logging.error("Volume name mismatch for volume: %s\n"
                          "Expected name: %s\n Name from vol-info: %s",
                          expected['name'],
                          expected['name'], actual_info['name'])
            error_count += 1
        else:
            logging.debug("Name of volume: %s from virsh vol-info successfully"
                          " checked against the created volume name",
                          expected['name'])

        # Check format from against qemu-img info
        img_info = get_image_info(expected['path'])
        if expected['format'] != img_info['format']:
            logging.error("Volume format mismatch for volume: %s\n"
                          "Expected format: %s\n Format from qemu-img info: %s",
                          expected['name'],
                          expected['format'], img_info['format'])
            error_count += 1
        else:
            logging.debug("Format of volume: %s from qemu-img info checked "
                          "successfully against the created volume format",
                          expected['name'])

        # Check format against vol-dumpxml
        if expected['format'] != volume_xml['format']:
            logging.error("Volume format mismatch for volume: %s\n"
                          "Expected format: %s\n Format from vol-dumpxml: %s",
                          expected['name'],
                          expected['format'], volume_xml['format'])
            error_count += 1
        else:
            logging.debug("Format of volume: %s from virsh vol-dumpxml checked"
                          " successfully against the created volume format",
                          expected['name'])

        # Check pool name against vol-pool
        vol_pool = virsh.vol_pool(expected['path'])
        if expected['pool_name'] != vol_pool.stdout.strip():
            logging.error("Pool name mismatch for volume: %s against"
                          "virsh vol-pool", expected['name'])
            error_count += 1
        else:
            logging.debug("Pool name of volume: %s checked successfully"
                          " against the virsh vol-pool", expected['name'])

        norm_cap = {}
        capacity = {}
        capacity['list'] = actual_list['capacity']
        capacity['info'] = actual_info['capacity']
        capacity['xml'] = volume_xml['capacity']
        capacity['qemu_img'] = img_info['capacity']
        norm_cap = norm_capacity(capacity)
        if expected['capacity'] != norm_cap['list']:
            logging.error("Capacity mismatch for volume: %s against virsh"
                          " vol-list\nExpected: %s\nActual: %s",
                          expected['name'], expected['capacity'],
                          norm_cap['list'])
            error_count += 1
        else:
            logging.debug("Capacity value checked successfully against"
                          " virsh vol-list for volume %s", expected['name'])

        if expected['capacity'] != norm_cap['info']:
            logging.error("Capacity mismatch for volume: %s against virsh"
                          " vol-info\nExpected: %s\nActual: %s",
                          expected['name'], expected['capacity'],
                          norm_cap['info'])
            error_count += 1
        else:
            logging.debug("Capacity value checked successfully against"
                          " virsh vol-info for volume %s", expected['name'])

        if expected['capacity'] != norm_cap['xml']:
            logging.error("Capacity mismatch for volume: %s against virsh"
                          " vol-dumpxml\nExpected: %s\nActual: %s",
                          expected['name'], expected['capacity'],
                          norm_cap['xml'])
            error_count += 1
        else:
            logging.debug("Capacity value checked successfully against"
                          " virsh vol-dumpxml for volume: %s",
                          expected['name'])

        if expected['capacity'] != norm_cap['qemu_img']:
            logging.error("Capacity mismatch for volume: %s against "
                          "qemu-img info\nExpected: %s\nActual: %s",
                          expected['name'], expected['capacity'],
                          norm_cap['qemu_img'])
            error_count += 1
        else:
            logging.debug("Capacity value checked successfully against"
                          " qemu-img info for volume: %s",
                          expected['name'])

        return error_count

    # Initialize the variables
    pool_name = params.get("pool_name")
    pool_type = params.get("pool_type")
    pool_target = params.get("pool_target")
    if os.path.dirname(pool_target) is "":
        pool_target = os.path.join(test.tmpdir, pool_target)
    vol_name = params.get("volume_name")
    vol_number = int(params.get("number_of_volumes", "2"))
    capacity = int(params.get("volume_size", "1048576"))
    allocation = int(params.get("volume_allocation", "1048576"))
    vol_format = params.get("volume_format")
    expected_vol = {}
    if pool_type == 'dir':
        vol_type = 'file'

        logging.debug("Debug:\npool_name:%s\npool_type:%s\npool_target:%s\n"
                      "vol_name:%s\nvol_number:%s\ncapacity:%s\nallocation:%s\n"
                      "vol_format:%s", pool_name, pool_type, pool_target,
                      vol_name, vol_number, capacity, allocation, vol_format)
    # Run Testcase
    total_err_count = 0
    try:
        # Define and start pool
        define_start_pool(pool_name, pool_type, pool_target)
        for i in range(vol_number):
            volume_name = "%s_%d" % (vol_name, i)
            # Build expected results
            expected_vol['pool_name'] = pool_name
            expected_vol['pool_type'] = pool_type
            expected_vol['pool_target'] = pool_target
            expected_vol['name'] = volume_name
            expected_vol['capacity'] = capacity
            expected_vol['allocation'] = allocation
            expected_vol['format'] = vol_format
            expected_vol['path'] = pool_target + '/' + volume_name
            expected_vol['type'] = vol_type
            # Creates volume
            create_volume(expected_vol)
            # Different Checks for volume
            total_err_count += check_vol(expected_vol)
            # Delete volume and check for results
            delete_volume(expected_vol)
            total_err_count += check_vol(expected_vol, False)
        if total_err_count > 0:
            raise error.TestFail("Test case failed due to previous errors.\n"
                                 "Check for error logs")
    finally:
        cleanup_pool(pool_name, pool_target)
