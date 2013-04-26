import re, logging, commands, shelve
from autotest.client.shared import error, utils
from virttest import storage, utils_misc, utils_test
from virttest import env_process, data_dir

def run_qemu_disk_img(test, params, env):
    """
    qemu-img test:

    1). Judge what subcommand is going to be tested
    2). Run subcommand test

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    file_operate = []
    result = shelve.open("check_result")
    cmd = utils_misc.get_path(test.bindir,
                             "qemu/%s" % params.get("qemu_img_binary"))

    def _check_file(img_name, file_check, file_create=None):
        """
        Check file in guest
        1) Login guest
        2) Create big file if needed
        3) Check file with cmd
        4) Save check result in host
        5) Shutdown guest

        @params img_name: image name of guest
        @params file_check: files in guest which need to check
        @params file_create: the file will be created in guest
        """

        # Boot guest
        vm_name = params.get("main_vm")
        params['vms'] = vm_name
        login_timeout = int(params.get("login_timeout", 360))
        dd_timeout = float(params.get("dd_timeout", 900))
        check_timeout = int(params.get("check_timeout", 240))
        file_size = int(params.get("file_size", 100))

        logging.info("Starting %s ..." % img_name)
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.verify_alive()
        session = vm.wait_for_login(timeout=login_timeout)

        # Create big file in guest if needed
        if file_create:
            clean_cmd = params.get("clean_cmd")
            clean_cmd += " %s" % file_create
            logging.info("Remove old file")
            session.cmd(clean_cmd)
            logging.info("Start to create big file in guest ...")
            cmd = params.get("create_file_cmd") % (file_create, file_size)
            s, o = session.get_command_status_output(cmd, timeout=dd_timeout)
            if s != 0:
                raise error.TestFail("Failed to create file in guest %s" % o)
            logging.info("File %s is created in guest" % file_create)

        # Check file
        for i in range(len(file_check)):
            key = "%s.%s" % (img_name, file_check[i])
            cmd = "%s %s" % (params.get("check_file_cmd"), file_check[i])
            status, output = session.get_command_status_output(cmd,
                              timeout=check_timeout)
            if status != 0:
                raise error.TestFail("Failed to get file data %s" % output)

            # Save data result
            result[key] = output.split()[0]
            logging.info("File message %s is saved" % result[key])

        # Shutdown guest
        try:
            session.sendline(params.get("shutdown_command"))
            logging.info("Shutdown command is sent, guest is going down...")

            if not utils_misc.wait_for(vm.is_dead, login_timeout):
                raise error.TestFail("Can not shutdown guest")

            logging.info("Shutdown guest successfully!")
            return result

        finally:
            session.close()

    def _compare_file(files, check_data):
        """
        Compare the md5sum data of files before and after
        operation, such as convert, rebase, commit
        @param files: files are checked
        @param check_data: md5sum data of files before and
                           after operation
        """
        logging.debug("Starting to compare files:\n%s" % check_data.items())

        num = 0
        for i in range(len(files)):
            cmp_result = ""
            for key in check_data:
                if len(re.findall(files[i], key)) > 0:
                    if cmp_result:
                        if cmp(cmp_result, check_data[key]) != 0:
                            num += 1
                    else:
                        cmp_result = check_data[key]

        if num != 0:
            raise error.TestFail("Test failed, file is changed")

    def _get_file_size(file_name):
        """
        Get image file size
        """
        get_size_cmd = params.get("get_size_cmd")
        get_size_cmd += " %s" % file_name

        logging.info("Get image size ... %s" % get_size_cmd)
        s, file_size = commands.getstatusoutput(get_size_cmd)

        if s != 0:
            logging.error("Failed to get image size %s" %s)
            return None

        file_size = float(file_size.split()[0])
        logging.info("Image size: %sM" % file_size)

        return file_size

    def _check_rebase_size(file_before_rebase, file_after_rebase):
        """
        Check snapshot size is enlarged after rebase
        """
        logging.info("Check increased size after rebase...")
        file_create_size = params.get("file_create_size", "1024M")
        file_create_size = float(file_create_size[:-1])

        file_increase = file_after_rebase - file_before_rebase
        if round(file_increase/file_create_size) < 1.0:
            raise error.TestFail("Rebase failed, increased size: %s" \
                                 % file_increase)
        logging.debug("File increased: %s" % file_increase)

    def convert_test():
        """
        Convert guest:
        1) Login guest
        2) Create big file
        3) Check the file and save check result
        4) Shutdown guest
        5) Create snapshot if needed
        6) Create big file in snapshot, and check the file
        7) Save check result and shutdown snapshot
        8) Convert guest(convert base imag in base testing,
           convert snapshot image in
           snapshot testing
        9) Check the file created in base image and snapshot image
        10) Compare the check result before and after convert
        """
        # Boot base image, create big file and check it
        file_base = params.get("file_base")
        file_orig = file_base,
        file_operate.append(file_base)

        img_filename = storage.get_image_filename(params, data_dir.get_data_dir())
        image_format = params.get("image_format")
        _check_file(img_filename, file_orig, file_create=file_base)

        # Create snapshot if needed
        snapshot_name = params.get("name_snapshot")
        snapshot_format = params.get("snapshot_format", "qcow2")
        if snapshot_name:
            params['image_name'] = snapshot_name
            params['image_format'] = snapshot_format

            snapshot_filename = storage.get_image_filename(params, data_dir.get_data_dir())
            utils_test.create_image(cmd, snapshot_filename,
            snapshot_format, base_img=img_filename, base_fmt=image_format)

            # Boot snapshot,create big file and check it.
            file_sn = params.get("file_sn1")
            file_orig = file_sn,
            file_operate.append(file_sn)
            img_filename = snapshot_filename
            _check_file(snapshot_filename, file_orig, file_create=file_sn)

        # Convert image
        image_name = params.get("image_name")
        image_format = params.get("image_format")
        convert_format = params.get("convert_format")
        convert_name = "%s.%s_to_%s" % (image_name, image_format,
                                        convert_format)
        params['image_name'] = convert_name
        params['image_format'] = convert_format
        convert_filename = storage.get_image_filename(params, data_dir.get_data_dir())
        utils_test.convert_image(cmd, img_filename, image_format,
                       convert_filename, convert_format)

        # Boot converted image, check wheather files are changed
        check_result = _check_file(convert_filename, file_operate)

        _compare_file(file_operate, check_result)

    def commit_test():
        """
        Commit image:
        1) Create snapshot
        2) Boot and login snapshot
        3) Create big file
        4) Check the file and save check result
        5) Shutdown snapshot
        6) Commit snapshot to base image
        7) Boot base image
        8) Check the file created in snapshot is in guest
        """
        file_sn = params.get("file_sn1")
        file_orig = file_sn,
        file_operate.append(file_sn)

        base_filename = storage.get_image_filename(params, data_dir.get_data_dir())
        base_name = params.get("image_name")
        base_format = params.get("image_format")
        snapshot_name = params.get("name_snapshot")
        snapshot_format = params.get("snapshot_format", "qcow2")
        params['image_name'] = snapshot_name
        params['image_format'] = snapshot_format

        snapshot_filename = storage.get_image_filename(params, data_dir.get_data_dir())
        utils_test.create_image(cmd, snapshot_filename, snapshot_format,
                                    base_img=base_filename)
        _check_file(snapshot_filename, file_orig, file_create=file_sn)

        # Commit image
        utils_test.commit_image(cmd, snapshot_filename, snapshot_format)

        # Boot backing image
        params['image_name'] = base_name
        params['image_format'] = base_format

        check_result = _check_file(base_filename, file_operate)
        _compare_file(file_operate, check_result)

    def _create_snapshot_image_file(name, file_sn, base_img):
        """
        @param name: image name which will be created
        @param file_sn: file name of snapshot
        @param base_img: base image name when creating snapshot

        @return snapshot image file path
        """
        # Create snapshot
        snapshot_format = params.get("snapshot_format", "qcow2")
        params['image_name'] = name
        params['image_format'] = snapshot_format
        sn_filename = storage.get_image_filename(params, data_dir.get_data_dir())
        utils_test.create_image(cmd, sn_filename, snapshot_format,
                                     base_img=base_img)

        file_operate.append(file_sn)
        _check_file(sn_filename, (file_sn,), file_create=file_sn)
        return sn_filename

    def _do_rebase(from_file, to_file, file_size=None):
        snapshot_format = params.get("snapshot_format", "qcow2")

        if file_size:
            before = file_size
        else:
            # Get snapshot image size before rebase
            before = _get_file_size(from_file)

        # Rebase from_file to to_file
        utils_test.rebase_image(cmd, from_file, to_file,
                       snapshot_format, snapshot_fmt=snapshot_format)
        # Get snapshot image size after rebase
        after = _get_file_size(from_file)
        # Check snapshot image size after rebase
        _check_rebase_size(before, after)

        return after

    def rebase_test():
        """
        Rebase image:
        1) Boot guest
        2) Create big file in guest
        3) Create and boot snapshot
        4) Create big file in snapshot
        5) Rebase snapshot
        6) Boot snapshot to check the created file is in guest.

        Scenerios:
        - New disk:
          1) base -> sn1 -> sn2 -> sn3
          2) rebase sn3 -> new disk
        - Scenerio1:
          1) base -> sn1 -> sn2
          2) rebase sn2 -> base
        - Scenerio2:
          1) base -> sn1 -> sn2 -> sn3 -> sn4
          2) rebase sn4 -> sn2
          3) rebase sn4 -> sn1
          4) rebase sn4 -> base
        - Seenerio3:
          1) base -> sn1 -> sn2 -> sn3
          2) rebase sn3 -> base
        """
        file_base = params.get("file_base")
        file_orig = file_base,
        file_operate.append(file_base)

        image_format = params.get("image_format")
        image_name = params.get("image_name")
        img_filename = storage.get_image_filename(params, data_dir.get_data_dir())
        _check_file(img_filename, file_orig, file_create=file_base)

        snapshot_format = params.get("snapshot_format", "qcow2")

        name_sn1 = params.get("name_snapshot1")
        file_sn1 = params.get("file_sn1")
        name_sn2 = params.get("name_snapshot2")
        file_sn2 = params.get("file_sn2")
        name_sn3 = params.get("name_snapshot3")
        name_sn4 = params.get("name_snapshot4")
        new_disk = params.get("name_disk")

        # Create snapshot1
        sn1_filename = _create_snapshot_image_file(name_sn1, file_sn1,
                                                   img_filename)
        # Create snapshot2
        sn2_filename = _create_snapshot_image_file(name_sn2, file_sn2,
                                                   sn1_filename)
        # snapshot2 test.
        if not name_sn3:
            # Rebase snapshot2 to base image
            _do_rebase(sn2_filename, img_filename)
            # Boot snapshot2 and check files
            check_result = _check_file(name_sn2, file_operate)

        # snapshot3 test.
        sn3_filename = None
        if name_sn3 and (not name_sn4) and (not new_disk):
            file_sn = params.get("file_sn3")
            sn3_filename = _create_snapshot_image_file(name_sn3, file_sn,
                                                       sn2_filename)
            _do_rebase(sn3_filename, img_filename)

            # Boot snapshot3 to check files
            check_result = _check_file(name_sn3, file_operate)


        sn4_filename = None
        if name_sn3 and name_sn4:
            # Create snapshot3 if needed
            if not sn3_filename:
                file_sn = params.get("file_sn3")
                sn3_filename = _create_snapshot_image_file(name_sn3, file_sn,
                                                           sn2_filename)
            file_sn = params.get("file_sn4")
            sn4_filename = _create_snapshot_image_file(name_sn4, file_sn,
                                                       sn3_filename)
            # Rebase snapshot4 to snapshot2
            sn4_size_after_sn2 = _do_rebase(sn4_filename, sn2_filename)
            # Rebase snapshot4 to snapshot1
            sn4_size_after_sn1 = _do_rebase(sn4_filename, sn1_filename,
                                            sn4_size_after_sn2)
            # Rebase snapshot4 to base image
            _do_rebase(sn4_filename, img_filename, sn4_size_after_sn1)
            # Boot snapshot4 to check files
            check_result = _check_file(name_sn4, file_operate)

        new_filename = None
        if name_sn3 and new_disk:
            # Create snapshot3 if needed
            if not sn3_filename:
                file_sn = params.get("file_sn3")
                sn3_filename = _create_snapshot_image_file(name_sn3, file_sn,
                                                           sn2_filename)
            # Create new disk
            params['image_name'] = new_disk
            params['image_format'] = image_format
            image_size = params.get("image_size")
            new_filename = storage.get_image_filename(params, data_dir.get_data_dir())
            utils_test.create_image(cmd, new_filename, image_format,
                                        img_size = image_size)

            # Rebase snapshot3 to new image
            _do_rebase(sn3_filename, new_filename)

            # Boot snapshot3 to check files
            params['image_name'] = name_sn3
            params['image_format'] = snapshot_format
            check_result = _check_file(name_sn3, file_operate)

            # Compare file after rebase snapshot to new disk
            _compare_file(file_operate, check_result)

            # Restore snapshot3 from new disk
            utils_test.rebase_image(cmd, sn3_filename, sn2_filename,
                             snapshot_format, snapshot_fmt=snapshot_format)
            name_sn3 = name_sn3 + "restore"
            check_result = _check_file(name_sn3, file_operate)

        # finally, we should:
        _compare_file(file_operate, check_result)
        # Remove snapshot files.
        utils.run("rm -f %s" % sn1_filename, ignore_status=True)
        utils.run("rm -f %s" % sn2_filename, ignore_status=True)
        if sn3_filename:
            utils.run("rm -f %s" % sn3_filename, ignore_status=True)
        if sn4_filename:
            utils.run("rm -f %s" % sn4_filename, ignore_status=True)
        if new_filename:
            utils.run("rm -f %s" % new_filename, ignore_status=True)
        # restore image_name and image_format paramters.
        params["image_name"] = image_name
        params["image_format"] = image_format

    subcommand = params.get("subcommand")
    eval("%s_test()" % subcommand)
