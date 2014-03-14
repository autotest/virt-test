import os
import time
import commands
import re
import logging
import glob
import threading
import shutil
import sys
import copy
from autotest.client import utils
from autotest.client.shared import error
import aexpect
import qemu_monitor
import ppm_utils
import test_setup
import virt_vm
import video_maker
import utils_misc
import storage
import qemu_storage
import utils_libvirtd
import remote
import data_dir
import utils_net
import utils_disk
import nfs
from autotest.client import local_host


try:
    import PIL.Image
except ImportError:
    logging.warning('No python imaging library installed. PPM image '
                    'conversion to JPEG disabled. In order to enable it, '
                    'please install python-imaging or the equivalent for your '
                    'distro.')

_screendump_thread = None
_screendump_thread_termination_event = None


def preprocess_image(test, params, image_name):
    """
    Preprocess a single QEMU image according to the instructions in params.

    :param test: Autotest test object.
    :param params: A dict containing image preprocessing parameters.
    :note: Currently this function just creates an image if requested.
    """
    base_dir = params.get("images_base_dir", data_dir.get_data_dir())

    if not storage.preprocess_image_backend(base_dir, params, image_name):
        logging.error("Backend can't be prepared correctly.")

    image_filename = storage.get_image_filename(params,
                                                base_dir)

    create_image = False
    if params.get("force_create_image") == "yes":
        create_image = True
    elif (params.get("create_image") == "yes" and not
          storage.file_exists(params, image_filename)):
        create_image = True

    if params.get("backup_image_before_testing", "no") == "yes":
        image = qemu_storage.QemuImg(params, base_dir, image_name)
        image.backup_image(params, base_dir, "backup", True, True)
    if create_image:
        image = qemu_storage.QemuImg(params, base_dir, image_name)
        image.create(params)


def preprocess_vm(test, params, env, name):
    """
    Preprocess a single VM object according to the instructions in params.
    Start the VM if requested and get a screendump.

    :param test: An Autotest test object.
    :param params: A dict containing VM preprocessing parameters.
    :param env: The environment (a dict-like object).
    :param name: The name of the VM object.
    """
    vm = env.get_vm(name)
    vm_type = params.get('vm_type')
    target = params.get('target')
    if not vm:
        vm = env.create_vm(vm_type, target, name, params, test.bindir)
    old_vm = copy.copy(vm)

    remove_vm = False
    if params.get("force_remove_vm") == "yes":
        remove_vm = True

    if remove_vm:
        vm.remove()

    start_vm = False
    update_virtnet = False
    gracefully_kill = params.get("kill_vm_gracefully") == "yes"

    if params.get("migration_mode"):
        start_vm = True
    elif params.get("start_vm") == "yes":
        # need to deal with libvirt VM differently than qemu
        if vm_type == 'libvirt' or vm_type == 'v2v':
            if not vm.is_alive():
                start_vm = True
        else:
            if not vm.is_alive():
                start_vm = True
            if params.get("check_vm_needs_restart", "yes") == "yes":
                if vm.needs_restart(name=name,
                                    params=params,
                                    basedir=test.bindir):
                    vm.devices = None
                    start_vm = True
                    old_vm.destroy(gracefully=gracefully_kill)
                    update_virtnet = True

    if start_vm:
        if vm_type == "libvirt" and params.get("type") != "unattended_install":
            vm.params = params
            vm.start()
        elif vm_type == "v2v":
            vm.params = params
            vm.start()
        else:
            if update_virtnet:
                vm.update_vm_id()
                vm.virtnet = utils_net.VirtNet(params, name, vm.instance)
            # Start the VM (or restart it if it's already up)
            if params.get("reuse_previous_config", "no") == "no":
                vm.create(name, params, test.bindir,
                          migration_mode=params.get("migration_mode"),
                          migration_fd=params.get("migration_fd"),
                          migration_exec_cmd=params.get("migration_exec_cmd_dst"))
            else:
                vm.create(migration_mode=params.get("migration_mode"),
                          migration_fd=params.get("migration_fd"),
                          migration_exec_cmd=params.get("migration_exec_cmd_dst"))
    elif not vm.is_alive():    # VM is dead and won't be started, update params
        vm.devices = None
        vm.params = params
    else:       # VM is alive and we don't care
        if params.get("kill_vm_before_test") == "yes":
            # Destroy the VM if kill_vm_before_test = "yes".
            old_vm.destroy(gracefully=gracefully_kill)
        else:
            # VM is alive and we just need to open the serial console
            vm.create_serial_console()

    pause_vm = False

    if params.get("paused_after_start_vm") == "yes":
        pause_vm = True
        # Check the status of vm
        if (not vm.is_alive()) or (vm.is_paused()):
            pause_vm = False

    if pause_vm:
        vm.pause()


