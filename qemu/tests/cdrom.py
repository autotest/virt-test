"""
KVM cdrom test
:author: Amos Kong <akong@redhat.com>
:author: Lucas Meneghel Rodrigues <lmr@redhat.com>
:author: Lukas Doktor <ldoktor@redhat.com>
:author: Jiri Zupka <jzupka@redhat.com>
:copyright: 2011 Red Hat, Inc.
"""
import logging
import re
import time
import os
import sys
from autotest.client.shared import error
from autotest.client import utils
from autotest.client.shared.syncdata import SyncData
from virttest import utils_misc, aexpect, qemu_monitor
from virttest import env_process, data_dir, utils_test


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
    11) Reboot vm after vm resume from s3/s4.
        Note: This case requires a qemu cli without setting file property
        for -drive option, and will be separated to a different cfg item.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.

    :param cfg: workaround_eject_time - Some versions of qemu are unable to
                                        eject CDROM directly after insert
    :param cfg: cdrom_test_autounlock - Test whether guest OS unlocks cdrom
                                        after boot (<300s after VM is booted)
    :param cfg: cdrom_test_tray_status - Test tray reporting (eject and insert
                                         CD couple of times in guest).
    :param cfg: cdrom_test_locked -     Test whether cdrom tray lock function
                                        work well in guest.
    :param cfg: cdrom_test_eject -      Test whether cdrom works well after
                                        several times of eject action.
    :param cfg: cdrom_test_file_operation - Test file operation for cdrom,
                                            such as mount/umount, reading files
                                            on cdrom.

    @warning: Check dmesg for block device failures
    """
    # Some versions of qemu are unable to eject CDROM directly after insert
    workaround_eject_time = float(params.get('workaround_eject_time', 0))

    login_timeout = int(params.get("login_timeout", 360))
    cdrom_prepare_timeout = int(params.get("cdrom_preapre_timeout", 360))

    @error.context_aware
    def create_iso_image(params, name, prepare=True, file_size=None):
        """
        Creates 'new' iso image with one file on it

        :param params: parameters for test
        :param name: name of new iso image file
        :param preapre: if True then it prepare cd images.
        :param file_size: Size of iso image in MB

        :return: path to new iso image file.
        """
        error.context("Creating test iso image '%s'" % name, logging.info)
        cdrom_cd1 = params.get("cdrom_cd1")
        if not os.path.isabs(cdrom_cd1):
            cdrom_cd1 = os.path.join(data_dir.get_data_dir(), cdrom_cd1)
        iso_image_dir = os.path.dirname(cdrom_cd1)
        if file_size is None:
            file_size = 10

        file_name = os.path.join(iso_image_dir, "%s.iso" % (name))
        if prepare:
            cmd = "dd if=/dev/urandom of=%s bs=1M count=%d"
            utils.run(cmd % (name, file_size))
            utils.run("mkisofs -o %s %s" % (file_name, name))
            utils.run("rm -rf %s" % (name))
        return file_name

    def cleanup_cdrom(path):
        """ Removes created iso image """
        if path:
            error.context("Cleaning up temp iso image '%s'" % path,
                          logging.info)
            os.remove("%s" % path)

    def get_cdrom_file(vm, qemu_cdrom_device):
        """
        :param vm: VM object
        :param qemu_cdrom_device: qemu monitor device
        :return: file associated with $qemu_cdrom_device device
        """
        blocks = vm.monitor.info("block")
        cdfile = None
        if isinstance(blocks, str):
            tmp_re_str = r'%s: .*file=(\S*) ' % qemu_cdrom_device
            file_list = re.findall(tmp_re_str, blocks)
            if file_list:
                cdfile = file_list[0]
            else:
            # try to deal with new qemu
                tmp_re_str = r'%s: (\S*) \(.*\)' % qemu_cdrom_device
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

    def _get_tray_stat_via_monitor(vm, qemu_cdrom_device):
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
            # fallback to new qemu
            tmp_block = ""
            for block_new in blocks.splitlines():
                if tmp_block and "Removable device" in block_new:
                    if "tray open" in block_new:
                        is_open, checked = (True, True)
                    elif "tray closed" in block_new:
                        is_open, checked = (False, True)
                if qemu_cdrom_device in block_new:
                    tmp_block = block_new
                else:
                    tmp_block = ""
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

    def is_tray_opened(vm, qemu_cdrom_device, mode='monitor',
                       dev_name="/dev/sr0"):
        """
        Checks whether the tray is opend

        :param vm: VM object
        :param qemu_cdrom_device: cdrom image file name.
        :param mode: tray status checking mode, now support:
                     "monitor": get tray status from monitor.
                     "session": get tray status from guest os.
                     "mixed": get tray status first, if failed, try to
                              get the status in guest os again.
        :param dev_name: cdrom device name in guest os.

        :return: True if cdrom tray is open, otherwise False.
                 None if failed to get the tray status.
        """
        is_open, checked = (None, False)

        if mode in ['monitor', 'mixed']:
            is_open, checked = _get_tray_stat_via_monitor(
                vm, qemu_cdrom_device)

        if (mode in ['session', 'mixed']) and not checked:
            session = vm.wait_for_login(timeout=login_timeout)
            tray_cmd = "python /tmp/tray_open.py %s" % dev_name
            o = session.cmd_output(tray_cmd)
            if "cdrom is open" in o:
                is_open, checked = (True, True)
            else:
                is_open, checked = (False, True)
        if checked:
            return is_open
        return None

    @error.context_aware
    def check_cdrom_lock(vm, cdrom):
        """
        Checks whether the cdrom is locked

        :param vm: VM object
        :param cdrom: cdrom object

        :return: Cdrom state if locked return True
        """
        error.context("Check cdrom state of locing.")
        blocks = vm.monitor.info("block")
        if isinstance(blocks, str):
            for block in blocks.splitlines():
                if cdrom in block:
                    if "locked=1" in block:
                        return True
                    elif "locked=0" in block:
                        return False
            # deal with new qemu
            lock_str_new = "locked"
            no_lock_str = "not locked"
            tmp_block = ""
            for block_new in blocks.splitlines():
                if tmp_block and "Removable device" in block_new:
                    if no_lock_str in block_new:
                        return False
                    elif lock_str_new in block_new:
                        return True
                if cdrom in block_new:
                    tmp_block = block_new
                else:
                    tmp_block = ""
        else:
            for block in blocks:
                if block['device'] == cdrom and 'locked' in block.keys():
                    return block['locked']
        return None

    def eject_cdrom(qemu_cdrom_device, monitor):
        """ Ejects the medium using qemu-monitor """
        if isinstance(monitor, qemu_monitor.HumanMonitor):
            monitor.cmd("eject %s" % qemu_cdrom_device)
        elif isinstance(monitor, qemu_monitor.QMPMonitor):
            monitor.cmd("eject", args={'device': qemu_cdrom_device})

    def change_cdrom(qemu_cdrom_device, target, monitor):
        """ Changes the medium using qemu-monitor """
        if isinstance(monitor, qemu_monitor.HumanMonitor):
            monitor.cmd("change %s %s" % (qemu_cdrom_device, target))
        elif isinstance(monitor, qemu_monitor.QMPMonitor):
            args = {'device': qemu_cdrom_device, 'target': target}
            monitor.cmd("change", args=args)

    @error.context_aware
    def get_device(vm, dev_file_path):
        """
        Get vm device class from device path.

        :param vm: VM object.
        :param dev_file_path: Device file path.
        :return: device object
        """
        error.context("Get cdrom device object")
        device = vm.get_block({'file': dev_file_path})
        if not device:
            device = vm.get_block({'backing_file': dev_file_path})
            if not device:
                raise error.TestFail("Could not find a valid cdrom device")
        return device

    def disk_copy(vm, src_path, dst_path, copy_timeout=None, dsize=None):
        """
        Start disk load. Cyclic copy from src_path to dst_path.

        :param vm: VM where to find a disk.
        :param src_path: Source of data
        :param dst_path: Path to destination
        :param copy_timeout: Timeout for copy
        :param dsize: Size of data block which is periodical copied.
        """
        if copy_timeout is None:
            copy_timeout = 120
        session = vm.wait_for_login(timeout=login_timeout)
        cmd = ("nohup cp %s %s 2> /dev/null &" % (src_path, dst_path))
        pid = re.search(r"\[.+\] (.+)",
                        session.cmd_output(cmd, timeout=copy_timeout))
        return pid.group(1)

    def get_empty_cdrom_device(vm):
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

    def eject_test_via_monitor(vm, qemu_cdrom_device, guest_cdrom_device,
                               iso_image_orig, iso_image_new, max_times):
        """
        Test cdrom eject function via qemu monitor.
        """
        error.context("Eject the iso image in monitor %s times" % max_times,
                      logging.info)
        session = vm.wait_for_login(timeout=login_timeout)
        iso_image = iso_image_orig
        for i in range(1, max_times):
            session.cmd('eject %s' % guest_cdrom_device)
            eject_cdrom(qemu_cdrom_device, vm.monitor)
            time.sleep(2)
            if get_cdrom_file(vm, qemu_cdrom_device) is not None:
                raise error.TestFail("Device %s was not ejected"
                                     " (round %s)" % (iso_image, i))

            iso_image = iso_image_new
            # On even attempts, try to change the iso image
            if i % 2 == 0:
                iso_image = iso_image_orig
            change_cdrom(qemu_cdrom_device, iso_image, vm.monitor)
            if get_cdrom_file(vm, qemu_cdrom_device) != iso_image:
                raise error.TestFail("Could not change iso image %s"
                                     " (round %s)" % (iso_image, i))
            time.sleep(workaround_eject_time)

    def check_tray_status_test(vm, qemu_cdrom_device, guest_cdrom_device,
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

        if is_tray_opened(vm, qemu_cdrom_device) is None:
            logging.warn("Tray status reporting is not supported by qemu!")
            logging.warn("cdrom_test_tray_status test is skipped...")
            return

        error.context("Eject the cdrom in guest %s times" % max_times,
                      logging.info)
        session = vm.wait_for_login(timeout=login_timeout)
        for i in range(1, max_times):
            session.cmd('eject %s' % guest_cdrom_device)
            if not is_tray_opened(vm, qemu_cdrom_device):
                raise error.TestFail("Monitor reports tray closed"
                                     " when ejecting (round %s)" % i)
            session.cmd('dd if=%s of=/dev/null count=1' % guest_cdrom_device)
            if is_tray_opened(vm, qemu_cdrom_device):
                raise error.TestFail("Monitor reports tray opened when reading"
                                     " cdrom in guest (round %s)" % i)
            time.sleep(workaround_eject_time)

    def check_tray_locked_test(vm, qemu_cdrom_device, guest_cdrom_device):
        """
        Test cdrom tray locked function.
        """
        error.context("Check cdrom tray status after cdrom is locked",
                      logging.info)
        session = vm.wait_for_login(timeout=login_timeout)
        tmp_is_trap_open = is_tray_opened(vm, qemu_cdrom_device, mode='mixed',
                                          dev_name=guest_cdrom_device)
        if tmp_is_trap_open is None:
            logging.warn("Tray status reporting is not supported by qemu!")
            logging.warn("cdrom_test_locked test is skipped...")
            return

        eject_failed = False
        eject_failed_msg = "Tray should be closed even in locked status"
        session.cmd('eject %s' % guest_cdrom_device)
        tmp_is_trap_open = is_tray_opened(vm, qemu_cdrom_device, mode='mixed',
                                          dev_name=guest_cdrom_device)
        if not tmp_is_trap_open:
            raise error.TestFail("Tray should not in closed status")
        session.cmd('eject -i on %s' % guest_cdrom_device)
        try:
            session.cmd('eject -t %s' % guest_cdrom_device)
        except aexpect.ShellCmdError, e:
            eject_failed = True
            eject_failed_msg += ", eject command failed: %s" % str(e)

        tmp_is_trap_open = is_tray_opened(vm, qemu_cdrom_device, mode='mixed',
                                          dev_name=guest_cdrom_device)
        if (eject_failed or tmp_is_trap_open):
            raise error.TestFail(eject_failed_msg)
        session.cmd('eject -i off %s' % guest_cdrom_device)
        session.cmd('eject -t %s' % guest_cdrom_device)

    def file_operation_test(session, guest_cdrom_device, max_times):
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
    class MiniSubtest(object):

        def __new__(cls, *args, **kargs):
            self = super(MiniSubtest, cls).__new__(cls)
            ret = None
            exc_info = None
            if args is None:
                args = []
            try:
                try:
                    ret = self.test(*args, **kargs)
                except Exception:
                    exc_info = sys.exc_info()
            finally:
                if hasattr(self, "clean"):
                    try:
                        self.clean()
                    except Exception:
                        if exc_info is None:
                            raise
                    if exc_info:
                        raise exc_info[0], exc_info[1], exc_info[2]
            return ret

    class test_singlehost(MiniSubtest):

        def test(self):
            self.iso_image_orig = None
            self.iso_image_new = None
            if (not params.get("not_insert_at_start")
                    or params.get("not_insert_at_start") == "no"):
                self.iso_image_orig = create_iso_image(params, "orig")
                self.iso_image_new = create_iso_image(params, "new")
                self.cdrom_dir = os.path.dirname(self.iso_image_new)
            vm = env.get_vm(params["main_vm"])
            vm.create()

            self.session = vm.wait_for_login(timeout=login_timeout)
            pre_cmd = params.get("pre_cmd")
            if pre_cmd:
                self.session.cmd(pre_cmd, timeout=120)
                self.session = vm.reboot()
            iso_image = self.iso_image_orig
            error.context("Query cdrom devices in guest")
            tmp_output = self.session.cmd_output("ls /dev/cdrom*")
            tmp_re_str = r"/dev/cdrom-\w+|/dev/cdrom\d*"
            guest_cdrom_device_list = re.findall(tmp_re_str, tmp_output)
            logging.debug("guest_cdrom_device_list: '%s'",
                          guest_cdrom_device_list)

            if params.get('not_insert_at_start') == "yes":
                error.context("Locked without media present", logging.info)
                # XXX: The device got from monitor might not match with the guest
                # defice if there are multiple cdrom devices.
                qemu_cdrom_device = get_empty_cdrom_device(vm)
                guest_cdrom_device = guest_cdrom_device_list[0]
                if vm.check_block_locked(qemu_cdrom_device):
                    raise error.TestFail("Device should not be locked just"
                                         " after booting up")
                self.session.cmd("eject -i on %s" % guest_cdrom_device)
                if not vm.check_block_locked(qemu_cdrom_device):
                    raise error.TestFail("Device is not locked as expect.")
                return

            error.context("Detecting the existence of a cdrom (guest OS side)",
                          logging.info)
            guest_cdrom_device = ""
            test_cmd = "dd if=%s of=/dev/null bs=1 count=1"
            for dev in guest_cdrom_device_list:
                try:
                    tmp_output = self.session.cmd(test_cmd % dev)
                    guest_cdrom_device = dev
                    break
                except aexpect.ShellError:
                    logging.error(tmp_output)
            if not guest_cdrom_device:
                raise error.TestFail("Could not find a valid cdrom device")

            error.context("Detecting the existence of a cdrom (qemu side)",
                          logging.info)
            qemu_cdrom_device = get_device(vm, iso_image)

            self.session.get_command_output("umount %s" % guest_cdrom_device)
            if params.get('cdrom_test_autounlock') == 'yes':
                error.context("Trying to unlock the cdrom", logging.info)
                _f = lambda: not vm.check_block_locked(qemu_cdrom_device)
                if not utils_misc.wait_for(_f, 300):
                    raise error.TestFail("Device %s could not be"
                                         " unlocked" % (qemu_cdrom_device))
                del _f

            max_test_times = int(params.get("cdrom_max_test_times", 100))
            if params.get("cdrom_test_eject") == "yes":
                eject_test_via_monitor(vm, qemu_cdrom_device,
                                       guest_cdrom_device, self.iso_image_orig,
                                       self.iso_image_new, max_test_times)

            if params.get('cdrom_test_tray_status') == 'yes':
                check_tray_status_test(vm, qemu_cdrom_device,
                                       guest_cdrom_device, max_test_times)

            if params.get('cdrom_test_locked') == 'yes':
                check_tray_locked_test(vm, qemu_cdrom_device,
                                       guest_cdrom_device)

            error.context("Check whether the cdrom is read-only", logging.info)
            try:
                self.session.cmd("echo y | mkfs %s" % guest_cdrom_device)
                raise error.TestFail("Attempt to format cdrom %s succeeded" %
                                    (guest_cdrom_device))
            except aexpect.ShellError:
                pass

            sub_test = params.get("sub_test")
            if sub_test:
                error.context("Run sub test '%s' before doing file"
                              " operation" % sub_test, logging.info)
                params["cdrom_cd1"] = os.path.basename(iso_image)
                utils_test.run_virt_sub_test(test, params, env, sub_test)

            if params.get("cdrom_test_file_operation") == "yes":
                file_operation_test(self.session, guest_cdrom_device,
                                    max_test_times)

            error.context("Cleanup")
            # Return the self.iso_image_orig
            cdfile = get_cdrom_file(vm, qemu_cdrom_device)
            if cdfile != self.iso_image_orig:
                time.sleep(workaround_eject_time)
                self.session.cmd('eject %s' % guest_cdrom_device)
                eject_cdrom(qemu_cdrom_device, vm.monitor)
                if get_cdrom_file(vm, qemu_cdrom_device) is not None:
                    raise error.TestFail("Device %s was not ejected"
                                         " in clearup stage" % qemu_cdrom_device)

                change_cdrom(
                    qemu_cdrom_device, self.iso_image_orig, vm.monitor)
                if get_cdrom_file(vm, qemu_cdrom_device) != self.iso_image_orig:
                    raise error.TestFail("It wasn't possible to change"
                                         " cdrom %s" % iso_image)
            post_cmd = params.get("post_cmd")
            if post_cmd:
                self.session.cmd(post_cmd)
            if params.get("guest_suspend_type"):
                self.session = vm.reboot()

        def clean(self):
            self.session.close()
            cleanup_cdrom(self.iso_image_orig)
            cleanup_cdrom(self.iso_image_new)

    class Multihost(MiniSubtest):

        def test(self):
            error.context("Preparing migration env and cdroms.")
            mig_protocol = params.get("mig_protocol", "tcp")
            self.mig_type = utils_test.qemu.MultihostMigration
            if mig_protocol == "fd":
                self.mig_type = utils_test.qemu.MultihostMigrationFd
            if mig_protocol == "exec":
                self.mig_type = utils_test.qemu.MultihostMigrationExec

            self.vms = params.get("vms").split(" ")
            self.srchost = params.get("hosts")[0]
            self.dsthost = params.get("hosts")[1]
            self.is_src = params.get("hostid") == self.srchost
            self.mig = self.mig_type(test, params, env, False, )
            self.cdrom_size = int(params.get("cdrom_size", 10))

            if self.is_src:
                self.cdrom_orig = create_iso_image(params, "orig",
                                                   file_size=self.cdrom_size)
                self.cdrom_dir = os.path.dirname(self.cdrom_orig)
                params["start_vm"] = "yes"
                env_process.process(test, params, env,
                                    env_process.preprocess_image,
                                    env_process.preprocess_vm)
                vm = env.get_vm(self.vms[0])
                vm.wait_for_login(timeout=login_timeout)
            else:
                self.cdrom_orig = create_iso_image(params, "orig", False)
                self.cdrom_dir = os.path.dirname(self.cdrom_orig)

        def clean(self):
            self.mig.cleanup()
            if self.is_src:
                cleanup_cdrom(self.cdrom_orig)

    class test_multihost_locking(Multihost):

        def test(self):
            super(test_multihost_locking, self).test()

            error.context("Lock cdrom in VM.")
            if self.is_src:  # Starts in source
                vm = env.get_vm(self.vms[0])
                session = vm.wait_for_login(timeout=login_timeout)
                output = session.get_command_output("ls /dev/cdrom*")
                cdrom_dev_list = re.findall("/dev/cdrom-\w+|/dev/cdrom\d*",
                                            output)
                logging.debug("cdrom_dev_list: %s", cdrom_dev_list)
                device = get_device(vm, self.cdrom_orig)

                session.cmd("eject -i on %s" % (cdrom_dev_list[0]))
                locked = check_cdrom_lock(vm, device)
                if locked:
                    logging.debug("Cdrom device is successfully locked in VM.")
                else:
                    raise error.TestFail("Cdrom device should be locked"
                                         " in VM.")

            self.mig._hosts_barrier(self.mig.hosts, self.mig.hosts,
                                    'cdrom_dev', cdrom_prepare_timeout)

            self.mig.migrate_wait([self.vms[0]], self.srchost, self.dsthost)

            if not self.is_src:  # Starts in dest
                vm = env.get_vm(self.vms[0])
                session = vm.wait_for_login(timeout=login_timeout)
                output = session.get_command_output("ls /dev/cdrom*")
                cdrom_dev_list = re.findall("/dev/cdrom-\w+|/dev/cdrom\d*",
                                            output)
                logging.debug("cdrom_dev_list: %s", cdrom_dev_list)
                device = get_device(vm, self.cdrom_orig)

                locked = check_cdrom_lock(vm, device)
                if locked:
                    logging.debug("Cdrom device stayed locked after "
                                  "migration in VM.")
                else:
                    raise error.TestFail("Cdrom device should stayed locked"
                                         " after migration in VM.")

            error.context("Unlock cdrom from VM.")
            if not self.is_src:  # Starts in dest
                session.cmd("eject -i off %s" % (cdrom_dev_list[0]))
                locked = check_cdrom_lock(vm, device)
                if not locked:
                    logging.debug("Cdrom device is successfully unlocked"
                                  " from VM.")
                else:
                    raise error.TestFail("Cdrom device should be unlocked"
                                         " in VM.")

            self.mig.migrate_wait([self.vms[0]], self.dsthost, self.srchost)

            if self.is_src:   # Starts in source
                locked = check_cdrom_lock(vm, device)
                if not locked:
                    logging.debug("Cdrom device stayed unlocked after "
                                  "migration in VM.")
                else:
                    raise error.TestFail("Cdrom device should stayed unlocked"
                                         " after migration in VM.")

            self.mig._hosts_barrier(self.mig.hosts, self.mig.hosts,
                                    'Finish_cdrom_test', login_timeout)

        def clean(self):
            super(test_multihost_locking, self).clean()

    class test_multihost_ejecting(Multihost):

        def test(self):
            super(test_multihost_ejecting, self).test()

            if self.is_src:  # Starts in source
                self.cdrom_new = create_iso_image(params, "new")
                vm = env.get_vm(self.vms[0])
                session = vm.wait_for_login(timeout=login_timeout)
                output = session.get_command_output("ls /dev/cdrom*")
                cdrom_dev_list = re.findall("/dev/cdrom-\w+|/dev/cdrom\d*",
                                            output)
                logging.debug("cdrom_dev_list: %s", cdrom_dev_list)
                device = get_device(vm, self.cdrom_orig)
                cdrom = cdrom_dev_list[0]

                error.context("Eject cdrom.")
                session.cmd('eject %s' % cdrom)
                eject_cdrom(device, vm.monitor)
                time.sleep(2)
                if get_cdrom_file(vm, device) is not None:
                    raise error.TestFail("Device %s was not ejected" % (cdrom))

                cdrom = self.cdrom_new

                error.context("Change cdrom.")
                change_cdrom(device, cdrom, vm.monitor)
                if get_cdrom_file(vm, device) != cdrom:
                    raise error.TestFail("It wasn't possible to change "
                                         "cdrom %s" % (cdrom))
                time.sleep(workaround_eject_time)

            self.mig._hosts_barrier(self.mig.hosts, self.mig.hosts,
                                    'cdrom_dev', cdrom_prepare_timeout)

            self.mig.migrate_wait([self.vms[0]], self.srchost, self.dsthost)

        def clean(self):
            if self.is_src:
                cleanup_cdrom(self.cdrom_new)
            super(test_multihost_ejecting, self).clean()

    class test_multihost_copy(Multihost):

        def test(self):
            super(test_multihost_copy, self).test()
            copy_timeout = int(params.get("copy_timeout", 480))
            checksum_timeout = int(params.get("checksum_timeout", 180))

            pid = None
            sync_id = {'src': self.srchost,
                       'dst': self.dsthost,
                       "type": "file_trasfer"}
            filename = "orig"

            if self.is_src:  # Starts in source
                vm = env.get_vm(self.vms[0])
                vm.monitor.migrate_set_speed("1G")
                session = vm.wait_for_login(timeout=login_timeout)
                output = session.get_command_output("ls /dev/cdrom*")
                cdrom_dev_list = re.findall("/dev/cdrom-\w+|/dev/cdrom\d*",
                                            output)
                logging.debug("cdrom_dev_list: %s", cdrom_dev_list)
                cdrom = cdrom_dev_list[0]

                error.context("Mount and copy data")
                session.cmd("mount %s %s" % (cdrom, "/mnt"), timeout=30)

                error.context("File copying test")
                session.cmd("rm -f /%s" % filename)

                pid = disk_copy(vm, os.path.join("/mnt", filename), "/",
                                copy_timeout)

            sync = SyncData(self.mig.master_id(), self.mig.hostid,
                            self.mig.hosts, sync_id, self.mig.sync_server)

            pid = sync.sync(pid, timeout=cdrom_prepare_timeout)[self.srchost]

            self.mig.migrate_wait([self.vms[0]], self.srchost, self.dsthost)

            if not self.is_src:  # Starts in source
                vm = env.get_vm(self.vms[0])
                session = vm.wait_for_login(timeout=login_timeout)
                error.context("Wait for copy finishing.")
                status = int(session.cmd_status("wait %s" % pid,
                                                timeout=copy_timeout))
                if not status in [0, 127]:
                    raise error.TestFail("Copy process was terminatted with"
                                         " error code %s" % (status))
                if status == 127:
                    logging.warn("Param cdrom_size should be bigger because "
                                 "copying finished before migration finish.")

                error.context("Compare file on disk and on cdrom")
                f1_hash = session.cmd("md5sum /mnt/%s" % filename,
                                      timeout=checksum_timeout).split()[0]
                f2_hash = session.cmd("md5sum /%s" % filename,
                                      timeout=checksum_timeout).split()[0]
                if f1_hash.strip() != f2_hash.strip():
                    raise error.TestFail("On disk and on cdrom files are"
                                         " different, md5 mismatch")
                session.cmd("rm -f /%s" % filename)

            self.mig._hosts_barrier(self.mig.hosts, self.mig.hosts,
                                    'Finish_cdrom_test', login_timeout)

        def clean(self):
            super(test_multihost_copy, self).clean()

    test_type = params.get("test_type", "test_singlehost")
    if (test_type in locals()):
        tests_group = locals()[test_type]
        tests_group()
    else:
        raise error.TestFail("Test group '%s' is not defined in"
                             " migration_with_dst_problem test" % test_type)
