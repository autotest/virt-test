"""
multi_disk_random_hotplug test for Autotest framework.

:copyright: 2013 Red Hat Inc.
"""
import logging
import random
import time
from autotest.client.shared import error
from virttest import funcatexit
from virttest import qemu_qtree, utils_test, env_process
from virttest.qemu_devices import utils


def stop_stresser(vm, stop_cmd):
    """
    Wrapper which connects to vm and sends the stop_cmd
    :param vm: Virtual Machine
    :type vm: virttest.virt_vm.BaseVM
    :param stop_cmd: Command to stop the stresser
    :type stop_cmd: string
    """
    session = vm.wait_for_login(timeout=10)
    session.cmd(stop_cmd)
    session.close()


# TODO: Remove this silly function when qdev vs. qtree comparison is available
def convert_params(params, args):
    """
    Updates params according to images_define_by_params arguments.
    :note: This is only temporarily solution until qtree vs. qdev verification
           is available.
    :param params: Dictionary with the test parameters
    :type param: virttest.utils_params.Params
    :param args: Dictionary of images_define_by_params arguments
    :type args: dictionary
    :return: Updated dictionary with the test parameters
    :rtype: virttest.utils_params.Params
    """
    convert = {'fmt': 'drive_format', 'cache': 'drive_cache',
               'werror': 'drive_werror', 'rerror': 'drive_rerror',
               'serial': 'drive_serial', 'snapshot': 'image_snapshot',
               'bus': 'drive_bus', 'unit': 'drive_unit', 'port': 'drive_port',
               'readonly': 'image_readonly', 'scsiid': 'drive_scsiid',
               'lun': 'drive_lun', 'aio': 'image_aio',
               'imgfmt': 'image_format', 'pci_addr': 'drive_pci_addr',
               'x_data_plane': 'x-data-plane',
               'scsi': 'virtio-blk-pci_scsi'}
    name = args.pop('name')
    params['images'] += " %s" % name
    params['image_name_%s' % name] = args.pop('filename')
    params['image_raw_device_%s' % name] = 'yes'
    for key, value in args.iteritems():
        params["%s_%s" % (convert.get(key, key), name)] = value
    return params


