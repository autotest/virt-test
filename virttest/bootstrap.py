import urllib2, logging, os, glob, shutil, ConfigParser
from autotest.client.shared import logging_manager
from autotest.client import utils
import utils_misc, data_dir

basic_program_requirements = ['7za', 'tcpdump', 'nc', 'ip', 'arping']

recommended_programs = {'qemu': [('qemu-kvm', 'kvm'), ('qemu-img',), ('qemu-io',)],
                        'libvirt': [('virsh',), ('virt-install',)],
                        'openvswitch': [],
                        'v2v': [],
                        'libguestfs': [('perl',)]}

mandatory_programs = {'qemu': basic_program_requirements + ['gcc'],
                      'libvirt': basic_program_requirements,
                      'openvswitch': basic_program_requirements,
                      'v2v': basic_program_requirements,
                      'libguestfs': basic_program_requirements}

mandatory_headers = {'qemu': ['Python.h', 'types.h', 'socket.h', 'unistd.h'],
                     'libvirt': [],
                     'openvswitch': [],
                     'v2v': [],
                     'libguestfs': []}

first_subtest = {'qemu': ['unattended_install', 'steps'],
                'libvirt': ['unattended_install'],
                'openvswitch': ['unattended_install'],
                'v2v': ['unattended_install'],
                'libguestfs': ['unattended_install']}

last_subtest = {'qemu': ['shutdown'],
                'libvirt': ['shutdown', 'remove_guest'],
                'openvswitch': ['shutdown'],
                'v2v': ['shutdown'],
                'libguestfs': ['shutdown']}

test_filter = ['__init__', 'cfg']
config_filter = ['__init__',]

def get_asset_info(asset):
    asset_path = os.path.join(data_dir.get_download_dir(), '%s.ini' % asset)
    asset_cfg = ConfigParser.ConfigParser()
    asset_cfg.read(asset_path)

    url = asset_cfg.get(asset, 'url')
    try:
        sha1_url = asset_cfg.get(asset, 'sha1_url')
    except ConfigParser.NoOptionError:
        sha1_url = None
    title = asset_cfg.get(asset, 'title')
    destination = asset_cfg.get(asset, 'destination')
    if not os.path.isabs(destination):
        destination = os.path.join(data_dir.get_data_dir(), destination)
    asset_exists = os.path.isfile(destination)

    # Optional fields
    try:
        destination_uncompressed = asset_cfg.get(asset,
                                                 'destination_uncompressed')
        if not os.path.isabs(destination_uncompressed):
            destination_uncompressed = os.path.join(data_dir.get_data_dir(),
                                                    destination)
        uncompress_cmd = asset_cfg.get(asset, 'uncompress_cmd')
    except:
        destination_uncompressed = None
        uncompress_cmd = None


    return {'url': url, 'sha1_url': sha1_url, 'destination': destination,
            'destination_uncompressed': destination_uncompressed,
            'uncompress_cmd': uncompress_cmd, 'shortname': asset,
            'title': title,
            'downloaded': asset_exists}


