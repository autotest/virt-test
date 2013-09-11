import re
import logging
import time
from autotest.client.shared import error
from virttest import qemu_io, data_dir
from virttest.qemu_storage import QemuImg
from autotest.client import utils


@error.context_aware
def run_qcow2perf(test, params, env):
    """
    Run qcow2 performance tests:
    1. Create image with given parameters
    2. Write to the image to prepare a certain size image
    3. Do one operations to the image and measure the time
    4. Record the results

    :param test:   QEMU test object
    :param params: Dictionary with the test parameters
    :param env:    Dictionary with test environment.
    """
    image_chain = params.get("image_chain")
    test_image = int(params.get("test_image", "0"))
    interval_size = params.get("interval_szie", "64k")
    write_round = int(params.get("write_round", "16384"))
    op_type = params.get("op_type")
    new_base = params.get("new_base")
    writecmd = params.get("writecmd")
    iocmd = params.get("iocmd")
    opcmd = params.get("opcmd")
    io_options = params.get("io_options", "n")
    cache_mode = params.get("cache_mode")
    image_dir = data_dir.get_data_dir()

    if not re.match("\d+", interval_size[-1]):
        write_unit = interval_size[-1]
        interval_size = int(interval_size[:-1])
    else:
        interval_size = int(interval_size)
        write_unit = ""

    error.context("Init images for testing", logging.info)
    sn_list = []
    for img in re.split("\s+", image_chain.strip()):
        image_params = params.object_params(img)
        sn_tmp = QemuImg(image_params, image_dir, img)
        sn_tmp.create(image_params)
        sn_list.append((sn_tmp, image_params))

    # Write to the test image
    error.context("Prepare the image with write a certain size block",
                  logging.info)
    dropcache = 'echo 3 > /proc/sys/vm/drop_caches && sleep 5'
    snapshot_file = sn_list[test_image][0].image_filename

    if op_type != "writeoffset1":
        offset = 0
        writecmd0 = writecmd % (write_round, offset, interval_size,
                                write_unit, interval_size, write_unit)
        iocmd0 = iocmd % (writecmd0, io_options, snapshot_file)
        logging.info("writecmd-offset-0: %s", writecmd0)
        utils.run(dropcache)
        output = utils.run(iocmd0)
    else:
        offset = 1
        writecmd1 = writecmd % (write_round, offset, interval_size,
                                write_unit, interval_size, write_unit)
        iocmd1 = iocmd % (writecmd1, io_options, snapshot_file)
        logging.info("writecmd-offset-1: %s", writecmd1)
        utils.run(dropcache)
        output = utils.run(iocmd1)

    error.context("Do one operations to the image and measure the time",
                  logging.info)

    if op_type == "read":
        readcmd = opcmd % (io_options, snapshot_file)
        logging.info("read: %s", readcmd)
        utils.run(dropcache)
        output = utils.run(readcmd)
    elif op_type == "commit":
        commitcmd = opcmd % (cache_mode, snapshot_file)
        logging.info("commit: %s", commitcmd)
        utils.run(dropcache)
        output = utils.run(commitcmd)
    elif op_type == "rebase":
        new_base_img = QemuImg(params.object_params(new_base), image_dir,
                               new_base)
        new_base_img.create(params.object_params(new_base))
        rebasecmd = opcmd % (new_base_img.image_filename,
                             cache_mode, snapshot_file)
        logging.info("rebase: %s", rebasecmd)
        utils.run(dropcache)
        output = utils.run(rebasecmd)
    elif op_type == "convert":
        convertname = sn_list[test_image][0].image_filename + "_convert"
        convertcmd = opcmd % (snapshot_file, cache_mode, convertname)
        logging.info("convert: %s", convertcmd)
        utils.run(dropcache)
        output = utils.run(convertcmd)

    error.context("Result recording", logging.info)
    result_file = open("%s/%s_%s_results" %
                       (test.resultsdir, "qcow2perf", op_type), 'w')
    result_file.write("%s:%s\n" % (op_type, output))
    logging.info("%s takes %s" % (op_type, output))
    result_file.close()
