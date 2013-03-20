"""
KVM cdrom test
@author: Amos Kong <akong@redhat.com>
@author: Lucas Meneghel Rodrigues <lmr@redhat.com>
@author: Lukas Doktor <ldoktor@redhat.com>
@copyright: 2011 Red Hat, Inc.
"""
import logging, re, time, os
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_misc, aexpect, qemu_monitor


@error.context_aware
def run_cdrom(test, params, env):
    """
    KVM cdrom test:

    1) Boot up a VM, with one iso image (optional).
    2) Check if VM identifies correctly the iso file.
    3) Verifies that device is unlocked <300s after boot (optional, if
       cdrom_test_autounlock is set).
    4) Eject cdrom using monitor.
    5) Change cdrom image with another iso several times.
    5) Test tray reporting function (optional, if cdrom_test_tray_status is set)
    6) Try to format cdrom and check the return string.
    7) Mount cdrom device.
    8) Copy file from cdrom and compare files.
    9) Umount and mount cdrom in guest for several times.
    10) Check if the cdrom lock works well when iso file is not inserted.
        Note: This case requires a qemu cli without setting file property
        for -drive option, and will be separated to a different cfg item.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.

    @param cfg: workaround_eject_time - Some versions of qemu are unable to
                                        eject CDROM directly after insert
    @param cfg: cdrom_test_autounlock - Test whether guest OS unlocks cdrom
                                        after boot (<300s after VM is booted)
    @param cfg: cdrom_test_tray_status - Test tray reporting (eject and insert
                                         CD couple of times in guest).
    @param cfg: cdrom_test_locked -     Test whether cdrom tray lock function
                                        work well in guest.
    @param cfg: cdrom_test_eject -      Test whether cdrom works well after
                                        several times of eject action.
    @param cfg: cdrom_test_file_operation - Test file operation for cdrom,
                                            such as mount/umount, reading files
                                            on cdrom.

    @warning: Check dmesg for block device failures
    """
    def master_iso_images(iso_image_dir):
        """
        Creates 'new' iso image with one file on it
        """
        error.context("Creating test iso images", logging.info)
        os.chdir(test.tmpdir)
        utils.run("dd if=/dev/urandom of=orig bs=10M count=1")
        utils.run("dd if=/dev/urandom of=new bs=10M count=1")
        utils.run("mkisofs -o %s/orig.iso orig" % iso_image_dir)
        utils.run("mkisofs -o %s/new.iso new" % iso_image_dir)
        return "%s/new.iso" % iso_image_dir


    def cleanup_cdroms(iso_image_dir):
        """
        Removes created iso images
        """
        error.context("Cleaning up temp iso images", logging.info)
        os.remove("%s/new.iso" % iso_image_dir)


    def get_cdrom_file(qemu_cdrom_device):
        """
        @param device: qemu monitor device
        @return: file associated with $qemu_cdrom_device device
        """
        blocks = vm.monitor.info("block")
        cdfile = None
        if isinstance(blocks, str):
            tmp_re_str = r'%s: .*file=(\S*) ' % qemu_cdrom_device
            file_list = re.findall(tmp_re_str, blocks)
            if file_list:
                cdfile = file_list[0]
        else:
            for block in blocks:
                if block['device'] == qemu_cdrom_device:
                    try:
                        cdfile = block['inserted']['file']
                        break
                    except KeyError:
                        continue
        return cdfile


    def _get_tray_stat_via_monitor(qemu_cdrom_device):
        """
        Get the cdrom tray status via qemu monitor
        """
        is_open, checked = (None, False)

        blocks = vm.monitor.info("block")
        if isinstance(blocks, str):
            for block in blocks.splitlines():
                if qemu_cdrom_device in block:
                    if "tray-open=1" in block:
                        is_open, checked = (True, True)
                    elif "tray-open=0" in block:
                        is_open, checked = (False, True)
        else:
            for block in blocks:
                if block['device'] == qemu_cdrom_device:
                    key = filter(lambda x: re.match(r"tray.*open", x),
                                 block.keys())
                    # compatible rhel6 and rhel7 diff qmp output
                    if not key:
                        break
                    is_open, checked = (block[key[0]], True)
        return (is_open, checked)


    def is_tray_opened(qemu_cdrom_device, mode='monitor', dev_name="/dev/sr0"):
        """
        Checks whether the tray is opend

        @param cdrom: cdrom image file name.
        @param mode: tray status checking mode, now support:
                     "monitor": get tray status from monitor.
                     "session": get tray status from guest os.
                     "mixed": get tray status first, if failed, try to
                              get the status in guest os again.
        @param dev_name: cdrom device name in guest os.

        @return: True if cdrom tray is open, otherwise False.
                 None if failed to get the tray status.
        """
        is_open, checked = (None, False)

        if mode in ['monitor', 'mixed']:
            is_open, checked = _get_tray_stat_via_monitor(qemu_cdrom_device)

        if (mode in ['session', 'mixed']) and not checked:
            tray_cmd = "python /tmp/tray_open.py %s" % dev_name
            o = session.cmd_output(tray_cmd)
            if "cdrom is open" in o:
                is_open, checked = (True, True)
            else:
                is_open, checked = (False, True)
        if checked:
            return is_open
        return None


    def eject_cdrom(qemu_cdrom_device, monitor):
        """ Ejects the cdrom using kvm-monitor """
        if isinstance(monitor, qemu_monitor.HumanMonitor):
            monitor.cmd("eject %s" % qemu_cdrom_device)
        elif isinstance(monitor, qemu_monitor.QMPMonitor):
            monitor.cmd("eject", args={'device': qemu_cdrom_device})

    def change_cdrom(qemu_cdrom_device, target, monitor):
        """ Changes the medium using kvm-monitor """
        if isinstance(monitor, qemu_monitor.HumanMonitor):
            monitor.cmd("change %s %s" % (qemu_cdrom_device, target))
        elif isinstance(monitor, qemu_monitor.QMPMonitor):
            args = {'device': qemu_cdrom_device, 'target': target}
            monitor.cmd("change", args=args)


    def get_empty_cdrom_device():
        """
        Get cdrom device when cdrom is not insert.
        """
        device = None
        blocks = vm.monitor.info("block")
        if isinstance(blocks, str):
            for block in blocks.strip().split('\n'):
                if 'not inserted' in block:
                    device = block.split(':')[0]
        else:
            for block in blocks:
                if 'inserted' not in block.keys():
                    device = block['device']
        return device


    def eject_test_via_monitor(qemu_cdrom_device, guest_cdrom_device,
                               iso_image, max_times):
        """
        Test cdrom eject function via qemu monitor.
        """
        error.context("Eject the iso image in monitor %s times" % max_times,
                      logging.info)
        for i in range(1, max_times):
            session.cmd('eject %s' % guest_cdrom_device)
            eject_cdrom(qemu_cdrom_device, vm.monitor)
            time.sleep(2)
            if get_cdrom_file(qemu_cdrom_device) is not None:
                raise error.TestFail("Device %s was not ejected"
                                     " (round %s)" % (iso_image, i))

            iso_image = iso_image_new
            # On even attempts, try to change the iso image
            if i % 2 == 0:
                iso_image = iso_image_orig
            change_cdrom(qemu_cdrom_device, iso_image, vm.monitor)
            if get_cdrom_file(qemu_cdrom_device) != iso_image:
                raise error.TestFail("Could not change iso image %s"
                                     " (round %s)" % (iso_image, i))
            time.sleep(workaround_eject_time)


    def check_tray_status_test(qemu_cdrom_device, guest_cdrom_device,
                               max_times):
        """
        Test cdrom tray status reporting function.
        """
        error.context("Copy test script to guest")
        tray_check_src = params.get("tray_check_src")
        if tray_check_src:
            tray_check_src = utils_misc.get_path(test.virtdir,
                                                 "deps/%s" % tray_check_src)
            vm.copy_files_to(tray_check_src, "/tmp")

        if is_tray_opened(qemu_cdrom_device) is None:
            logging.warn("Tray status reporting is not supported by qemu!")
            logging.warn("cdrom_test_tray_status test is skipped...")
            return

        error.context("Eject the cdrom in guest %s times" % max_times,
                      logging.info)
        for i in range(1, max_times):
            session.cmd('eject %s' % guest_cdrom_device)
            if not is_tray_opened(qemu_cdrom_device):
                raise error.TestFail("Monitor reports tray closed"
                                     " when ejecting (round %s)" % i)
            session.cmd('dd if=%s of=/dev/null count=1' % guest_cdrom_device)
            if is_tray_opened(qemu_cdrom_device):
                raise error.TestFail("Monitor reports tray opened when reading"
                                     " cdrom in guest (round %s)" % i)
            time.sleep(workaround_eject_time)


    def check_tray_locked_test(qemu_cdrom_device, guest_cdrom_device):
        """
        Test cdrom tray locked function.
        """
        error.context("Check cdrom tray status after cdrom is locked",
                      logging.info)
        tmp_is_trap_open = is_tray_opened(qemu_cdrom_device, mode='mixed',
                             dev_name=guest_cdrom_device)
        if tmp_is_trap_open is None:
            logging.warn("Tray status reporting is not supported by qemu!")
            logging.warn("cdrom_test_locked test is skipped...")
            return

        eject_failed = False
        eject_failed_msg = "Tray should be closed even in locked status"
        session.cmd('eject %s' % guest_cdrom_device)
        tmp_is_trap_open = is_tray_opened(qemu_cdrom_device, mode='mixed',
                             dev_name=guest_cdrom_device)
        if not tmp_is_trap_open:
            raise error.TestFail("Tray should not in closed status")

        session.cmd('eject -i on %s' % guest_cdrom_device)
        try:
            session.cmd('eject -t %s' % guest_cdrom_device)
        except aexpect.ShellCmdError, e:
            eject_failed = True
            eject_failed_msg += ", eject command failed: %s" % str(e)

        tmp_is_trap_open = is_tray_opened(qemu_cdrom_device, mode='mixed',
                             dev_name=guest_cdrom_device)
        if (eject_failed or tmp_is_trap_open):
            raise error.TestFail(eject_failed_msg)

        session.cmd('eject -i off %s' % guest_cdrom_device)
        session.cmd('eject -t %s' % guest_cdrom_device)


    def file_operation_test(guest_cdrom_device, session):
        """
        Cdrom file operation test.
        """
        error.context("Mounting the cdrom under /mnt", logging.info)
        session.cmd("mount %s %s" % (guest_cdrom_device, "/mnt"), timeout=30)

        filename = "new"

        error.context("File copying test", logging.info)
        session.cmd("rm -f /tmp/%s" % filename)
        session.cmd("cp -f /mnt/%s /tmp/" % filename)

        error.context("Compare file on disk and on cdrom", logging.info)
        f1_hash = session.cmd("md5sum /mnt/%s" % filename).split()[0].strip()
        f2_hash = session.cmd("md5sum /tmp/%s" % filename).split()[0].strip()
        if f1_hash != f2_hash:
            raise error.TestFail("On disk and on cdrom files are different, "
                                 "md5 mismatch")

        error.context("Mount/Unmount cdrom for %s times" % max_times,
                      logging.info)
        for _ in range(1, max_times):
            try:
                session.cmd("umount %s" % guest_cdrom_device)
                session.cmd("mount %s /mnt" % guest_cdrom_device)
            except aexpect.ShellError, detail:
                logging.error("Mount/Unmount fail, detail: '%s'", detail)
                logging.debug(session.cmd("cat /etc/mtab"))
                raise

        session.cmd("umount %s" % guest_cdrom_device)


    # Test main body start.
    iso_image_orig = params.get("cdrom_cd1")
    if iso_image_orig and not os.path.isabs(iso_image_orig):
        iso_image_orig = os.path.join(test.bindir, iso_image_orig)
    iso_image_dir = os.path.dirname(iso_image_orig)
    if (not params.get("not_insert_at_start")
        or params.get("not_insert_at_start") == "no"):
        iso_image_new = master_iso_images(iso_image_dir)

    vm = env.get_vm(params["main_vm"])
    vm.create()

    # Some versions of qemu are unable to eject CDROM directly after insert
    workaround_eject_time = float(params.get('workaround_eject_time', 0))

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    iso_image = iso_image_orig
    error.context("Query cdrom devices in guest")
    tmp_output = session.cmd_output("ls /dev/cdrom*")
    tmp_re_str = r"/dev/cdrom-\w+|/dev/cdrom\d*"
    guest_cdrom_device_list = re.findall(tmp_re_str, tmp_output)
    logging.debug("guest_cdrom_device_list: %s", guest_cdrom_device_list)
    if params.get('not_insert_at_start') == "yes":
        error.context("Locked without media present", logging.info)
        #XXX: The device got from monitor might not match with the guest
        # defice if there are multiple cdrom devices.
        qemu_cdrom_device = get_empty_cdrom_device()
        guest_cdrom_device = guest_cdrom_device_list[0]
        if vm.check_block_locked(qemu_cdrom_device):
            raise error.TestFail("Device should not be locked just after "
                                 "booting up")
        session.cmd("eject -i on %s" % guest_cdrom_device)
        if not vm.check_block_locked(qemu_cdrom_device):
            raise error.TestFail("Device is not locked as expect.")
        return

    error.context("Get a valid cdrom device in guest")
    guest_cdrom_device = ""
    test_cmd = "dd if=%s of=/dev/null bs=1 count=1"
    for dev in guest_cdrom_device_list:
        try:
            tmp_output = session.cmd(test_cmd % dev)
            guest_cdrom_device = dev
            break
        except aexpect.ShellError:
            logging.warn(tmp_output)
    if not guest_cdrom_device:
        raise error.TestFail("Could not find a valid cdrom device")

    error.context("Detecting the existence of a cdrom image file", logging.info)
    qemu_cdrom_device = vm.get_block({'file': iso_image})
    if not qemu_cdrom_device:
        qemu_cdrom_device = vm.get_block({'backing_file': iso_image})
        if not qemu_cdrom_device:
            raise error.TestFail("Could not find a valid cdrom device"
                                 " matched iso file '%s'" % iso_image)

    session.cmd_output("umount %s" % guest_cdrom_device)
    if params.get('cdrom_test_autounlock') == 'yes':
        error.context("Trying to unlock the cdrom", logging.info)
        func = lambda: not vm.check_block_locked(qemu_cdrom_device)
        if not utils_misc.wait_for(func, 300):
            raise error.TestFail("Device %s could not be auto"
                                 " unlocked" % qemu_cdrom_device)
        del func

    max_times = int(params.get("max_times", 100))
    if params.get("cdrom_test_eject") == "yes":
        eject_test_via_monitor(qemu_cdrom_device, guest_cdrom_device,
                               iso_image, max_times)

    if params.get('cdrom_test_tray_status') == 'yes':
        check_tray_status_test(qemu_cdrom_device, guest_cdrom_device,
                               max_times)

    if params.get('cdrom_test_locked') == 'yes':
        check_tray_locked_test(qemu_cdrom_device, guest_cdrom_device)

    if params.get("cdrom_test_file_operation") == "yes":
        file_operation_test(guest_cdrom_device, session)

    error.context("Cleanup")
    # Return the iso_image_orig
    cdfile = get_cdrom_file(qemu_cdrom_device)
    if cdfile != iso_image_orig:
        time.sleep(workaround_eject_time)
        session.cmd('eject %s' % guest_cdrom_device)
        eject_cdrom(qemu_cdrom_device, vm.monitor)
        if get_cdrom_file(qemu_cdrom_device) is not None:
            raise error.TestFail("Device %s was not ejected"
                                 "in cleanup stage" % qemu_cdrom_device)

        change_cdrom(qemu_cdrom_device, iso_image_orig, vm.monitor)
        if get_cdrom_file(qemu_cdrom_device) != iso_image_orig:
            raise error.TestFail("Could not change cdrom image %s" % iso_image)

    session.close()
    cleanup_cdroms(iso_image_dir)