def postprocess_image(test, params, image_name):
    """
    Postprocess a single QEMU image according to the instructions in params.

    :param test: An Autotest test object.
    :param params: A dict containing image postprocessing parameters.
    """
    clone_master = params.get("clone_master", None)
    base_dir = data_dir.get_data_dir()
    image = qemu_storage.QemuImg(params, base_dir, image_name)
    if params.get("check_image") == "yes":
        try:
            if clone_master is None:
                image.check_image(params, base_dir)
            elif clone_master == "yes":
                if image_name in params.get("master_images_clone").split():
                    image.check_image(params, base_dir)
            # Allow test to overwrite any pre-testing  automatic backup
            # with a new backup. i.e. assume pre-existing image/backup
            # would not be usable after this test succeeds. The best
            # example for this is when 'unattended_install' is run.
            if params.get("backup_image", "no") == "yes":
                image.backup_image(params, base_dir, "backup", True)
            elif params.get("restore_image", "no") == "yes":
                image.backup_image(params, base_dir, "restore", True)
        except Exception, e:
            if params.get("restore_image_on_check_error", "no") == "yes":
                image.backup_image(params, base_dir, "restore", True)
            if params.get("remove_image_on_check_error", "no") == "yes":
                cl_images = params.get("master_images_clone", "")
                if image_name in cl_images.split():
                    image.remove()
            raise e
    if params.get("restore_image_after_testing", "no") == "yes":
        image.backup_image(params, base_dir, "restore", True)
    if params.get("remove_image") == "yes":
        if clone_master is None:
            image.remove()
        elif clone_master == "yes":
            if image_name in params.get("master_images_clone").split():
                image.remove()


def postprocess_vm(test, params, env, name):
    """
    Postprocess a single VM object according to the instructions in params.
    Kill the VM if requested and get a screendump.

    :param test: An Autotest test object.
    :param params: A dict containing VM postprocessing parameters.
    :param env: The environment (a dict-like object).
    :param name: The name of the VM object.
    """
    vm = env.get_vm(name)
    if not vm:
        return

    # Close all SSH sessions that might be active to this VM
    for s in [x for x in vm.remote_sessions]:
        try:
            s.close()
            vm.remote_sessions.remove(s)
        except Exception:
            pass

    if params.get("kill_vm") == "yes":
        kill_vm_timeout = float(params.get("kill_vm_timeout", 0))
        if kill_vm_timeout:
            utils_misc.wait_for(vm.is_dead, kill_vm_timeout, 0, 1)
        vm.destroy(gracefully=params.get("kill_vm_gracefully") == "yes")
    else:
        # Close the serial console session, as it'll help
        # keeping the number of filedescriptors used by virt-test honest.
        vm.cleanup_serial_console()


def process_command(test, params, env, command, command_timeout,
                    command_noncritical):
    """
    Pre- or post- custom commands to be executed before/after a test is run

    :param test: An Autotest test object.
    :param params: A dict containing all VM and image parameters.
    :param env: The environment (a dict-like object).
    :param command: Command to be run.
    :param command_timeout: Timeout for command execution.
    :param command_noncritical: If True test will not fail if command fails.
    """
    # Export environment vars
    for k in params:
        os.putenv("KVM_TEST_%s" % k, str(params[k]))
    # Execute commands
    try:
        utils.system("cd %s; %s" % (test.bindir, command))
    except error.CmdError, e:
        if command_noncritical:
            logging.warn(e)
        else:
            raise


