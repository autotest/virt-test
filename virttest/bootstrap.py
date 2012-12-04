import urllib2, logging, os, glob, shutil
from autotest.client.shared import logging_manager
from autotest.client import utils, os_dep
import utils_misc, data_dir


def download_file(url, destination, sha1_url, interactive=False):
    """
    Verifies if file that can be find on url is on destination with right hash.

    This function will verify the SHA1 hash of the file. If the file
    appears to be missing or corrupted, let the user know.

    @param url: URL where the file can be found.
    @param destination: Directory in local disk where we'd like the file to be.
    @param sha1_url: URL with a file containing the sha1sum of the file in the
            form: sha1sum  filename
    @return: True, if file had to be downloaded
             False, if file didn't have to be downloaded
    """
    file_ok = False
    had_to_download = False
    sha1 = None

    try:
        logging.info("Verifying expected SHA1 sum from %s", sha1_url)
        sha1_file = urllib2.urlopen(sha1_url)
        sha1_contents = sha1_file.read()
        sha1 = sha1_contents.split(" ")[0]
        logging.info("Expected SHA1 sum: %s", sha1)
    except Exception, e:
        logging.error("Failed to get SHA1 from file: %s", e)

    if not os.path.isdir(destination):
        os.makedirs(destination)

    path = os.path.join(destination, os.path.basename(url))
    if not os.path.isfile(path):
        logging.warning("File %s not found", path)
        if interactive:
            answer = utils.ask("Would you like to download it from %s?" % url)
        else:
            answer = 'y'
        if answer == 'y':
            utils.interactive_download(url, path, "JeOS x86_64 image")
            had_to_download = True
        else:
            logging.warning("Missing file %s", path)
    else:
        logging.info("Found %s", path)
        if sha1 is None:
            answer = 'n'
        else:
            answer = 'y'

        if answer == 'y':
            actual_sha1 = utils.hash_file(path, method='sha1')
            if actual_sha1 != sha1:
                logging.error("Actual SHA1 sum: %s", actual_sha1)
                if interactive:
                    answer = utils.ask("The file seems corrupted or outdated. "
                                       "Would you like to download it?")
                else:
                    answer = 'y'
                if answer == 'y':
                    logging.info("Updating image to the latest available...")
                    utils.interactive_download(url, path, "JeOS x86_64 image")
                    had_to_download = True
                    file_ok = True
            else:
                file_ok = True
                logging.info("SHA1 sum check OK")
        else:
            logging.info("File %s present, but did not verify integrity",
                         path)

    if file_ok:
        logging.info("%s present, with proper checksum", path)
    return had_to_download


def create_config_files(test_dir, shared_dir, interactive, step=None):
    if step is None:
        step = 0
    logging.info("")
    step += 1
    logging.info("%d - Creating config files from samples", step)
    config_file_list = glob.glob(os.path.join(test_dir, "cfg", "*.cfg.sample"))
    config_file_list_shared = glob.glob(os.path.join(shared_dir,
                                                     "*.cfg.sample"))

    # Handle overrides of cfg files. Let's say a test provides its own
    # subtest.cfg.sample, this file takes precedence over the shared
    # subtest.cfg.sample. So, yank this file from the cfg file list.

    idx = 0
    for cf in config_file_list_shared:
        basename = os.path.basename(cf)
        target = os.path.join(test_dir, "cfg", basename)
        if target in config_file_list:
            config_file_list_shared.pop(idx)
        idx += 1

    config_file_list += config_file_list_shared

    for config_file in config_file_list:
        src_file = config_file
        dst_file = os.path.join(test_dir, "cfg", os.path.basename(config_file))
        dst_file = dst_file.rstrip(".sample")
        if not os.path.isfile(dst_file):
            logging.debug("Creating config file %s from sample", dst_file)
            shutil.copyfile(src_file, dst_file)
        else:
            diff_result = utils.run("diff -Naur %s %s" % (dst_file, src_file),
                                    ignore_status=True, verbose=False)
            if diff_result.exit_status != 0:
                logging.info("%s result:\n %s" %
                              (diff_result.command, diff_result.stdout))
                if interactive:
                    answer = utils.ask("Config file  %s differs from %s."
                                       "Overwrite?" % (dst_file,src_file))
                else:
                    answer = "n"

                if answer == "y":
                    logging.debug("Restoring config file %s from sample" %
                                  dst_file)
                    shutil.copyfile(src_file, dst_file)
                else:
                    logging.debug("Preserving existing %s file" % dst_file)
            else:
                logging.debug("Config file %s exists, not touching" % dst_file)