def download_file(asset, interactive=False):
    """
    Verifies if file that can be find on url is on destination with right hash.

    This function will verify the SHA1 hash of the file. If the file
    appears to be missing or corrupted, let the user know.

    @param asset: String describing an asset file inside the shared/downloads
            directory. This asset file is a .ini file with information about
            download and SHA1SUM url data.

    @return: True, if file had to be downloaded
             False, if file didn't have to be downloaded
    """
    file_ok = False
    problems_ignored = False
    had_to_download = False
    sha1 = None

    asset_info = get_asset_info(asset)

    url = asset_info['url']
    sha1_url = asset_info['sha1_url']
    destination = asset_info['destination']
    title = asset_info['title']

    if sha1_url is not None:
        try:
            logging.info("Verifying expected SHA1 sum from %s", sha1_url)
            sha1_file = urllib2.urlopen(sha1_url)
            sha1_contents = sha1_file.read()
            sha1 = sha1_contents.split(" ")[0]
            logging.info("Expected SHA1 sum: %s", sha1)
        except Exception, e:
            logging.error("Failed to get SHA1 from file: %s", e)
    else:
        sha1 = None

    destination_dir = os.path.dirname(destination)
    if not os.path.isdir(destination_dir):
        os.makedirs(destination_dir)

    if not os.path.isfile(destination):
        logging.warning("File %s not found", destination)
        if interactive:
            answer = utils.ask("Would you like to download it from %s?" % url)
        else:
            answer = 'y'
        if answer == 'y':
            utils.interactive_download(url, destination, "Downloading %s" % title)
            had_to_download = True
        else:
            logging.warning("Missing file %s", destination)
    else:
        logging.info("Found %s", destination)
        if sha1 is None:
            answer = 'n'
        else:
            answer = 'y'

        if answer == 'y':
            actual_sha1 = utils.hash_file(destination, method='sha1')
            if actual_sha1 != sha1:
                logging.info("Actual SHA1 sum: %s", actual_sha1)
                if interactive:
                    answer = utils.ask("The file seems corrupted or outdated. "
                                       "Would you like to download it?")
                else:
                    logging.info("The file seems corrupted or outdated")
                    answer = 'y'
                if answer == 'y':
                    logging.info("Updating image to the latest available...")
                    while not file_ok:
                        utils.interactive_download(url, destination, title)
                        sha1_post_download = utils.hash_file(destination,
                                                             method='sha1')
                        had_to_download = True
                        if sha1_post_download != sha1:
                            logging.error("Actual SHA1 sum: %s", actual_sha1)
                            if interactive:
                                answer = utils.ask("The file downloaded %s is "
                                                   "corrupted. Would you like "
                                                   "to try again?" %
                                                   destination)
                            else:
                                answer = 'n'
                            if answer == 'n':
                                problems_ignored = True
                                logging.error("File %s is corrupted" %
                                              destination)
                                file_ok = True
                            else:
                                file_ok = False
                        else:
                            file_ok = True
            else:
                file_ok = True
                logging.info("SHA1 sum check OK")
        else:
            problems_ignored = True
            logging.info("File %s present, but did not verify integrity",
                         destination)

    if file_ok:
        if not problems_ignored:
            logging.info("%s present, with proper checksum", destination)

    return had_to_download


def download_asset(asset, interactive=True, restore_image=False):
    """
    Download an asset defined on an asset file.

    Asset files are located under /shared/downloads, are .ini files with the
    following keys defined:
        title: Title string to display in the download progress bar.
        url = URL of the resource
        sha1_url = URL with SHA1 information for the resource, in the form
            sha1sum file_basename
        destination = Location of your file relative to the data directory
            (TEST_SUITE_ROOT/shared/data)
        destination = Location of the uncompressed file relative to the data
            directory (TEST_SUITE_ROOT/shared/data)
        uncompress_cmd = Command that needs to be executed with the compressed
            file as a parameter

    @param asset: String describing an asset file.
    @param interactive: Whether to ask the user before downloading the file.
    @param restore_image: If the asset is a compressed image, we can uncompress
                          in order to restore the image.
    """
    asset_info = get_asset_info(asset)
    destination = os.path.join(data_dir.get_data_dir(),
                               asset_info['destination'])

    if (interactive and not os.path.isfile(destination)):
        answer = utils.ask("File %s not present. Do you want to download it?" %
                           asset_info['title'])
    else:
        answer = "y"

    if answer == "y":
        had_to_download = download_file(asset=asset, interactive=interactive)

        requires_uncompress = asset_info['uncompress_cmd'] is not None
        if requires_uncompress:
            destination_uncompressed = asset_info['destination_uncompressed']
            uncompressed_file_exists = os.path.exists(destination_uncompressed)

            restore_image = (restore_image or had_to_download or not
                             uncompressed_file_exists)

            if os.path.isfile(destination) and restore_image:
                os.chdir(os.path.dirname(destination))
                uncompress_cmd = asset_info['uncompress_cmd']
                utils.run("%s %s" % (uncompress_cmd, destination))