class _CreateImages(threading.Thread):

    """
    Thread which creates images. In case of failure it stores the exception
    in self.exc_info
    """

    def __init__(self, image_func, test, images, params, exit_event):
        threading.Thread.__init__(self)
        self.image_func = image_func
        self.test = test
        self.images = images
        self.params = params
        self.exit_event = exit_event
        self.exc_info = None

    def run(self):
        try:
            _process_images_serial(self.image_func, self.test, self.images,
                                   self.params, self.exit_event)
        except Exception:
            self.exc_info = sys.exc_info()
            self.exit_event.set()


def process_images(image_func, test, params):
    """
    Wrapper which chooses the best way to process images.
    :param image_func: Process function
    :param test: An Autotest test object.
    :param params: A dict containing all VM and image parameters.
    """
    images = params.objects("images")
    if len(images) > 20:    # Lets do it in parallel
        _process_images_parallel(image_func, test, params)
    else:
        _process_images_serial(image_func, test, images, params)


def _process_images_serial(image_func, test, images, params, exit_event=None):
    """
    Original process_image function, which allows custom set of images
    :param image_func: Process function
    :param test: An Autotest test object.
    :param images: List of images (usually params.objects("images"))
    :param params: A dict containing all VM and image parameters.
    :param exit_event: (optional) exit event which interrupts the processing
    """
    for image_name in images:
        image_params = params.object_params(image_name)
        image_func(test, image_params, image_name)
        if exit_event and exit_event.is_set():
            logging.error("Received exit_event, stop processing of images.")
            break


def _process_images_parallel(image_func, test, params):
    """
    The same as _process_images but in parallel.
    :param image_func: Process function
    :param test: An Autotest test object.
    :param params: A dict containing all VM and image parameters.
    """
    images = params.objects("images")
    no_threads = min(len(images) / 5,
                     2 * local_host.LocalHost().get_num_cpu())
    exit_event = threading.Event()
    threads = []
    for i in xrange(no_threads):
        imgs = images[i::no_threads]
        threads.append(_CreateImages(image_func, test, imgs, params,
                                     exit_event))
        threads[-1].start()
    finished = False
    while not finished:
        finished = True
        for thread in threads:
            if thread.is_alive():
                finished = False
                time.sleep(0.5)
                break
    if exit_event.is_set():     # Failure in some thread
        logging.error("Image processing failed:")
        for thread in threads:
            if thread.exc_info:     # Throw the first failure
                raise thread.exc_info[1], None, thread.exc_info[2]
    del exit_event
    del threads[:]


def process(test, params, env, image_func, vm_func, vm_first=False):
    """
    Pre- or post-process VMs and images according to the instructions in params.
    Call image_func for each image listed in params and vm_func for each VM.

    :param test: An Autotest test object.
    :param params: A dict containing all VM and image parameters.
    :param env: The environment (a dict-like object).
    :param image_func: A function to call for each image.
    :param vm_func: A function to call for each VM.
    :param vm_first: Call vm_func first or not.
    """
    def _call_vm_func():
        for vm_name in params.objects("vms"):
            vm_params = params.object_params(vm_name)
            vm_func(test, vm_params, env, vm_name)

    def _call_image_func():
        if params.get("skip_image_processing") == "yes":
            return

        if params.objects("vms"):
            for vm_name in params.objects("vms"):
                vm_params = params.object_params(vm_name)
                vm = env.get_vm(vm_name)
                unpause_vm = False
                if vm is not None and vm.is_alive() and not vm.is_paused():
                    vm.pause()
                    unpause_vm = True
                try:
                    process_images(image_func, test, vm_params)
                finally:
                    if unpause_vm:
                        vm.resume()
        else:
            process_images(image_func, test, params)

    if not vm_first:
        _call_image_func()

    _call_vm_func()

    if vm_first:
        _call_image_func()