@error.context_aware
def run(test, params, env):
    """
    This tests the disk hotplug/unplug functionality.
    1) prepares multiple disks to be hotplugged
    2) hotplugs them
    3) verifies that they are in qtree/guest system/...
    4) unplugs them
    5) verifies they are not in qtree/guest system/...
    6) repeats $repeat_times
    *) During the whole test stress_cmd might be executed

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def verify_qtree(params, info_qtree, info_block, proc_scsi, qdev):
        """
        Verifies that params, info qtree, info block and /proc/scsi/ matches
        :param params: Dictionary with the test parameters
        :type params: virttest.utils_params.Params
        :param info_qtree: Output of "info qtree" monitor command
        :type info_qtree: string
        :param info_block: Output of "info block" monitor command
        :type info_block: dict of dicts
        :param proc_scsi: Output of "/proc/scsi/scsi" guest file
        :type proc_scsi: string
        :param qdev: qcontainer representation
        :type qdev: virttest.qemu_devices.qcontainer.DevContainer
        """
        err = 0
        qtree = qemu_qtree.QtreeContainer()
        qtree.parse_info_qtree(info_qtree)
        disks = qemu_qtree.QtreeDisksContainer(qtree.get_nodes())
        (tmp1, tmp2) = disks.parse_info_block(info_block)
        err += tmp1 + tmp2
        err += disks.generate_params()
        err += disks.check_disk_params(params)
        (tmp1, tmp2, _, _) = disks.check_guests_proc_scsi(proc_scsi)
        err += tmp1 + tmp2
        if err:
            logging.error("info qtree:\n%s", info_qtree)
            logging.error("info block:\n%s", info_block)
            logging.error("/proc/scsi/scsi:\n%s", proc_scsi)
            logging.error(qdev.str_bus_long())
            raise error.TestFail("%s errors occurred while verifying"
                                 " qtree vs. params" % err)

    def insert_into_qdev(qdev, param_matrix, no_disks, params):
        """
        Inserts no_disks disks int qdev using randomized args from param_matrix
        :param qdev: qemu devices container
        :type qdev: virttest.qemu_devices.qcontainer.DevContainer
        :param param_matrix: Matrix of randomizable params
        :type param_matrix: list of lists
        :param no_disks: Desired number of disks
        :type no_disks: integer
        :param params: Dictionary with the test parameters
        :type params: virttest.utils_params.Params
        :return: (newly added devices, number of added disks)
        :rtype: tuple(list, integer)
        """
        error.context("Insert devices into qdev", logging.debug)
        new_devices = []
        _new_devs_fmt = ""
        _formats = param_matrix.pop('fmt', [params.get('drive_format')])
        formats = _formats[:]
        i = 0
        while i < no_disks:
            # Set the format
            if len(formats) < 1:
                if i == 0:
                    raise error.TestError("Fail to add any disks, probably bad"
                                          " configuration.")
                logging.warn("Can't create desired number '%s' of disk types "
                             "'%s'. Using '%d' no disks.", no_disks,
                             _formats, i)
                break
            name = 'stg%d' % i
            args = {'name': name, 'filename': stg_image_name % i}
            fmt = random.choice(formats)
            if fmt == 'virtio_scsi':
                args['fmt'] = 'scsi-hd'
                args['scsi_hba'] = 'virtio-scsi-pci'
            elif fmt == 'lsi_scsi':
                args['fmt'] = 'scsi-hd'
                args['scsi_hba'] = 'lsi53c895a'
            elif fmt == 'spapr_vscsi':
                args['fmt'] = 'scsi-hd'
                args['scsi_hba'] = 'spapr-vscsi'
            else:
                args['fmt'] = fmt
            # Other params
            for key, value in param_matrix.iteritems():
                args[key] = random.choice(value)

            try:
                devs = qdev.images_define_by_variables(**args)
                for dev in devs:
                    qdev.insert(dev)
            except utils.DeviceError:
                for dev in devs:
                    if dev in qdev:
                        qdev.remove(dev, recursive=True)
                formats.remove(fmt)
                continue

            params = convert_params(params, args)
            env_process.preprocess_image(test, params.object_params(name),
                                         name)
            new_devices.extend(devs)
            _new_devs_fmt += "%s(%s) " % (name, fmt)
            i += 1
        if _new_devs_fmt:
            logging.info("Using disks: %s", _new_devs_fmt[:-1])
        param_matrix['fmt'] = _formats
        return new_devices, params

    def hotplug_serial(new_devices, monitor):
        """
        Do the actual hotplug of the new_devices using monitor monitor.
        :param new_devices: List of devices which should be hotplugged
        :type new_devices: List of virttest.qemu_devices.qdevice.QBaseDevice
        :param monitor: Monitor which should be used for hotplug
        :type monitor: virttest.qemu_monitor.Monitor
        """
        error.context("Hotplug the devices", logging.debug)
        failed = 0
        passed = 0
        unverif = 0
        hotplug_outputs = []
        hotplug_sleep = float(params.get('wait_between_hotplugs', 0))
        for device in new_devices:      # Hotplug all devices
            time.sleep(hotplug_sleep)
            hotplug_outputs.append(device.hotplug(monitor))
        time.sleep(hotplug_sleep)
        for device in new_devices:      # Verify the hotplug status
            out = hotplug_outputs.pop(0)
            out = device.verify_hotplug(out, monitor)
            if out is True:
                passed += 1
            elif out is False:
                failed += 1
            else:
                unverif += 1
        if failed == 0 and unverif == 0:
            logging.debug("Hotplug status: verified %d", passed)
        elif failed == 0:
            logging.warn("Hotplug status: verified %d, unverified %d", passed,
                         unverif)
        else:
            logging.error("Hotplug status: verified %d, unverified %d, failed "
                          "%d", passed, unverif, failed)
            raise error.TestFail("Hotplug of some devices failed.")

    def unplug_serial(new_devices, qdev, monitor):
        """
        Do the actual unplug of new_devices using monitor monitor
        :param new_devices: List of devices which should be hotplugged
        :type new_devices: List of virttest.qemu_devices.qdevice.QBaseDevice
        :param qdev: qemu devices container
        :type qdev: virttest.qemu_devices.qcontainer.DevContainer
        :param monitor: Monitor which should be used for hotplug
        :type monitor: virttest.qemu_monitor.Monitor
        """
        error.context("Unplug and remove the devices", logging.debug)
        unplug_sleep = float(params.get('wait_between_unplugs', 0))
        failed = 0
        passed = 0
        unverif = 0
        unplug_outs = []
        unplug_devs = []
        for device in new_devices[::-1]:    # unplug all devices
            if device in qdev:  # Some devices are removed with previous one
                time.sleep(unplug_sleep)
                unplug_devs.append(device)
                unplug_outs.append(device.unplug(monitor))
                # Remove from qdev even when unplug failed because further in
                # this test we compare VM with qdev, which should be without
                # these devices. We can do this because we already set the VM
                # as dirty.
                qdev.remove(device)
        time.sleep(unplug_sleep)
        for device in unplug_devs:          # Verify unplugs
            _out = unplug_outs.pop(0)
            # unplug effect can be delayed as it waits for OS respone before
            # it removes the device form qtree
            for _ in xrange(50):
                out = device.verify_unplug(_out, monitor)
                if out is True:
                    break
                time.sleep(0.1)
            if out is True:
                passed += 1
            elif out is False:
                failed += 1
            else:
                unverif += 1

        # remove and check the images
        _disks = []
        for disk in params['images'].split(' '):
            if disk.startswith("stg"):
                env_process.postprocess_image(test, params.object_params(disk),
                                              disk)
            else:
                _disks.append(disk)
        params['images'] = " ".join(_disks)
        if failed == 0 and unverif == 0:
            logging.debug("Unplug status: verified %d", passed)
        elif failed == 0:
            logging.warn("Unplug status: verified %d, unverified %d", passed,
                         unverif)
        else:
            logging.error("Unplug status: verified %d, unverified %d, failed "
                          "%d", passed, unverif, failed)
            raise error.TestFail("Unplug of some devices failed.")

    vm = env.get_vm(params['main_vm'])
    monitor = vm.monitor
    qdev = vm.devices
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    out = vm.monitor.human_monitor_cmd("info qtree", debug=False)
    if "unknown command" in str(out):
        msg = "info qtree not supported. Can't verify qtree vs. guest disks."
        verify_qtree = lambda _1, _2, _3: logging.warn(msg)

    stg_image_name = params['stg_image_name']
    stg_image_num = int(params['stg_image_num'])
    stg_params = params.get('stg_params', '').split(' ')
    i = 0
    while i < len(stg_params) - 1:
        if not stg_params[i].strip():
            i += 1
            continue
        if stg_params[i][-1] == '\\':
            stg_params[i] = '%s %s' % (stg_params[i][:-1],
                                       stg_params.pop(i + 1))
        i += 1

    param_matrix = {}
    for i in xrange(len(stg_params)):
        if not stg_params[i].strip():
            continue
        (cmd, parm) = stg_params[i].split(':', 1)
        # ',' separated list of values
        parm = parm.split(',')
        j = 0
        while j < len(parm) - 1:
            if parm[j][-1] == '\\':
                parm[j] = '%s,%s' % (parm[j][:-1], parm.pop(j + 1))
            j += 1

        param_matrix[cmd] = parm

    # Modprobe the module if specified in config file
    module = params.get("modprobe_module")
    if module:
        session.cmd("modprobe %s" % module)

    stress_cmd = params.get('stress_cmd')
    if stress_cmd:
        funcatexit.register(env, params.get('type'), stop_stresser, vm,
                            params.get('stress_kill_cmd'))
        stress_session = vm.wait_for_login(timeout=10)
        for _ in xrange(int(params.get('no_stress_cmds', 1))):
            stress_session.sendline(stress_cmd)

    rp_times = int(params.get("repeat_times", 1))
    context_msg = "Running sub test '%s' %s"
    error.context("Verify disk before test", logging.info)
    info_qtree = vm.monitor.info('qtree', False)
    info_block = vm.monitor.info_block(False)
    proc_scsi = session.cmd_output('cat /proc/scsi/scsi')
    verify_qtree(params, info_qtree, info_block, proc_scsi, qdev)
    for iteration in xrange(rp_times):
        sub_type = params.get("sub_type_before_plug")
        if sub_type:
            error.context(context_msg % (sub_type, "before hotplug"),
                          logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)

        error.context("Hotplugging/unplugging devices, iteration %d"
                      % iteration, logging.info)
        qdev.set_dirty()
        new_devices, params = insert_into_qdev(qdev, param_matrix,
                                               stg_image_num, params)
        hotplug_serial(new_devices, monitor)
        time.sleep(float(params.get('wait_after_hotplug', 0)))
        error.context("Verify disks after hotplug", logging.debug)
        info_qtree = vm.monitor.info('qtree', False)
        info_block = vm.monitor.info_block(False)
        proc_scsi = session.cmd_output('cat /proc/scsi/scsi')
        verify_qtree(params, info_qtree, info_block, proc_scsi, qdev)
        qdev.set_clean()

        sub_type = params.get("sub_type_after_plug")
        if sub_type:
            error.context(context_msg % (sub_type, "after hotplug"),
                          logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)

        sub_type = params.get("sub_type_before_unplug")
        if sub_type:
            error.context(context_msg % (sub_type, "before hotunplug"),
                          logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)
        unplug_serial(new_devices, qdev, monitor)
        time.sleep(float(params.get('wait_after_unplug', 0)))
        error.context("Verify disks after unplug", logging.debug)
        info_qtree = vm.monitor.info('qtree', False)
        info_block = vm.monitor.info_block(False)
        proc_scsi = session.cmd_output('cat /proc/scsi/scsi')
        verify_qtree(params, info_qtree, info_block, proc_scsi, qdev)
        # we verified the unplugs, set the state to 0
        for _ in xrange(qdev.get_state()):
            qdev.set_clean()

        sub_type = params.get("sub_type_after_unplug")
        if sub_type:
            error.context(context_msg % (sub_type, "after hotunplug"),
                          logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)

    # Check for various KVM failures
    vm.verify_alive()