def verify_recommended_programs(t_type):
    cmds = recommended_programs[t_type]
    for cmd_aliases in cmds:
        for cmd in cmd_aliases:
            found = None
            try:
                found = utils_misc.find_command(cmd)
                logging.info(found)
                break
            except ValueError:
                pass
        if found is None:
            if len(cmd_aliases) == 1:
                logging.info("Recommended command %s missing. You may "
                             "want to install it if not building from "
                             "source.", cmd_aliases[0])
            else:
                logging.info("Recommended command missing. You may "
                             "want to install it if not building it from "
                             "source. Aliases searched: %s", cmd_aliases)

def verify_mandatory_programs(t_type):
    failed_cmds = []
    cmds = mandatory_programs[t_type]
    for cmd in cmds:
        try:
            logging.info(utils_misc.find_command(cmd))
        except ValueError:
            logging.error("Required command %s is missing. You must "
                          "install it", cmd)
            failed_cmds.append(cmd)

    includes = mandatory_headers[t_type]
    available_includes = glob.glob('/usr/include/*/*')
    for include in available_includes:
        include_basename = os.path.basename(include)
        if include_basename in includes:
            logging.info(include)
            includes.pop(includes.index(include_basename))

    if includes:
        for include in includes:
            logging.error("Required include %s is missing. You may have to "
                          "install it", include)

    failures = failed_cmds + includes

    if failures:
        raise ValueError('Missing (cmds/includes): %s' % " ".join(failures))


def write_subtests_files(config_file_list, output_file_object, test_type=None):
    '''
    Writes a collection of individual subtests config file to one output file

    Optionally, for tests that we know their type, write the 'virt_test_type'
    configuration automatically.
    '''
    for config_path in config_file_list:
        config_file = open(config_path, 'r')

        write_test_type_line = False

        for line in config_file.readlines():
            # special virt_test_type line output
            if test_type is not None:
                if write_test_type_line:
                    type_line = "        virt_test_type = %s\n" % test_type
                    output_file_object.write(type_line)
                    write_test_type_line = False
                elif line.startswith('- '):
                    write_test_type_line = True

            # regular line output
            output_file_object.write("    %s" % line)

        config_file.close()


def get_directory_structure(rootdir, guest_file):
    rootdir = rootdir.rstrip(os.sep)
    start = rootdir.rfind(os.sep) + 1
    previous_indent = 0
    indent = 0
    number_variants = 0
    for path, subdirs, files in os.walk(rootdir):
        folders = path[start:].split(os.sep)
        folders = folders[1:]
        indent = len(folders)
        if indent > previous_indent:
            guest_file.write("%svariants:\n" %
                             (4 * (indent + number_variants - 1) * " "))
            number_variants += 1
        elif indent < previous_indent:
            number_variants -= 1
        indent += number_variants
        try:
            base_folder = folders[-1]
        except IndexError:
            base_folder = []
        base_cfg = "%s.cfg" % base_folder
        base_cfg_path = os.path.join(os.path.dirname(path), base_cfg)
        if os.path.isfile(base_cfg_path):
            base_file = open(base_cfg_path, 'r')
            for line in base_file.readlines():
                guest_file.write("%s%s" % ((4 * (indent - 1) * " "), line))
        else:
            if base_folder:
                guest_file.write("%s- %s:\n" %
                                 ((4 * (indent - 1) * " "), base_folder))
        variant_printed = False
        if files:
            files.sort()
            for f in files:
                if f.endswith(".cfg"):
                    bf = f[:len(f) - 4]
                    if bf not in subdirs:
                        if not variant_printed:
                            guest_file.write("%svariants:\n" %
                                             ((4 * (indent) * " ")))
                            variant_printed = True
                        base_file = open(os.path.join(path, f), 'r')
                        for line in base_file.readlines():
                            guest_file.write("%s%s" %
                                             ((4 * (indent + 1) * " "), line))
        indent -= number_variants
        previous_indent = indent


def create_guest_os_cfg(t_type):
    root_dir = data_dir.get_root_dir()
    guest_os_cfg_dir = os.path.join(root_dir, 'shared', 'cfg', 'guest-os')
    guest_os_cfg_path = os.path.join(root_dir, t_type, 'cfg', 'guest-os.cfg')
    guest_os_cfg_file = open(guest_os_cfg_path, 'w')
    get_directory_structure(guest_os_cfg_dir, guest_os_cfg_file)


