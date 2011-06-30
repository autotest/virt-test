import os, time, commands, re, logging, glob, threading, shutil
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
import aexpect, virt_utils, kvm_monitor, ppm_utils, virt_test_setup
import virt_vm, kvm_vm
try:
    import PIL.Image
except ImportError:
    logging.warning('No python imaging library installed. PPM image '
                    'conversion to JPEG disabled. In order to enable it, '
                    'please install python-imaging or the equivalent for your '
                    'distro.')


_screendump_thread = None
_screendump_thread_termination_event = None


def preprocess_image(test, params):
    """
    Preprocess a single QEMU image according to the instructions in params.

    @param test: Autotest test object.
    @param params: A dict containing image preprocessing parameters.
    @note: Currently this function just creates an image if requested.
    """
    image_filename = virt_vm.get_image_filename(params, test.bindir)

    create_image = False

    if params.get("force_create_image") == "yes":
        logging.debug("Param 'force_create_image' specified, creating image")
        create_image = True
    elif (params.get("create_image") == "yes" and not
          os.path.exists(image_filename)):
        create_image = True

    if create_image and not virt_vm.create_image(params, test.bindir):
        raise error.TestError("Could not create image")


def preprocess_vm(test, params, env, name):
    """
    Preprocess a single VM object according to the instructions in params.
    Start the VM if requested and get a screendump.

    @param test: An Autotest test object.
    @param params: A dict containing VM preprocessing parameters.
    @param env: The environment (a dict-like object).
    @param name: The name of the VM object.
    """
    logging.debug("Preprocessing VM '%s'", name)
    vm = env.get_vm(name)
    if not vm:
        logging.debug("VM object for '%s' does not exist, creating it", name)
        vm_type = params.get('vm_type')
        if vm_type == 'kvm':
            vm = kvm_vm.VM(name, params, test.bindir, env.get("address_cache"))
        env.register_vm(name, vm)

    start_vm = False

    if params.get("restart_vm") == "yes":
        logging.debug("Param 'restart_vm' specified, (re)starting VM")
        start_vm = True
    elif params.get("migration_mode"):
        logging.debug("Param 'migration_mode' specified, starting VM in "
                      "incoming migration mode")
        start_vm = True
    elif params.get("start_vm") == "yes":
        if not vm.is_alive():
            logging.debug("VM is not alive, starting it")
            start_vm = True
        if vm.needs_restart(name=name, params=params, basedir=test.bindir):
            logging.debug("Current VM specs differ from requested one; "
                          "restarting it")
            start_vm = True

    if start_vm:
        # Start the VM (or restart it if it's already up)
        vm.create(name, params, test.bindir,
                  migration_mode=params.get("migration_mode"))
    else:
        # Don't start the VM, just update its params
        vm.params = params

    scrdump_filename = os.path.join(test.debugdir, "pre_%s.ppm" % name)
    try:
        if vm.monitor:
            vm.monitor.screendump(scrdump_filename, debug=False)
    except kvm_monitor.MonitorError, e:
        logging.warn(e)


def postprocess_image(test, params):
    """
    Postprocess a single QEMU image according to the instructions in params.

    @param test: An Autotest test object.
    @param params: A dict containing image postprocessing parameters.
    """
    if params.get("check_image") == "yes":
        virt_vm.check_image(params, test.bindir)
    if params.get("remove_image") == "yes":
        virt_vm.remove_image(params, test.bindir)


def postprocess_vm(test, params, env, name):
    """
    Postprocess a single VM object according to the instructions in params.
    Kill the VM if requested and get a screendump.

    @param test: An Autotest test object.
    @param params: A dict containing VM postprocessing parameters.
    @param env: The environment (a dict-like object).
    @param name: The name of the VM object.
    """
    logging.debug("Postprocessing VM '%s'" % name)
    vm = env.get_vm(name)
    if not vm:
        return

    scrdump_filename = os.path.join(test.debugdir, "post_%s.ppm" % name)
    try:
        if vm.monitor:
            vm.monitor.screendump(scrdump_filename, debug=False)
    except kvm_monitor.MonitorError, e:
        logging.warn(e)

    if params.get("kill_vm") == "yes":
        kill_vm_timeout = float(params.get("kill_vm_timeout", 0))
        if kill_vm_timeout:
            logging.debug("Param 'kill_vm' specified, waiting for VM to shut "
                          "down before killing it")
            virt_utils.wait_for(vm.is_dead, kill_vm_timeout, 0, 1)
        else:
            logging.debug("Param 'kill_vm' specified, killing VM")
        vm.destroy(gracefully = params.get("kill_vm_gracefully") == "yes")