@error.context_aware
def preprocess(test, params, env):
    """
    Preprocess all VMs and images according to the instructions in params.
    Also, collect some host information, such as the KVM version.

    :param test: An Autotest test object.
    :param params: A dict containing all VM and image parameters.
    :param env: The environment (a dict-like object).
    """
    error.context("preprocessing")
    # First, let's verify if this test does require root or not. If it
    # does and the test suite is running as a regular user, we shall just
    # throw a TestNAError exception, which will skip the test.
    if params.get('requires_root', 'no') == 'yes':
        utils_misc.verify_running_as_root()

    port = params.get('shell_port')
    prompt = params.get('shell_prompt')
    address = params.get('ovirt_node_address')
    username = params.get('ovirt_node_user')
    password = params.get('ovirt_node_password')

    setup_pb = False
    for nic in params.get('nics', "").split():
        nic_params = params.object_params(nic)
        if nic_params.get('netdst') == 'private':
            setup_pb = True
            params_pb = nic_params
            params['netdst_%s' % nic] = nic_params.get("priv_brname", 'atbr0')

    if setup_pb:
        brcfg = test_setup.PrivateBridgeConfig(params_pb)
        brcfg.setup()

    base_dir = data_dir.get_data_dir()
    if params.get("storage_type") == "iscsi":
        iscsidev = qemu_storage.Iscsidev(params, base_dir, "iscsi")
        params["image_name"] = iscsidev.setup()
        params["image_raw_device"] = "yes"

    if params.get("storage_type") == "lvm":
        lvmdev = qemu_storage.LVMdev(params, base_dir, "lvm")
        params["image_name"] = lvmdev.setup()
        params["image_raw_device"] = "yes"
        env.register_lvmdev("lvm_%s" % params["main_vm"], lvmdev)

    if params.get("storage_type") == "nfs":
        image_nfs = nfs.Nfs(params)
        image_nfs.setup()
        image_name_only = os.path.basename(params["image_name"])
        params['image_name'] = os.path.join(image_nfs.mount_dir,
                                            image_name_only)
        for image_name in params.objects("images"):
            name_tag = "image_name_%s" % image_name
            if params.get(name_tag):
                image_name_only = os.path.basename(params[name_tag])
                params[name_tag] = os.path.join(image_nfs.mount_dir,
                                                image_name_only)

    # Start tcpdump if it isn't already running
    # The fact it has to be started here is so that the test params
    # have to be honored.
    env.start_tcpdump(params)

    # Destroy and remove VMs that are no longer needed in the environment
    requested_vms = params.objects("vms")
    for key in env.keys():
        vm = env[key]
        if not isinstance(vm, virt_vm.BaseVM):
            continue
        if not vm.name in requested_vms:
            vm.destroy()
            del env[key]

    if (params.get("auto_cpu_model") == "yes" and
            params.get("vm_type") == "qemu"):
        if not env.get("cpu_model"):
            env["cpu_model"] = utils_misc.get_qemu_best_cpu_model(params)
        params["cpu_model"] = env.get("cpu_model")

    kvm_ver_cmd = params.get("kvm_ver_cmd", "")

    if kvm_ver_cmd:
        try:
            cmd_result = utils.run(kvm_ver_cmd)
            kvm_version = cmd_result.stdout.strip()
        except error.CmdError:
            kvm_version = "Unknown"
    else:
        # Get the KVM kernel module version and write it as a keyval
        if os.path.exists("/dev/kvm"):
            try:
                kvm_version = open("/sys/module/kvm/version").read().strip()
            except Exception:
                kvm_version = os.uname()[2]
        else:
            logging.warning("KVM module not loaded")
            kvm_version = "Unknown"

    logging.debug("KVM version: %s" % kvm_version)
    test.write_test_keyval({"kvm_version": kvm_version})

    # Get the KVM userspace version and write it as a keyval
    kvm_userspace_ver_cmd = params.get("kvm_userspace_ver_cmd", "")

    if kvm_userspace_ver_cmd:
        try:
            cmd_result = utils.run(kvm_userspace_ver_cmd)
            kvm_userspace_version = cmd_result.stdout.strip()
        except error.CmdError:
            kvm_userspace_version = "Unknown"
    else:
        qemu_path = utils_misc.get_qemu_binary(params)
        version_line = commands.getoutput("%s -help | head -n 1" % qemu_path)
        matches = re.findall("[Vv]ersion .*?,", version_line)
        if matches:
            kvm_userspace_version = " ".join(matches[0].split()[1:]).strip(",")
        else:
            kvm_userspace_version = "Unknown"

    logging.debug("KVM userspace version: %s" % kvm_userspace_version)
    test.write_test_keyval({"kvm_userspace_version": kvm_userspace_version})

    if params.get("setup_hugepages") == "yes":
        h = test_setup.HugePageConfig(params)
        suggest_mem = h.setup()
        if suggest_mem is not None:
            params['mem'] = suggest_mem
        if params.get("vm_type") == "libvirt":
            utils_libvirtd.libvirtd_restart()

    if params.get("setup_thp") == "yes":
        thp = test_setup.TransparentHugePageConfig(test, params)
        thp.setup()

    if params.get("setup_ksm") == "yes":
        ksm = test_setup.KSMConfig(params, env)
        ksm.setup(env)

    # Execute any pre_commands
    if params.get("pre_command"):
        process_command(test, params, env, params.get("pre_command"),
                        int(params.get("pre_command_timeout", "600")),
                        params.get("pre_command_noncritical") == "yes")

    # if you want set "pci=nomsi" before test, set "disable_pci_msi = yes"
    # and pci_msi_sensitive = "yes"
    if params.get("pci_msi_sensitive", "no") == "yes":
        disable_pci_msi = params.get("disable_pci_msi", "no")
        image_filename = storage.get_image_filename(params,
                                                    data_dir.get_data_dir())
        grub_file = params.get("grub_file", "/boot/grub2/grub.cfg")
        kernel_cfg_pos_reg = params.get("kernel_cfg_pos_reg",
                                        r".*vmlinuz-\d+.*")
        msi_keyword = params.get("msi_keyword", " pci=nomsi")

        disk_obj = utils_disk.GuestFSModiDisk(image_filename)
        kernel_config_ori = disk_obj.read_file(grub_file)
        kernel_config = re.findall(kernel_cfg_pos_reg, kernel_config_ori)
        if not kernel_config:
            raise error.TestError("Cannot find the kernel config, reg is %s" %
                                  kernel_cfg_pos_reg)
        kernel_config_line = kernel_config[0]

        kernel_need_modify = False
        if disable_pci_msi == "yes":
            if not re.findall(msi_keyword, kernel_config_line):
                kernel_config_set = kernel_config_line + msi_keyword
                kernel_need_modify = True
        else:
            if re.findall(msi_keyword, kernel_config_line):
                kernel_config_set = re.sub(msi_keyword, "", kernel_config_line)
                kernel_need_modify = True

        if kernel_need_modify:
            for vm in env.get_all_vms():
                if vm:
                    vm.destroy()
                    env.unregister_vm(vm.name)
            disk_obj.replace_image_file_content(grub_file, kernel_config_line,
                                                kernel_config_set)
        logging.debug("Guest cmdline 'pci=nomsi' setting is: [ %s ]" %
                      disable_pci_msi)

    kernel_extra_params = params.get("kernel_extra_params")
    if kernel_extra_params:
        image_filename = storage.get_image_filename(params,
                                                    data_dir.get_data_dir())
        grub_file = params.get("grub_file", "/boot/grub2/grub.cfg")
        kernel_cfg_pos_reg = params.get("kernel_cfg_pos_reg",
                                        r".*vmlinuz-\d+.*")

        disk_obj = utils_disk.GuestFSModiDisk(image_filename)
        kernel_config_ori = disk_obj.read_file(grub_file)
        kernel_config = re.findall(kernel_cfg_pos_reg, kernel_config_ori)
        if not kernel_config:
            raise error.TestError("Cannot find the kernel config, reg is %s" %
                                  kernel_cfg_pos_reg)
        kernel_config_line = kernel_config[0]

        kernel_need_modify = False
        if not re.findall(kernel_extra_params, kernel_config_line):
            kernel_config_set = kernel_config_line + kernel_extra_params
            kernel_need_modify = True

        if kernel_need_modify:
            for vm in env.get_all_vms():
                if vm:
                    vm.destroy()
                    env.unregister_vm(vm.name)
            disk_obj.replace_image_file_content(grub_file, kernel_config_line,
                                                kernel_config_set)
        logging.debug("Guest cmdline extra_params setting is: [ %s ]" %
                      kernel_extra_params)

    # Clone master image from vms.
    base_dir = data_dir.get_data_dir()
    if params.get("master_images_clone"):
        for vm_name in params.get("vms").split():
            vm = env.get_vm(vm_name)
            if vm:
                vm.destroy()
                env.unregister_vm(vm_name)

            vm_params = params.object_params(vm_name)
            for image in vm_params.get("master_images_clone").split():
                image_obj = qemu_storage.QemuImg(params, base_dir, image)
                image_obj.clone_image(params, vm_name, image, base_dir)

    # Preprocess all VMs and images
    if params.get("not_preprocess", "no") == "no":
        process(test, params, env, preprocess_image, preprocess_vm)

    # Start the screendump thread
    if params.get("take_regular_screendumps") == "yes":
        global _screendump_thread, _screendump_thread_termination_event
        _screendump_thread_termination_event = threading.Event()
        _screendump_thread = threading.Thread(target=_take_screendumps,
                                              name='ScreenDump',
                                              args=(test, params, env))
        _screendump_thread.start()

    return params


