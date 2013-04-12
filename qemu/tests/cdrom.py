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
from virttest import utils_misc, utils_test, aexpect, qemu_monitor


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
    10) Check if the cdrom lock works well when cdrom file is not inserted.
        This case required the a command line without cdrom file and will be
        separated to a different cfg item.

    @param test: QEMU test object
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
    def master_cdroms(params):
        """ Creates 'new' cdrom with one file on it """
        error.context("creating test cdrom", logging.info)
        os.chdir(test.tmpdir)
        cdrom_cd1 = params.get("cdrom_cd1")
        if not os.path.isabs(cdrom_cd1):
            cdrom_cd1 = os.path.join(test.bindir, cdrom_cd1)
        cdrom_dir = os.path.dirname(cdrom_cd1)
        utils.run("dd if=/dev/urandom of=orig bs=10M count=1")
        utils.run("dd if=/dev/urandom of=new bs=10M count=1")
        utils.run("mkisofs -o %s/orig.iso orig" % cdrom_dir)
        utils.run("mkisofs -o %s/new.iso new" % cdrom_dir)
        return "%s/new.iso" % cdrom_dir

    def cleanup_cdroms(cdrom_dir):
        """ Removes created cdrom """
        error.context("cleaning up temp cdrom images", logging.info)
        os.remove("%s/new.iso" % cdrom_dir)

    def get_cdrom_file(device):
        """
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

    def check_cdrom_tray(cdrom, mode='monitor', dev_name="/dev/sr0"):
        """ Checks whether the tray is opend """
        checked = False
        if mode == 'monitor' or mode == 'mixed':
            blocks = vm.monitor.info("block")
            if isinstance(blocks, str):
                for block in blocks.splitlines():
                    if cdrom in block:
                        if "tray-open=1" in block:
                            is_open = True
                            checked = True
                        elif "tray-open=0" in block:
                            is_open = False
                            checked = True
            else:
                for block in blocks:
                    if block['device'] == cdrom:
                        key = filter(lambda x: re.match(r"tray.*open", x),
                            block.keys())
                        # compatible rhel6 and rhel7 diff qmp output
                        if not key:
                            break
                        is_open = block[key[0]]
                        checked = True

        if mode == 'session' or (mode == 'mixed' and not checked):
            tray_cmd = "python /tmp/tray_open.py %s" % dev_name
            o = session.cmd_output(tray_cmd)
            if "cdrom is open" in o:
                is_open = True
                checked = True
            else:
                is_open = False
                checked = True
        if checked:
            return is_open
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


    def get_cdrom_device():
        """Get cdrom device when cdrom is not insert."""
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


    if (not params.get("not_insert_at_start")
        or params.get("not_insert_at_start") == "no"):
        cdrom_new = master_cdroms(params)
        cdrom_dir = os.path.dirname(cdrom_new)


    vm = env.get_vm(params["main_vm"])
    vm.create()

    # Some versions of qemu are unable to eject CDROM directly after insert
    workaround_eject_time = float(params.get('workaround_eject_time', 0))

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    cdrom_orig = params.get("cdrom_cd1")
    if cdrom_orig and not os.path.isabs(cdrom_orig):
        cdrom_orig = os.path.join(test.bindir, cdrom_orig)
    cdrom = cdrom_orig
    output = session.get_command_output("ls /dev/cdrom*")
    cdrom_dev_list = re.findall("/dev/cdrom-\w+|/dev/cdrom\d*", output)
    logging.debug("cdrom_dev_list: %s", cdrom_dev_list)
    if params.get('not_insert_at_start') == "yes":
        error.context("Locked without media present", logging.info)
        device = get_cdrom_device()
        cdrom_dev = cdrom_dev_list[0]
        if vm.check_block_locked(device):
            raise error.TestFail("Device should not be locked just after "
                                 "booting up")
        session.cmd("eject -i on %s" % cdrom_dev)
        if not vm.check_block_locked(device):
            raise error.TestFail("Device is not locked as expect.")
        return

    cdrom_dev = ""
    test_cmd = "dd if=%s of=/dev/null bs=1 count=1"
    for d in cdrom_dev_list:
        try:
            output = session.cmd(test_cmd % d)
            cdrom_dev = d
            break
        except aexpect.ShellError:
            logging.error(output)
    if not cdrom_dev:
        raise error.TestFail("Could not find a valid cdrom device")

    error.context("Detecting the existence of a cdrom", logging.info)
    cdfile = cdrom
    device = vm.get_block({'file': cdfile})
    if not device:
        device = vm.get_block({'backing_file': cdfile})
        if not device:
            raise error.TestFail("Could not find a valid cdrom device")

    session.get_command_output("umount %s" % cdrom_dev)
    if params.get('cdrom_test_autounlock') == 'yes':
        error.context("Trying to unlock the cdrom", logging.info)
        if not utils_misc.wait_for(lambda: not vm.check_block_locked(device),
                                   300):
            raise error.TestFail("Device %s could not be unlocked" % device)

    max_times = int(params.get("max_times", 100))
    error.context("Eject the cdrom in monitor %s times" % max_times,
            logging.info)
    for i in range(1, max_times):
        session.cmd('eject %s' % cdrom_dev)
        eject_cdrom(device, vm.monitor)
        time.sleep(2)
        if get_cdrom_file(device) is not None:
            raise error.TestFail("Device %s was not ejected (%s)" % (cdrom, i))

        cdrom = cdrom_new
        # On even attempts, try to change the cdrom
        if i % 2 == 0:
            cdrom = cdrom_orig
        change_cdrom(device, cdrom, vm.monitor)
        if get_cdrom_file(device) != cdrom:
            raise error.TestFail("It wasn't possible to change cdrom %s (%s)"
                                  % (cdrom, i))
        time.sleep(workaround_eject_time)

    if params.get("tray_check_src"):
        tray_check_src = utils_misc.get_path(test.virtdir,
                                     "deps/%s" % params.get("tray_check_src"))
        vm.copy_files_to(tray_check_src, "/tmp")

    error.context('Eject the cdrom in guest %s times' % max_times,
            logging.info)
    if params.get('cdrom_test_tray_status') != 'yes':
        pass
    elif check_cdrom_tray(device) is None:
        logging.error("Tray reporting not supported by qemu!")
        logging.error("cdrom_test_tray_status skipped...")
    else:
        for i in range(1, max_times):
            session.cmd('eject %s' % cdrom_dev)
            if not check_cdrom_tray(device):
                raise error.TestFail("Monitor reports closed tray (%s)" % i)
            session.cmd('dd if=%s of=/dev/null count=1' % cdrom_dev)
            if check_cdrom_tray(device):
                raise error.TestFail("Monitor reports opened tray (%s)" % i)
            time.sleep(workaround_eject_time)

    error.context("Check cdrom tray status after cdrom is locked",
            logging.info)
    if params.get('cdrom_test_locked') != 'yes':
        pass
    elif check_cdrom_tray(device, mode='mixed', dev_name=cdrom_dev) is None:
        logging.error("Tray reporting not supported by qemu!")
        logging.error("cdrom_test_locked skipped...")
    else:
        eject_failed = False
        eject_failed_msg = "Tray should be closed even in locked status"
        session.cmd('eject %s' % cdrom_dev)
        if not check_cdrom_tray(device, mode='mixed', dev_name=cdrom_dev):
            raise error.TestFail("Tray should not in closed status")
        session.cmd('eject -i on %s' % cdrom_dev)
        try:
            session.cmd('eject -t %s' % cdrom_dev)
        except aexpect.ShellCmdError, e:
            eject_failed = True
            eject_failed_msg += ", eject command failed: %s" % str(e)
        if (eject_failed
            or check_cdrom_tray(device, mode='mixed', dev_name=cdrom_dev)):
            raise error.TestFail(eject_failed_msg)
        session.cmd('eject -i off %s' % cdrom_dev)
        session.cmd('eject -t %s' % cdrom_dev)

    error.context("Check whether the cdrom is read-only", logging.info)
    try:
        output = session.cmd("echo y | mkfs %s" % cdrom_dev)
        raise error.TestFail("Attempt to format cdrom %s succeeded" %
                                                                    cdrom_dev)
    except aexpect.ShellError:
        pass

    sub_test = params.get("sub_test")
    if sub_test:
        error.context("Run sub test '%s' before doing file"
                      " operation" % sub_test, logging.info)
        params["cdrom_cd1"] = os.path.basename(cdrom)
        utils_test.run_virt_sub_test(test, params, env, sub_test)

    error.context("Mounting the cdrom under /mnt", logging.info)
    session.cmd("mount %s %s" % (cdrom_dev, "/mnt"), timeout=30)

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

    error.context("Mount/Unmount cdrom for %s times" % max_times, logging.info)
    for i in range(1, max_times):
        try:
            session.cmd("umount %s" % cdrom_dev)
            session.cmd("mount %s /mnt" % cdrom_dev)
        except aexpect.ShellError:
            logging.debug(session.cmd("cat /etc/mtab"))
            raise

    session.cmd("umount %s" % cdrom_dev)

    error.context("Cleanup", logging.info)
    # Return the cdrom_orig
    cdfile = get_cdrom_file(device)
    if cdfile != cdrom_orig:
        time.sleep(workaround_eject_time)
        session.cmd('eject %s' % cdrom_dev)
        eject_cdrom(device, vm.monitor)
        if get_cdrom_file(device) is not None:
            raise error.TestFail("Device %s was not ejected (%s)" % (cdrom, i))

        change_cdrom(device, cdrom_orig, vm.monitor)
        if get_cdrom_file(device) != cdrom_orig:
            raise error.TestFail("It wasn't possible to change cdrom %s (%s)"
                                  % (cdrom, i))

    session.close()
    cleanup_cdroms(cdrom_dir)