def process_command(test, params, env, command, command_timeout,
                    command_noncritical):
    """
    Pre- or post- custom commands to be executed before/after a test is run

    @param test: An Autotest test object.
    @param params: A dict containing all VM and image parameters.
    @param env: The environment (a dict-like object).
    @param command: Command to be run.
    @param command_timeout: Timeout for command execution.
    @param command_noncritical: If True test will not fail if command fails.
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


def process(test, params, env, image_func, vm_func):
    """
    Pre- or post-process VMs and images according to the instructions in params.
    Call image_func for each image listed in params and vm_func for each VM.

    @param test: An Autotest test object.
    @param params: A dict containing all VM and image parameters.
    @param env: The environment (a dict-like object).
    @param image_func: A function to call for each image.
    @param vm_func: A function to call for each VM.
    """
    # Get list of VMs specified for this test
    for vm_name in params.objects("vms"):
        vm_params = params.object_params(vm_name)
        # Get list of images specified for this VM
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)
            # Call image_func for each image
            image_func(test, image_params)
        # Call vm_func for each vm
        vm_func(test, vm_params, env, vm_name)


@error.context_aware
def preprocess(test, params, env):
    """
    Preprocess all VMs and images according to the instructions in params.
    Also, collect some host information, such as the KVM version.

    @param test: An Autotest test object.
    @param params: A dict containing all VM and image parameters.
    @param env: The environment (a dict-like object).
    """
    error.context("preprocessing")

    if params.get("bridge") == "private":
        brcfg = virt_test_setup.PrivateBridgeConfig(params)
        brcfg.setup()

    # Start tcpdump if it isn't already running
    if "address_cache" not in env:
        env["address_cache"] = {}
    if "tcpdump" in env and not env["tcpdump"].is_alive():
        env["tcpdump"].close()
        del env["tcpdump"]
    if "tcpdump" not in env and params.get("run_tcpdump", "yes") == "yes":
        cmd = "%s -npvi any 'dst port 68'" % virt_utils.find_command("tcpdump")
        logging.debug("Starting tcpdump '%s'", cmd)
        env["tcpdump"] = aexpect.Tail(
            command=cmd,
            output_func=_update_address_cache,
            output_params=(env["address_cache"],))
        if virt_utils.wait_for(lambda: not env["tcpdump"].is_alive(),
                              0.1, 0.1, 1.0):
            logging.warn("Could not start tcpdump")
            logging.warn("Status: %s" % env["tcpdump"].get_status())
            logging.warn("Output:" + virt_utils.format_str_for_message(
                env["tcpdump"].get_output()))

    # Destroy and remove VMs that are no longer needed in the environment
    requested_vms = params.objects("vms")
    for key in env.keys():
        vm = env[key]
        if not virt_utils.is_vm(vm):
            continue
        if not vm.name in requested_vms:
            logging.debug("VM '%s' found in environment but not required for "
                          "test, destroying it" % vm.name)
            vm.destroy()
            del env[key]

    # Get the KVM kernel module version and write it as a keyval
    if os.path.exists("/dev/kvm"):
        try:
            kvm_version = open("/sys/module/kvm/version").read().strip()
        except:
            kvm_version = os.uname()[2]
    else:
        kvm_version = "Unknown"
        logging.debug("KVM module not loaded")
    logging.debug("KVM version: %s" % kvm_version)
    test.write_test_keyval({"kvm_version": kvm_version})

    # Get the KVM userspace version and write it as a keyval
    qemu_path = virt_utils.get_path(test.bindir, params.get("qemu_binary",
                                                           "qemu"))
    version_line = commands.getoutput("%s -help | head -n 1" % qemu_path)
    matches = re.findall("[Vv]ersion .*?,", version_line)
    if matches:
        kvm_userspace_version = " ".join(matches[0].split()[1:]).strip(",")
    else:
        kvm_userspace_version = "Unknown"
    logging.debug("KVM userspace version: %s" % kvm_userspace_version)
    test.write_test_keyval({"kvm_userspace_version": kvm_userspace_version})

    if params.get("setup_hugepages") == "yes":
        h = virt_test_setup.HugePageConfig(params)
        h.setup()

    # Execute any pre_commands
    if params.get("pre_command"):
        process_command(test, params, env, params.get("pre_command"),
                        int(params.get("pre_command_timeout", "600")),
                        params.get("pre_command_noncritical") == "yes")

    # Preprocess all VMs and images
    process(test, params, env, preprocess_image, preprocess_vm)

    # Start the screendump thread
    if params.get("take_regular_screendumps") == "yes":
        logging.debug("Starting screendump thread")
        global _screendump_thread, _screendump_thread_termination_event
        _screendump_thread_termination_event = threading.Event()
        _screendump_thread = threading.Thread(target=_take_screendumps,
                                              args=(test, params, env))
        _screendump_thread.start()


@error.context_aware
def postprocess(test, params, env):
    """
    Postprocess all VMs and images according to the instructions in params.

    @param test: An Autotest test object.
    @param params: Dict containing all VM and image parameters.
    @param env: The environment (a dict-like object).
    """
    error.context("postprocessing")

    # Postprocess all VMs and images
    process(test, params, env, postprocess_image, postprocess_vm)

    # Terminate the screendump thread
    global _screendump_thread, _screendump_thread_termination_event
    if _screendump_thread:
        logging.debug("Terminating screendump thread")
        _screendump_thread_termination_event.set()
        _screendump_thread.join(10)
        _screendump_thread = None

    # Warn about corrupt PPM files
    for f in glob.glob(os.path.join(test.debugdir, "*.ppm")):
        if not ppm_utils.image_verify_ppm_file(f):
            logging.warn("Found corrupt PPM file: %s", f)

    # Should we convert PPM files to PNG format?
    if params.get("convert_ppm_files_to_png") == "yes":
        logging.debug("Param 'convert_ppm_files_to_png' specified, converting "
                      "PPM files to PNG format")
        try:
            for f in glob.glob(os.path.join(test.debugdir, "*.ppm")):
                if ppm_utils.image_verify_ppm_file(f):
                    new_path = f.replace(".ppm", ".png")
                    image = PIL.Image.open(f)
                    image.save(new_path, format='PNG')
        except NameError:
            pass

    # Should we keep the PPM files?
    if params.get("keep_ppm_files") != "yes":
        logging.debug("Param 'keep_ppm_files' not specified, removing all PPM "
                      "files from debug dir")
        for f in glob.glob(os.path.join(test.debugdir, '*.ppm')):
            os.unlink(f)

    # Should we keep the screendump dirs?
    if params.get("keep_screendumps") != "yes":
        logging.debug("Param 'keep_screendumps' not specified, removing "
                      "screendump dirs")
        for d in glob.glob(os.path.join(test.debugdir, "screendumps_*")):
            if os.path.isdir(d) and not os.path.islink(d):
                shutil.rmtree(d, ignore_errors=True)

    # Kill all unresponsive VMs
    if params.get("kill_unresponsive_vms") == "yes":
        logging.debug("Param 'kill_unresponsive_vms' specified, killing all "
                      "VMs that fail to respond to a remote login request")
        for vm in env.get_all_vms():
            if vm.is_alive():
                try:
                    session = vm.login()
                    session.close()
                except (virt_utils.LoginError, virt_vm.VMError), e:
                    logging.warn(e)
                    vm.destroy(gracefully=False)

    # Kill all aexpect tail threads
    aexpect.kill_tail_threads()

    # Terminate tcpdump if no VMs are alive
    living_vms = [vm for vm in env.get_all_vms() if vm.is_alive()]
    if not living_vms and "tcpdump" in env:
        env["tcpdump"].close()
        del env["tcpdump"]

    if params.get("setup_hugepages") == "yes":
        h = virt_test_setup.HugePageConfig(params)
        h.cleanup()

    # Execute any post_commands
    if params.get("post_command"):
        process_command(test, params, env, params.get("post_command"),
                        int(params.get("post_command_timeout", "600")),
                        params.get("post_command_noncritical") == "yes")

    if params.get("bridge") == "private":
        brcfg = virt_test_setup.PrivateBridgeConfig()
        brcfg.cleanup()


def postprocess_on_error(test, params, env):
    """
    Perform postprocessing operations required only if the test failed.

    @param test: An Autotest test object.
    @param params: A dict containing all VM and image parameters.
    @param env: The environment (a dict-like object).
    """
    params.update(params.object_params("on_error"))


def _update_address_cache(address_cache, line):
    if re.search("Your.IP", line, re.IGNORECASE):
        matches = re.findall(r"\d*\.\d*\.\d*\.\d*", line)
        if matches:
            address_cache["last_seen"] = matches[0]
    if re.search("Client.Ethernet.Address", line, re.IGNORECASE):
        matches = re.findall(r"\w*:\w*:\w*:\w*:\w*:\w*", line)
        if matches and address_cache.get("last_seen"):
            mac_address = matches[0].lower()
            if time.time() - address_cache.get("time_%s" % mac_address, 0) > 5:
                logging.debug("(address cache) Adding cache entry: %s ---> %s",
                              mac_address, address_cache.get("last_seen"))
            address_cache[mac_address] = address_cache.get("last_seen")
            address_cache["time_%s" % mac_address] = time.time()
            del address_cache["last_seen"]


def _take_screendumps(test, params, env):
    global _screendump_thread_termination_event
    temp_dir = test.debugdir
    if params.get("screendump_temp_dir"):
        temp_dir = virt_utils.get_path(test.bindir,
                                      params.get("screendump_temp_dir"))
        try:
            os.makedirs(temp_dir)
        except OSError:
            pass
    temp_filename = os.path.join(temp_dir, "scrdump-%s.ppm" %
                                 virt_utils.generate_random_string(6))
    delay = float(params.get("screendump_delay", 5))
    quality = int(params.get("screendump_quality", 30))

    cache = {}

    while True:
        for vm in env.get_all_vms():
            if not vm.is_alive():
                continue
            try:
                vm.monitor.screendump(filename=temp_filename, debug=False)
            except kvm_monitor.MonitorError, e:
                logging.warn(e)
                continue
            except AttributeError, e:
                continue
            if not os.path.exists(temp_filename):
                logging.warn("VM '%s' failed to produce a screendump", vm.name)
                continue
            if not ppm_utils.image_verify_ppm_file(temp_filename):
                logging.warn("VM '%s' produced an invalid screendump", vm.name)
                os.unlink(temp_filename)
                continue
            screendump_dir = os.path.join(test.debugdir,
                                          "screendumps_%s" % vm.name)
            try:
                os.makedirs(screendump_dir)
            except OSError:
                pass
            screendump_filename = os.path.join(screendump_dir,
                    "%s_%s.jpg" % (vm.name,
                                   time.strftime("%Y-%m-%d_%H-%M-%S")))
            hash = utils.hash_file(temp_filename)
            if hash in cache:
                try:
                    os.link(cache[hash], screendump_filename)
                except OSError:
                    pass
            else:
                try:
                    image = PIL.Image.open(temp_filename)
                    image.save(screendump_filename, format="JPEG", quality=quality)
                    cache[hash] = screendump_filename
                except NameError:
                    pass
            os.unlink(temp_filename)
        if _screendump_thread_termination_event.isSet():
            _screendump_thread_termination_event = None
            break
        _screendump_thread_termination_event.wait(delay)