def create_subtests_cfg(t_type):
    root_dir = data_dir.get_root_dir()

    specific_test = os.path.join(root_dir, t_type, 'tests')
    specific_test_list = data_dir.SubdirGlobList(specific_test,
                                                 '*.py',
                                                 test_filter)
    shared_test = os.path.join(root_dir, 'tests')
    shared_test_list = data_dir.SubdirGlobList(shared_test,
                                               '*.py',
                                               test_filter)
    all_specific_test_list = []
    for test in specific_test_list:
        basename = os.path.basename(test)
        if basename != "__init__.py":
            all_specific_test_list.append(basename.split(".")[0])
    all_shared_test_list = []
    for test in shared_test_list:
        basename = os.path.basename(test)
        if basename != "__init__.py":
            all_shared_test_list.append(basename.split(".")[0])

    all_specific_test_list.sort()
    all_shared_test_list.sort()
    all_test_list = set(all_specific_test_list + all_shared_test_list)

    specific_test_cfg = os.path.join(root_dir, t_type,
                                   'tests', 'cfg')
    shared_test_cfg = os.path.join(root_dir, 'tests', 'cfg')

    shared_file_list = data_dir.SubdirGlobList(shared_test_cfg,
                                               "*.cfg",
                                               config_filter)
    first_subtest_file = []
    last_subtest_file = []
    non_dropin_tests = []
    tmp = []
    for shared_file in shared_file_list:
        shared_file_obj = open(shared_file, 'r')
        for line in shared_file_obj.readlines():
            line = line.strip()
            if not line.startswith("#"):
                try:
                    (key, value) = line.split("=")
                    if key.strip() == 'type':
                        value = value.strip()
                        value = value.split(" ")
                        for v in value:
                            if v not in non_dropin_tests:
                                non_dropin_tests.append(v)
                except:
                    pass
        shared_file_name = os.path.basename(shared_file)
        shared_file_name = shared_file_name.split(".")[0]
        if shared_file_name in first_subtest[t_type]:
            if shared_file_name not in first_subtest_file:
                first_subtest_file.append(shared_file)
        elif shared_file_name in last_subtest[t_type]:
            if shared_file_name not in last_subtest_file:
                last_subtest_file.append(shared_file)
        else:
            if shared_file_name not in tmp:
                tmp.append(shared_file)
    shared_file_list = tmp
    shared_file_list.sort()

    specific_file_list = data_dir.SubdirGlobList(specific_test_cfg,
                                                 "*.cfg",
                                                 config_filter)
    tmp = []
    for shared_file in specific_file_list:
        shared_file_obj = open(shared_file, 'r')
        for line in shared_file_obj.readlines():
            line = line.strip()
            if not line.startswith("#"):
                try:
                    (key, value) = line.split("=")
                    if key.strip() == 'type':
                        value = value.strip()
                        value = value.split(" ")
                        for v in value:
                            if v not in non_dropin_tests:
                                non_dropin_tests.append(v)
                except:
                    pass
        shared_file_name = os.path.basename(shared_file)
        shared_file_name = shared_file_name.split(".")[0]
        if shared_file_name in first_subtest[t_type]:
            if shared_file_name not in first_subtest_file:
                first_subtest_file.append(shared_file)
        elif shared_file_name in last_subtest[t_type]:
            if shared_file_name not in last_subtest_file:
                last_subtest_file.append(shared_file)
        else:
            if shared_file_name not in tmp:
                tmp.append(shared_file)
    specific_file_list = tmp
    specific_file_list.sort()

    non_dropin_tests.sort()
    non_dropin_tests = set(non_dropin_tests)
    dropin_tests = all_test_list - non_dropin_tests
    dropin_file_list = []
    tmp_dir = data_dir.get_tmp_dir()
    if not os.path.isdir(tmp_dir):
        os.makedirs(tmp_dir)
    for dropin_test in dropin_tests:
        autogen_cfg_path = os.path.join(tmp_dir,
                                        '%s.cfg' % dropin_test)
        autogen_cfg_file = open(autogen_cfg_path, 'w')
        autogen_cfg_file.write("# Drop-in test - auto generated snippet\n")
        autogen_cfg_file.write("- %s:\n" % dropin_test)
        autogen_cfg_file.write("    virt_test_type = %s\n" % t_type)
        autogen_cfg_file.write("    type = %s\n" % dropin_test)
        autogen_cfg_file.close()
        dropin_file_list.append(autogen_cfg_path)

    subtests_cfg = os.path.join(root_dir, t_type, 'cfg', 'subtests.cfg')
    subtests_file = open(subtests_cfg, 'w')
    subtests_file.write("# Do not edit, auto generated file from subtests config\n")
    subtests_file.write("variants:\n")
    write_subtests_files(first_subtest_file, subtests_file)
    write_subtests_files(specific_file_list, subtests_file, t_type)
    write_subtests_files(shared_file_list, subtests_file)
    write_subtests_files(dropin_file_list, subtests_file)
    write_subtests_files(last_subtest_file, subtests_file)

    subtests_file.close()