@error.context_aware
def postprocess(test, params, env):
    """
    Postprocess all VMs and images according to the instructions in params.

    :param test: An Autotest test object.
    :param params: Dict containing all VM and image parameters.
    :param env: The environment (a dict-like object).
    """
    error.context("postprocessing")
    err = ""

    # Postprocess all VMs and images
    try:
        process(test, params, env, postprocess_image, postprocess_vm,
                vm_first=True)
    except Exception, details:
        err += "\nPostprocess: %s" % str(details).replace('\\n', '\n  ')
        logging.error(details)

    # Terminate the screendump thread
    global _screendump_thread, _screendump_thread_termination_event
    if _screendump_thread is not None:
        _screendump_thread_termination_event.set()
        _screendump_thread.join(10)
        _screendump_thread = None

    # Encode an HTML 5 compatible video from the screenshots produced

    dirs = re.findall("(screendump\S*_[0-9]+)", str(os.listdir(test.debugdir)))
    for dir in dirs:
        screendump_dir = os.path.join(test.debugdir, dir)
        if (params.get("encode_video_files", "yes") == "yes" and
           glob.glob("%s/*" % screendump_dir)):
            try:
                video = video_maker.GstPythonVideoMaker()
                if (video.has_element('vp8enc') and video.has_element('webmmux')):
                    video_file = os.path.join(test.debugdir, "%s-%s.webm" %
                                             (screendump_dir, test.iteration))
                else:
                    video_file = os.path.join(test.debugdir, "%s-%s.ogg" %
                                             (screendump_dir, test.iteration))
                logging.debug("Encoding video file %s", video_file)
                video.start(screendump_dir, video_file)

            except Exception, detail:
                logging.info(
                    "Video creation failed for %s: %s", screendump_dir, detail)

    # Warn about corrupt PPM files
    for f in glob.glob(os.path.join(test.debugdir, "*.ppm")):
        if not ppm_utils.image_verify_ppm_file(f):
            logging.warn("Found corrupt PPM file: %s", f)

    # Should we convert PPM files to PNG format?
    if params.get("convert_ppm_files_to_png", "no") == "yes":
        try:
            for f in glob.glob(os.path.join(test.debugdir, "*.ppm")):
                if ppm_utils.image_verify_ppm_file(f):
                    new_path = f.replace(".ppm", ".png")
                    image = PIL.Image.open(f)
                    image.save(new_path, format='PNG')
        except NameError:
            pass

    # Should we keep the PPM files?
    if params.get("keep_ppm_files", "no") != "yes":
        for f in glob.glob(os.path.join(test.debugdir, '*.ppm')):
            os.unlink(f)

    # Should we keep the screendump dirs?
    if params.get("keep_screendumps", "no") != "yes":
        for d in glob.glob(os.path.join(test.debugdir, "screendumps_*")):
            if os.path.isdir(d) and not os.path.islink(d):
                shutil.rmtree(d, ignore_errors=True)

    # Should we keep the video files?
    if params.get("keep_video_files", "yes") != "yes":
        for f in (glob.glob(os.path.join(test.debugdir, '*.ogg')) +
                  glob.glob(os.path.join(test.debugdir, '*.webm'))):
            os.unlink(f)

    # Kill all unresponsive VMs
    if params.get("kill_unresponsive_vms") == "yes":
        for vm in env.get_all_vms():
            if vm.is_dead() or vm.is_paused():
                continue
            try:
                # Test may be fast, guest could still be booting
                if len(vm.virtnet) > 0:
                    session = vm.wait_for_login(timeout=vm.LOGIN_WAIT_TIMEOUT)
                    session.close()
                else:
                    session = vm.wait_for_serial_login(
                        timeout=vm.LOGIN_WAIT_TIMEOUT)
                    session.close()
            except (remote.LoginError, virt_vm.VMError, IndexError), e:
                logging.warn(e)
                vm.destroy(gracefully=False)

    # Kill VMs with deleted disks
    for vm in env.get_all_vms():
        destroy = False
        vm_params = params.object_params(vm.name)
        for image in vm_params.objects('images'):
            if params.object_params(image).get('remove_image') == 'yes':
                destroy = True
        if destroy and not vm.is_dead():
            logging.debug('Image of VM %s was removed, destroing it.', vm.name)
            vm.destroy()

    # Terminate the tcpdump thread
    env.stop_tcpdump()

    # Kill all aexpect tail threads
    aexpect.kill_tail_threads()

    living_vms = [vm for vm in env.get_all_vms() if vm.is_alive()]
    # Close all monitor socket connections of living vm.
    for vm in living_vms:
        if hasattr(vm, "monitors"):
            for m in vm.monitors:
                try:
                    m.close()
                except Exception:
                    pass

    if params.get("setup_hugepages") == "yes":
        try:
            h = test_setup.HugePageConfig(params)
            h.cleanup()
            if params.get("vm_type") == "libvirt":
                utils_libvirtd.libvirtd_restart()
        except Exception, details:
            err += "\nHP cleanup: %s" % str(details).replace('\\n', '\n  ')
            logging.error(details)

    if params.get("setup_thp") == "yes":
        try:
            thp = test_setup.TransparentHugePageConfig(test, params)
            thp.cleanup()
        except Exception, details:
            err += "\nTHP cleanup: %s" % str(details).replace('\\n', '\n  ')
            logging.error(details)

    if params.get("setup_ksm") == "yes":
        try:
            ksm = test_setup.KSMConfig(params, env)
            ksm.cleanup(env)
        except Exception, details:
            err += "\nKSM cleanup: %s" % str(details).replace('\\n', '\n  ')
            logging.error(details)

    # Execute any post_commands
    if params.get("post_command"):
        try:
            process_command(test, params, env, params.get("post_command"),
                            int(params.get("post_command_timeout", "600")),
                            params.get("post_command_noncritical") == "yes")
        except Exception, details:
            err += "\nPostprocess command: %s" % str(details).replace('\n',
                                                                      '\n  ')
            logging.error(details)

    base_dir = data_dir.get_data_dir()
    if params.get("storage_type") == "iscsi":
        try:
            iscsidev = qemu_storage.Iscsidev(params, base_dir, "iscsi")
            iscsidev.cleanup()
        except Exception, details:
            err += "\niscsi cleanup: %s" % str(details).replace('\\n', '\n  ')
            logging.error(details)

    if params.get("storage_type") == "lvm":
        try:
            lvmdev = env.get_lvmdev("lvm_%s" % params["main_vm"])
            lvmdev.cleanup()
        except Exception, details:
            err += "\nLVM cleanup: %s" % str(details).replace('\\n', '\n  ')
            logging.error(details)
        env.unregister_lvmdev("lvm_%s" % params["main_vm"])

    if params.get("storage_type") == "nfs":
        try:
            image_nfs = nfs.Nfs(params)
            image_nfs.cleanup()
        except Exception, details:
            err += "\nnfs cleanup: %s" % str(details).replace('\\n', '\n  ')

    setup_pb = False
    for nic in params.get('nics', "").split():
        if params.get('netdst_%s' % nic) == 'private':
            setup_pb = True
            break
    else:
        setup_pb = params.get("netdst") == 'private'

    if setup_pb:
        try:
            brcfg = test_setup.PrivateBridgeConfig()
            brcfg.cleanup()
        except Exception, details:
            err += "\nPB cleanup: %s" % str(details).replace('\\n', '\n  ')
            logging.error(details)

    if err:
        raise virt_vm.VMError("Failures occurred while postprocess:%s" % err)