def bootstrap(test_name, test_dir, base_dir, default_userspace_paths,
                        check_modules, online_docs_url, restore_image=False,
                        interactive=True, verbose=False):
    """
    Common virt test assistant module.

    @param test_name: Test name, such as "kvm".
    @param test_dir: Path with the test directory.
    @param base_dir: Base directory used to hold images and isos.
    @param default_userspace_paths: Important programs for a successful test
            execution.
    @param check_modules: Whether we want to verify if a given list of modules
            is loaded in the system.
    @param online_docs_url: URL to an online documentation system, such as a
            wiki page.
    @param restore_image: Whether to restore the image from the pristine.
    @param interactive: Whether to ask for confirmation.

    @raise error.CmdError: If JeOS image failed to uncompress
    @raise ValueError: If 7za was not found
    """
    if interactive:
        logging_manager.configure_logging(utils_misc.VirtLoggingConfig(),
                                          verbose=verbose)
    logging.info("%s test config helper", test_name)
    step = 0
    shared_dir = os.path.dirname(data_dir.get_data_dir())
    shared_dir = os.path.join(shared_dir, "cfg")
    logging.info("")
    step += 1
    logging.info("%d - Verifying directories", step)
    sub_dir_list = ["images", "isos", "steps_data"]
    for sub_dir in sub_dir_list:
        sub_dir_path = os.path.join(base_dir, sub_dir)
        if not os.path.isdir(sub_dir_path):
            logging.debug("Creating %s", sub_dir_path)
            os.makedirs(sub_dir_path)
        else:
            logging.debug("Dir %s exists, not creating" %
                          sub_dir_path)

    create_config_files(test_dir, shared_dir, interactive, step)

    logging.info("")
    step += 2
    logging.info("%s - Verifying (and possibly downloading) guest image", step)

    # If this is not present, we better tell the user straight away
    try:
        os_dep.command("7za")
    except ValueError:
        raise ValueError("Command 7za not installed. Please install p7zip "
                         "(Red Hat based) or the equivalent for your host")

    sha1_file = "SHA1SUM"
    guest_tarball = "jeos-17-64.qcow2.7z"
    base_location = "http://lmr.fedorapeople.org/jeos/"
    url = os.path.join(base_location, guest_tarball)
    tarball_sha1_url = os.path.join(base_location, sha1_file)
    destination = os.path.join(base_dir, 'images')
    uncompressed_file_path = os.path.join(base_dir, 'images',
                                          'jeos-17-64.qcow2')
    uncompressed_file_exists = os.path.isfile(uncompressed_file_path)

    if (interactive and not
        os.path.isfile(os.path.join(destination, guest_tarball))):
        answer = utils.ask("Minimal basic guest image (JeOS) not present. "
                           "Do you want to download it (~ 120MB)?")
    else:
        answer = "y"

    if answer == "y":
        had_to_download = download_file(url, destination, tarball_sha1_url,
                                        interactive=interactive)
        restore_image = (restore_image or had_to_download or not
                         uncompressed_file_exists)
        tarball_path = os.path.join(destination, guest_tarball)
        if os.path.isfile(tarball_path) and restore_image:
            os.chdir(destination)
            utils.run("7za -y e %s" % tarball_path)

    if default_userspace_paths:
        logging.info("")
        step += 1
        logging.info("%d - Checking if the appropriate userspace programs are "
                     "installed", step)
        for path in default_userspace_paths:
            logging.info(path)
            if not os.path.isfile(path):
                logging.warning("No %s found. You might need to install %s.",
                                path, os.path.basename(path))
            else:
                logging.debug("%s present", path)

    if check_modules:
        logging.info("")
        step += 1
        logging.info("%d - Checking for modules %s", step,
                     ", ".join(check_modules))
        for module in check_modules:
            if not utils.module_is_loaded(module):
                logging.warning("Module %s is not loaded. You might want to "
                                "load it", module)
            else:
                logging.debug("Module %s loaded", module)

    if online_docs_url:
        logging.info("")
        step += 1
        logging.info("%d - Please verify needed packages to get started", step)
        logging.info("")
        logging.info("Take a look at the online documentation: %s",
                     online_docs_url)