def create_config_files(test_dir, shared_dir, interactive, step=None,
                        force_update=False):
    if step is None:
        step = 0
    logging.info("")
    step += 1
    logging.info("%d - Generating config set", step)
    config_file_list = data_dir.SubdirGlobList(os.path.join(test_dir, "cfg"),
                                               "*.cfg",
                                               config_filter)
    config_file_list_shared = glob.glob(os.path.join(shared_dir, "cfg",
                                                     "*.cfg"))

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
        if not os.path.isfile(dst_file):
            logging.debug("Creating config file %s from sample", dst_file)
            shutil.copyfile(src_file, dst_file)
        else:
            diff_result = utils.run("diff -Naur %s %s" % (dst_file, src_file),
                                    ignore_status=True, verbose=False)
            if diff_result.exit_status != 0:
                logging.info("%s result:\n %s",
                              diff_result.command, diff_result.stdout)
                if interactive:
                    answer = utils.ask("Config file  %s differs from %s."
                                       "Overwrite?" % (dst_file, src_file))
                elif force_update:
                    answer = "y"
                else:
                    answer = "n"

                if answer == "y":
                    logging.debug("Restoring config file %s from sample",
                                  dst_file)
                    shutil.copyfile(src_file, dst_file)
                else:
                    logging.debug("Preserving existing %s file", dst_file)
            else:
                logging.debug("Config file %s exists, not touching", dst_file)


def bootstrap(test_name, test_dir, base_dir, default_userspace_paths,
              check_modules, online_docs_url, restore_image=False,
              download_image=True, interactive=True, verbose=False):
    """
    Common virt test assistant module.

    @param test_name: Test name, such as "qemu".
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

    logging.info("")
    step += 1
    logging.info("%d - Checking the mandatory programs and headers", step)
    verify_mandatory_programs(test_name)

    logging.info("")
    step += 1
    logging.info("%d - Checking the recommended programs", step)
    verify_recommended_programs(test_name)

    logging.info("")
    step += 1
    logging.info("%d - Verifying directories", step)
    shared_dir = os.path.dirname(data_dir.get_data_dir())
    sub_dir_list = ["images", "isos", "steps_data"]
    for sub_dir in sub_dir_list:
        sub_dir_path = os.path.join(base_dir, sub_dir)
        if not os.path.isdir(sub_dir_path):
            logging.debug("Creating %s", sub_dir_path)
            os.makedirs(sub_dir_path)
        else:
            logging.debug("Dir %s exists, not creating",
                          sub_dir_path)

    create_config_files(test_dir, shared_dir, interactive, step)
    create_subtests_cfg(test_name)
    create_guest_os_cfg(test_name)

    if download_image or restore_image:
        logging.info("")
        step += 2
        logging.info("%s - Verifying (and possibly downloading) guest image", step)
        download_asset('jeos', interactive=interactive, restore_image=restore_image)

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
        logging.info("%d - If you wish, take a look at the online docs for "
                     "more info", step)
        logging.info("")
        logging.info(online_docs_url)