def postprocess_on_error(test, params, env):
    """
    Perform postprocessing operations required only if the test failed.

    :param test: An Autotest test object.
    :param params: A dict containing all VM and image parameters.
    :param env: The environment (a dict-like object).
    """
    params.update(params.object_params("on_error"))


def _take_screendumps(test, params, env):
    global _screendump_thread_termination_event
    temp_dir = test.debugdir
    if params.get("screendump_temp_dir"):
        temp_dir = utils_misc.get_path(test.bindir,
                                       params.get("screendump_temp_dir"))
        try:
            os.makedirs(temp_dir)
        except OSError:
            pass
    temp_filename = os.path.join(temp_dir, "scrdump-%s.ppm" %
                                 utils_misc.generate_random_string(6))
    delay = float(params.get("screendump_delay", 5))
    quality = int(params.get("screendump_quality", 30))
    inactivity_treshold = float(params.get("inactivity_treshold", 1800))
    inactivity_watcher = params.get("inactivity_watcher", "log")

    cache = {}
    counter = {}
    inactivity = {}

    while True:
        for vm in env.get_all_vms():
            if vm.instance not in counter.keys():
                counter[vm.instance] = 0
            if vm.instance not in inactivity.keys():
                inactivity[vm.instance] = time.time()
            if not vm.is_alive():
                continue
            vm_pid = vm.get_pid()
            try:
                vm.screendump(filename=temp_filename, debug=False)
            except qemu_monitor.MonitorError, e:
                logging.warn(e)
                continue
            except AttributeError, e:
                logging.warn(e)
                continue
            if not os.path.exists(temp_filename):
                logging.warn("VM '%s' failed to produce a screendump", vm.name)
                continue
            if not ppm_utils.image_verify_ppm_file(temp_filename):
                logging.warn("VM '%s' produced an invalid screendump", vm.name)
                os.unlink(temp_filename)
                continue
            screendump_dir = os.path.join(test.debugdir,
                                          "screendumps_%s_%s" % (vm.name,
                                                                 vm_pid))
            try:
                os.makedirs(screendump_dir)
            except OSError:
                pass
            counter[vm.instance] += 1
            screendump_filename = os.path.join(screendump_dir, "%04d.jpg" %
                                               counter[vm.instance])
            vm.verify_bsod(screendump_filename)
            image_hash = utils.hash_file(temp_filename)
            if image_hash in cache:
                time_inactive = time.time() - inactivity[vm.instance]
                if time_inactive > inactivity_treshold:
                    msg = (
                        "%s screen is inactive for more than %d s (%d min)" %
                        (vm.name, time_inactive, time_inactive / 60))
                    if inactivity_watcher == "error":
                        try:
                            raise virt_vm.VMScreenInactiveError(vm,
                                                                time_inactive)
                        except virt_vm.VMScreenInactiveError:
                            logging.error(msg)
                            # Let's reset the counter
                            inactivity[vm.instance] = time.time()
                            test.background_errors.put(sys.exc_info())
                    elif inactivity_watcher == 'log':
                        logging.debug(msg)
                try:
                    os.link(cache[image_hash], screendump_filename)
                except OSError:
                    pass
            else:
                inactivity[vm.instance] = time.time()
                try:
                    try:
                        image = PIL.Image.open(temp_filename)
                        image.save(screendump_filename, format="JPEG",
                                   quality=quality)
                        cache[image_hash] = screendump_filename
                    except IOError, error_detail:
                        logging.warning("VM '%s' failed to produce a "
                                        "screendump: %s", vm.name, error_detail)
                        # Decrement the counter as we in fact failed to
                        # produce a converted screendump
                        counter[vm.instance] -= 1
                except NameError:
                    pass
            os.unlink(temp_filename)

        if _screendump_thread_termination_event is not None:
            if _screendump_thread_termination_event.isSet():
                _screendump_thread_termination_event = None
                break
            _screendump_thread_termination_event.wait(delay)
        else:
            # Exit event was deleted, exit this thread
            break
