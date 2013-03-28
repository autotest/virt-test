"""
KVM cdrom test
@author: Amos Kong <akong@redhat.com>
@author: Lucas Meneghel Rodrigues <lmr@redhat.com>
@author: Lukas Doktor <ldoktor@redhat.com>
@author: Jiri Zupka <jzupka@redhat.com>
@copyright: 2011 Red Hat, Inc.
"""
import logging, re, time, os, sys
from autotest.client.shared import error
from autotest.client import utils
from autotest.client.shared.syncdata import SyncData
from virttest import utils_misc, aexpect, qemu_monitor
from virttest import env_process, data_dir, utils_test


@error.context_aware
def run_cdrom(test, params, env):
    """
    KVM cdrom test:

    1) Boot up a VM with one iso.
    2) Check if VM identifies correctly the iso file.
    3) * If cdrom_test_autounlock is set, verifies that device is unlocked
       <300s after boot
    4) Eject cdrom using monitor and change with another iso several times.
    5) * If cdrom_test_tray_status = yes, tests tray reporting.
    6) Try to format cdrom and check the return string.
    7) Mount cdrom device.
    8) Copy file from cdrom and compare files using diff.
    9) Umount and mount several times.

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.

    @param cfg: workaround_eject_time - Some versions of qemu are unable to
                                        eject CDROM directly after insert
    @param cfg: cdrom_test_autounlock - Test whether guest OS unlocks cdrom
                                        after boot (<300s after VM is booted)
    @param cfg: cdrom_test_tray_status - Test tray reporting (eject and insert
                                         CD couple of times in guest).

    @warning: Check dmesg for block device failures
    """
    # Some versions of qemu are unable to eject CDROM directly after insert
    workaround_eject_time = float(params.get('workaround_eject_time', 0))

    login_timeout = int(params.get("login_timeout", 360))
    cdrom_prepare_timeout = int(params.get("cdrom_preapre_timeout", 360))

    @error.context_aware
    def create_cdrom(params, name, prepare=True, file_size=None):
        """
        Creates 'new' cdrom with one file on it

        @param params: paramters for test
        @param name: name of new cdrom file
        @param preapre: if True then it prepare cd images.
        @param file_size: Size of CDrom in MB

        @return: path to new cdrom file.
        """
        error.context("creating test cdrom")
        cdrom_cd1 = params.get("cdrom_cd1")
        if not os.path.isabs(cdrom_cd1):
            cdrom_cd1 = os.path.join(data_dir.get_data_dir(), cdrom_cd1)
        cdrom_dir = os.path.dirname(cdrom_cd1)
        if file_size is None:
            file_size = 10

        file_name = os.path.join(cdrom_dir, "%s.iso" % (name))
        if prepare:
            utils.run("dd if=/dev/urandom of=%s bs=1M count=%d" %
                                                            (name, file_size))
            utils.run("mkisofs -o %s %s" % (file_name, name))
            utils.run("rm -rf %s" % (name))
        return file_name


    def cleanup_cdrom(path):
        """ Removes created cdrom """
        error.context("cleaning up temp cdrom images")
        os.remove("%s" % path)


    def get_cdrom_file(vm, device):
        """
        @param vm: VM object
        @param device: qemu monitor device
        @return: file associated with $device device
        """
        blocks = vm.monitor.info("block")
        cdfile = None
        if isinstance(blocks, str):
            cdfile = re.findall('%s: .*file=(\S*) ' % device, blocks)
            if not cdfile:
                return None
            else:
                cdfile = cdfile[0]
        else:
            for block in blocks:
                if block['device'] == device:
                    try:
                        cdfile = block['inserted']['file']
                    except KeyError:
                        continue
        return cdfile


    def check_cdrom_tray(vm, cdrom):
        """
        Checks whether the tray is opend

        @param vm: VM object
        @param cdrom: cdrom object
        """
        blocks = vm.monitor.info("block")
        if isinstance(blocks, str):
            for block in blocks.splitlines():
                if cdrom in block:
                    if "tray-open=1" in block:
                        return True
                    elif "tray-open=0" in block:
                        return False
        else:
            for block in blocks:
                if block['device'] == cdrom and 'tray_open' in block.keys():
                    return block['tray_open']
        return None


    @error.context_aware
    def check_cdrom_lock(vm, cdrom):
        """
        Checks whether the cdrom is locked

        @param vm: VM object
        @param cdrom: cdrom object

        @return: Cdrom state if locked return True
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
        else:
            for block in blocks:
                if block['device'] == cdrom and 'locked' in block.keys():
                    return block['locked']
        return None



    def eject_cdrom(device, monitor):
        """ Ejects the cdrom using kvm-monitor """
        if isinstance(monitor, qemu_monitor.HumanMonitor):
            monitor.cmd("eject %s" % device)
        elif isinstance(monitor, qemu_monitor.QMPMonitor):
            monitor.cmd("eject", args={'device': device})


    def change_cdrom(device, target, monitor):
        """ Changes the medium using kvm-monitor """
        if isinstance(monitor, qemu_monitor.HumanMonitor):
            monitor.cmd("change %s %s" % (device, target))
        elif isinstance(monitor, qemu_monitor.QMPMonitor):
            monitor.cmd("change", args={'device': device, 'target': target})


    @error.context_aware
    def get_device(vm, dev_file_path):
        """
        Get vm device class from device path.

        @param vm: VM object.
        @param dev_file_path: Device file path.
        @return: device object
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

        @param vm: VM where to find a disk.
        @param src_path: Source of data
        @param dst_path: Path to destination
        @param copy_timeout: Timeout for copy
        @param dsize: Size of data block which is periodical copied.
        """
        if copy_timeout is None:
            copy_timeout = 120
        session = vm.wait_for_login(timeout=login_timeout)
        cmd = ("nohup cp %s %s 2> /dev/null &" % (src_path, dst_path))
        pid = re.search(r"\[.+\] (.+)",
                        session.cmd_output(cmd, timeout=copy_timeout))
        return pid.group(1)


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
            self.cdrom_orig = create_cdrom(params, "orig")
            self.cdrom_new = create_cdrom(params, "new")
            self.cdrom_dir = os.path.dirname(self.cdrom_new)
            vm = env.get_vm(params["main_vm"])
            vm.create()

            self.session = vm.wait_for_login(timeout=login_timeout)
            cdrom = self.cdrom_orig
            output = self.session.get_command_output("ls /dev/cdrom*")
            cdrom_dev_list = re.findall("/dev/cdrom-\w+|/dev/cdrom\d*", output)
            logging.debug("cdrom_dev_list: %s", cdrom_dev_list)
            error.context("Detecting the existence of a cdrom (guest OS side)")
            cdrom_dev = ""
            test_cmd = "dd if=%s of=/dev/null bs=1 count=1"
            for d in cdrom_dev_list:
                try:
                    output = self.session.cmd(test_cmd % d)
                    cdrom_dev = d
                    break
                except aexpect.ShellError:
                    logging.error(output)
            if not cdrom_dev:
                raise error.TestFail("Could not find a valid cdrom device")

            error.context("Detecting the existence of a cdrom (qemu side)")
            cdfile = cdrom
            device = get_device(vm, cdfile)

            self.session.get_command_output("umount %s" % cdrom_dev)
            if params.get('cdrom_test_autounlock') == 'yes':
                error.context("Trying to unlock the cdrom")
                _f = lambda: not vm.check_block_locked(device)
                if not utils_misc.wait_for(_f, 300):
                    raise error.TestFail("Device %s could not be"
                                         " unlocked" % (device))

            max_times = int(params.get("max_times", 100))
            error.context("Eject the cdrom in monitor %s times" % max_times)
            for i in range(1, max_times):
                self.session.cmd('eject %s' % cdrom_dev)
                eject_cdrom(device, vm.monitor)
                time.sleep(2)
                if get_cdrom_file(vm, device) is not None:
                    raise error.TestFail("Device %s was not ejected (%s)" %
                                                                    (cdrom, i))

                cdrom = self.cdrom_new
                # On even attempts, try to change the cdrom
                if i % 2 == 0:
                    cdrom = self.cdrom_orig
                change_cdrom(device, cdrom, vm.monitor)
                if get_cdrom_file(vm, device) != cdrom:
                    raise error.TestFail("It wasn't possible to change "
                                         "cdrom %s (%s)" % (cdrom, i))
                time.sleep(workaround_eject_time)

            error.context('Eject the cdrom in guest %s times' % max_times)
            if params.get('cdrom_test_tray_status') != 'yes':
                pass
            elif check_cdrom_tray(vm, device) is None:
                logging.error("Tray reporting not supported by qemu!")
                logging.error("cdrom_test_tray_status skipped...")
            else:
                for i in range(1, max_times):
                    self.session.cmd('eject %s' % cdrom_dev)
                    if not check_cdrom_tray(vm, device):
                        raise error.TestFail("Monitor reports closed"
                                             " tray (%s)" % (i))
                    self.session.cmd('dd if=%s of=/dev/null count=1' %
                                                                  (cdrom_dev))
                    if check_cdrom_tray(vm, device):
                        raise error.TestFail("Monitor reports opened"
                                             " tray (%s)" % (i))
                    time.sleep(workaround_eject_time)

            error.context("Check whether the cdrom is read-only")
            try:
                output = self.session.cmd("echo y | mkfs %s" % cdrom_dev)
                raise error.TestFail("Attempt to format cdrom %s succeeded" %
                                                                   (cdrom_dev))
            except aexpect.ShellError:
                pass

            error.context("Mounting the cdrom under /mnt")
            self.session.cmd("mount %s %s" % (cdrom_dev, "/mnt"), timeout=30)

            filename = "new"

            error.context("File copying test")
            self.session.cmd("rm -f /tmp/%s" % filename)
            self.session.cmd("cp -f /mnt/%s /tmp/" % filename)

            error.context("Compare file on disk and on cdrom")
            f1_hash = self.session.cmd("md5sum /mnt/%s" % filename).split()[0]
            f2_hash = self.session.cmd("md5sum /tmp/%s" % filename).split()[0]
            if f1_hash.strip() != f2_hash.strip():
                raise error.TestFail("On disk and on cdrom files are"
                                     " different, md5 mismatch")

            error.context("Mount/Unmount cdrom for %s times" % max_times)
            for i in range(1, max_times):
                try:
                    self.session.cmd("umount %s" % cdrom_dev)
                    self.session.cmd("mount %s /mnt" % cdrom_dev)
                except aexpect.ShellError:
                    logging.debug(self.session.cmd("cat /etc/mtab"))
                    raise

            self.session.cmd("umount %s" % cdrom_dev)

            error.context("Cleanup")
            # Return the self.cdrom_orig
            cdfile = get_cdrom_file(vm, device)
            if cdfile != self.cdrom_orig:
                time.sleep(workaround_eject_time)
                self.session.cmd('eject %s' % cdrom_dev)
                eject_cdrom(device, vm.monitor)
                if get_cdrom_file(vm, device) is not None:
                    raise error.TestFail("Device %s was not ejected (%s)" %
                                                                    (cdrom, i))

                change_cdrom(device, self.cdrom_orig, vm.monitor)
                if get_cdrom_file(vm, device) != self.cdrom_orig:
                    raise error.TestFail("It wasn't possible to change"
                                         " cdrom %s (%s)" % (cdrom, i))


        def clean(self):
            self.session.close()
            cleanup_cdrom(self.cdrom_orig)
            cleanup_cdrom(self.cdrom_new)


    class Multihost(MiniSubtest):
        def test(self):
            error.context("Preparing migration env and cdroms.")
            mig_protocol = params.get("mig_protocol", "tcp")
            self.mig_type = utils_test.MultihostMigration
            if mig_protocol == "fd":
                self.mig_type = utils_test.MultihostMigrationFd
            if mig_protocol == "exec":
                self.mig_type = utils_test.MultihostMigrationExec

            self.vms = params.get("vms").split(" ")
            self.srchost = params.get("hosts")[0]
            self.dsthost = params.get("hosts")[1]
            self.is_src = params.get("hostid") == self.srchost
            self.mig = self.mig_type(test, params, env, False, )
            self.cdrom_size = int(params.get("cdrom_size", 10))

            if self.is_src:
                self.cdrom_orig = create_cdrom(params, "orig",
                                               file_size=self.cdrom_size)
                self.cdrom_dir = os.path.dirname(self.cdrom_orig)
                params["start_vm"] = "yes"
                env_process.process(test, params, env,
                                    env_process.preprocess_image,
                                    env_process.preprocess_vm)
                vm = env.get_vm(self.vms[0])
                vm.wait_for_login(timeout=login_timeout)
            else:
                self.cdrom_orig = create_cdrom(params, "orig", False)
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
                self.cdrom_new = create_cdrom(params, "new")
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
