import logging
import os
import glob
import shutil
from autotest.client.shared import logging_manager, error
from autotest.client import utils
import utils_misc
import data_dir
import asset
import cartesian_config

basic_program_requirements = ['7za', 'tcpdump', 'nc', 'ip', 'arping']

recommended_programs = {'qemu': [('qemu-kvm', 'kvm'), ('qemu-img',),
                                 ('qemu-io',)],
                        'libvirt': [('virsh',), ('virt-install',),
                                    ('fakeroot',)],
                        'openvswitch': [],
                        'lvsb': [],
                        'libguestfs': [('perl',)]}

mandatory_programs = {'qemu': basic_program_requirements + ['gcc'],
                      'libvirt': basic_program_requirements,
                      'openvswitch': basic_program_requirements,
                      'lvsb': ['virt-sandbox', 'virt-sandbox-service', 'virsh'],
                      'v2v': basic_program_requirements,
                      'libguestfs': basic_program_requirements}

mandatory_headers = {'qemu': ['Python.h', 'types.h', 'socket.h', 'unistd.h'],
                     'libvirt': [],
                     'openvswitch': [],
                     'v2v': [],
                     'lvsb': [],
                     'libguestfs': []}

first_subtest = {'qemu': ['unattended_install', 'steps'],
                 'libvirt': ['unattended_install'],
                 'openvswitch': ['unattended_install'],
                 'v2v': ['unattended_install'],
                 'libguestfs': ['unattended_install'],
                 'lvsb': []}

last_subtest = {'qemu': ['shutdown'],
                'libvirt': ['shutdown', 'remove_guest'],
                'openvswitch': ['shutdown'],
                'v2v': ['shutdown'],
                'libguestfs': ['shutdown'],
                'lvsb': []}

test_filter = ['__init__', 'cfg']
config_filter = ['__init__', ]


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
    if test_type is not None:
        output_file_object.write("    - @type_specific:\n")
        output_file_object.write("        variants subtest:\n")

    for config_path in config_file_list:
        config_file = open(config_path, 'r')

        write_test_type_line = False

        for line in config_file.readlines():
            # special virt_test_type line output
            if test_type is not None:
                if write_test_type_line:
                    type_line = ("                virt_test_type = %s\n" %
                                                                     test_type)
                    output_file_object.write(type_line)
                    write_test_type_line = False
                elif line.startswith('- '):
                    write_test_type_line = True
                output_file_object.write("            %s" % line)
            else:
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
            number_variants = indent
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
    if t_type == 'lvsb':
        shared_test_list = []
    else:
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

    # lvsb tests can't use VM shared tests
    if t_type == 'lvsb':
        shared_file_list = []
    else:
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
            if line.startswith("type"):
                cartesian_parser = cartesian_config.Parser()
                cartesian_parser.parse_string(line)
                td = cartesian_parser.get_dicts().next()
                values = td['type'].split(" ")
                for value in values:
                    if t_type not in non_dropin_tests:
                        non_dropin_tests.append(value)

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
            if line.startswith("type"):
                cartesian_parser = cartesian_config.Parser()
                cartesian_parser.parse_string(line)
                td = cartesian_parser.get_dicts().next()
                values = td['type'].split(" ")
                for value in values:
                    if value not in non_dropin_tests:
                        non_dropin_tests.append(value)

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
    subtests_file.write(
        "# Do not edit, auto generated file from subtests config\n")
    subtests_file.write("variants subtest:\n")
    write_subtests_files(first_subtest_file, subtests_file)
    write_subtests_files(specific_file_list, subtests_file, t_type)
    write_subtests_files(shared_file_list, subtests_file)
    write_subtests_files(dropin_file_list, subtests_file)
    write_subtests_files(last_subtest_file, subtests_file)

    subtests_file.close()


def create_config_files(test_dir, shared_dir, interactive, step=None,
                        force_update=False):
    def is_file_tracked(fl):
        tracked_result = utils.run("git ls-files %s --error-unmatch" % fl,
                                   ignore_status=True, verbose=False)
        return (tracked_result.exit_status == 0)

    if step is None:
        step = 0
    logging.info("")
    step += 1
    logging.info("%d - Generating config set", step)
    config_file_list = data_dir.SubdirGlobList(os.path.join(test_dir, "cfg"),
                                               "*.cfg",
                                               config_filter)
    config_file_list = [cf for cf in config_file_list if is_file_tracked(cf)]
    config_file_list_shared = glob.glob(os.path.join(shared_dir, "cfg",
                                                     "*.cfg"))

    # Handle overrides of cfg files. Let's say a test provides its own
    # subtest.cfg.sample, this file takes precedence over the shared
    # subtest.cfg.sample. So, yank this file from the cfg file list.

    config_file_list_shared_keep = []
    for cf in config_file_list_shared:
        basename = os.path.basename(cf)
        target = os.path.join(test_dir, "cfg", basename)
        if target not in config_file_list:
            config_file_list_shared_keep.append(cf)

    config_file_list += config_file_list_shared_keep
    for config_file in config_file_list:
        src_file = config_file
        dst_file = os.path.join(test_dir, "cfg", os.path.basename(config_file))
        if not os.path.isfile(dst_file):
            logging.debug("Creating config file %s from sample", dst_file)
            shutil.copyfile(src_file, dst_file)
        else:
            diff_cmd = "diff -Naur %s %s" % (dst_file, src_file)
            diff_result = utils.run(
                diff_cmd, ignore_status=True, verbose=False)
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

    :param test_name: Test name, such as "qemu".
    :param test_dir: Path with the test directory.
    :param base_dir: Base directory used to hold images and isos.
    :param default_userspace_paths: Important programs for a successful test
            execution.
    :param check_modules: Whether we want to verify if a given list of modules
            is loaded in the system.
    :param online_docs_url: URL to an online documentation system, such as a
            wiki page.
    :param restore_image: Whether to restore the image from the pristine.
    :param interactive: Whether to ask for confirmation.

    :raise error.CmdError: If JeOS image failed to uncompress
    :raise ValueError: If 7za was not found
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
    sub_dir_list = ["images", "isos", "steps_data", "gpg"]
    for sub_dir in sub_dir_list:
        sub_dir_path = os.path.join(base_dir, sub_dir)
        if not os.path.isdir(sub_dir_path):
            logging.debug("Creating %s", sub_dir_path)
            os.makedirs(sub_dir_path)
        else:
            logging.debug("Dir %s exists, not creating",
                          sub_dir_path)

    # lvsb test doesn't use any shared configs
    if test_name == 'lvsb':
        create_subtests_cfg(test_name)
    else:
        create_config_files(test_dir, shared_dir, interactive, step)
        create_subtests_cfg(test_name)
        create_guest_os_cfg(test_name)

    if download_image or restore_image:
        logging.info("")
        step += 2
        logging.info("%s - Verifying (and possibly downloading) guest image",
                     step)
        asset.download_asset('jeos-17-64', interactive=interactive,
                             restore_image=restore_image)

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
