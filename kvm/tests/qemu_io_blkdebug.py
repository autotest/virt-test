import re, logging, ConfigParser
from autotest.client.shared import error
from virttest import qemu_io
from virttest import utils_misc
from virttest.kvm_storage import QemuImg
from autotest.client import utils

@error.context_aware
def run_qemu_io_blkdebug(test, params, env):
    """
    Run qemu-io blkdebug tests:
    1. Create image with given parameters
    2. Write the blkdebug config file
    3. Try to do operate in image with qemu-io and get the error message
    4. Get the error message from perror by error number set in config file
    5. Compare the error message

    @param test:   kvm test object
    @param params: Dictionary with the test parameters
    @param env:    Dictionary with test environment.
    """
    tmp_dir = params.get("tmp_dir", "/tmp")
    blkdebug_cfg = utils_misc.get_path(tmp_dir, params.get("blkdebug_cfg",
                                                            "blkdebug.cfg"))
    err_command = params.get("err_command")
    err_event = params.get("err_event")
    errn_list = re.split("\s+", params.get("errn_list").strip())
    re_std_msg = params.get("re_std_msg")
    test_timeout = int(params.get("test_timeout", "60"))
    pre_err_commands = params.get("pre_err_commands")
    image = params.get("images")
    blkdebug_default = params.get("blkdebug_default")

    error.context("Create image", logging.info)
    image_io = QemuImg(params.object_params(image), test.bindir, image)
    image_name = image_io.create(params.object_params(image))

    template_name =  utils_misc.get_path(test.virtdir, blkdebug_default)
    template = ConfigParser.ConfigParser()
    template.read(template_name)

    for errn in errn_list:
        log_filename = utils_misc.get_path(test.outputdir,
                                           "qemu-io-log-%s" % errn)
        error.context("Write the blkdebug config file", logging.info)
        template.set("inject-error", "event", '"%s"' % err_event)
        template.set("inject-error", "errno", '"%s"' % errn)

        error.context("Write blkdebug config file", logging.info)
        blkdebug = None
        try:
            blkdebug = open(blkdebug_cfg, 'w')
            template.write(blkdebug)
        finally:
            if blkdebug is not None:
                blkdebug.close()

        error.context("Operate in qemu-io to trigger the error", logging.info)
        session = qemu_io.QemuIOShellSession(test, params, image_name,
                                             blkdebug_cfg=blkdebug_cfg,
                                             log_filename=log_filename)
        if pre_err_commands:
            for cmd in re.split(",", pre_err_commands.strip()):
                session.cmd_output(cmd, timeout=test_timeout)

        output = session.cmd_output(err_command, timeout=test_timeout)
        error.context("Get error message from command perror", logging.info)
        perror_cmd = "perror %s" % errn
        std_msg = utils.system_output(perror_cmd)
        std_msg = re.findall(re_std_msg, std_msg)
        if std_msg:
            std_msg = std_msg[0]
        else:
            std_msg = ""
            logging.warning("Can not find error message from perror")

        session.close()
        error.context("Compare the error message", logging.info)
        if std_msg:
            if std_msg in output:
                logging.info("Error message is correct in qemu-io")
            else:
                fail_log = "The error message is mismatch:"
                fail_log += "qemu-io reports: '%s'," % output
                fail_log += "perror reports: '%s'" % std_msg
                raise error.TestFail(fail_log)
        else:
            logging.warning("Can not find error message from perror."
                            " The output from qemu-io is %s" % output)
