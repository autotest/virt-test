"""
Utilities to perform automatic guest installation using step files.

:copyright: Red Hat 2008-2009
"""

import os
import time
import shutil
import logging
from autotest.client.shared import error
from virttest import utils_misc, ppm_utils, qemu_monitor

try:
    import PIL.Image
except ImportError:
    logging.warning('No python imaging library installed. PPM image '
                    'conversion to JPEG disabled. In order to enable it, '
                    'please install python-imaging or the equivalent for your '
                    'distro.')


def handle_var(vm, params, varname):
    var = params.get(varname)
    if not var:
        return False
    vm.send_string(var)
    return True


def barrier_2(vm, words, params, debug_dir, data_scrdump_filename,
              current_step_num):
    if len(words) < 7:
        logging.error("Bad barrier_2 command line")
        return False

    # Parse barrier command line
    _, dx, dy, x1, y1, md5sum, timeout = words[:7]
    dx, dy, x1, y1, timeout = map(int, [dx, dy, x1, y1, timeout])

    # Define some paths
    scrdump_filename = os.path.join(debug_dir, "scrdump.ppm")
    cropped_scrdump_filename = os.path.join(debug_dir, "cropped_scrdump.ppm")
    expected_scrdump_filename = os.path.join(debug_dir, "scrdump_expected.ppm")
    expected_cropped_scrdump_filename = os.path.join(debug_dir,
                                                     "cropped_scrdump_expected.ppm")
    comparison_filename = os.path.join(debug_dir, "comparison.ppm")
    history_dir = os.path.join(debug_dir, "barrier_history")

    # Collect a few parameters
    timeout_multiplier = float(params.get("timeout_multiplier") or 1)
    fail_if_stuck_for = float(params.get("fail_if_stuck_for") or 1e308)
    stuck_detection_history = int(params.get("stuck_detection_history") or 2)
    keep_screendump_history = params.get("keep_screendump_history") == "yes"
    keep_all_history = params.get("keep_all_history") == "yes"

    # Multiply timeout by the timeout multiplier
    timeout *= timeout_multiplier

    # Timeout/5 is the time it took stepmaker to complete this step.
    # Divide that number by 10 to poll 10 times, just in case
    # current machine is stronger then the "stepmaker machine".
    # Limit to 1 (min) and 10 (max) seconds between polls.
    sleep_duration = float(timeout) / 50.0
    if sleep_duration < 1.0:
        sleep_duration = 1.0
    if sleep_duration > 10.0:
        sleep_duration = 10.0

    end_time = time.time() + timeout
    end_time_stuck = time.time() + fail_if_stuck_for
    start_time = time.time()

    prev_whole_image_md5sums = []

    failure_message = None

    # Main loop
    while True:
        # Check for timeouts
        if time.time() > end_time:
            failure_message = "regular timeout"
            break
        if time.time() > end_time_stuck:
            failure_message = "guest is stuck"
            break

        # Make sure vm is alive
        if not vm.is_alive():
            failure_message = "VM is dead"
            break

        # Request screendump
        try:
            vm.monitor.screendump(scrdump_filename, debug=False)
        except qemu_monitor.MonitorError, e:
            logging.warn(e)
            continue

        # Read image file
        try:
            (w, h, data) = ppm_utils.image_read_from_ppm_file(scrdump_filename)
        except IOError, e:
            logging.warn(e)
            continue

        # Make sure image is valid
        if not ppm_utils.image_verify_ppm_file(scrdump_filename):
            logging.warn("Got invalid screendump: dimensions: %dx%d, "
                         "data size: %d", w, h, len(data))
            continue

        # Compute md5sum of whole image
        whole_image_md5sum = ppm_utils.image_md5sum(w, h, data)

        # Write screendump to history_dir (as JPG) if requested
        # and if the screendump differs from the previous one
        if (keep_screendump_history and
                whole_image_md5sum not in prev_whole_image_md5sums[:1]):
            try:
                os.makedirs(history_dir)
            except Exception:
                pass
            history_scrdump_filename = os.path.join(history_dir,
                                                    "scrdump-step_%s-%s.jpg" % (current_step_num,
                                                                                time.strftime("%Y%m%d-%H%M%S")))
            try:
                image = PIL.Image.open(scrdump_filename)
                image.save(history_scrdump_filename, format='JPEG',
                           quality=30)
            except NameError:
                pass

        # Compare md5sum of barrier region with the expected md5sum
        calced_md5sum = ppm_utils.get_region_md5sum(w, h, data, x1, y1, dx, dy,
                                                    cropped_scrdump_filename)
        if calced_md5sum == md5sum:
            # Success -- remove screendump history unless requested not to
            if keep_screendump_history and not keep_all_history:
                shutil.rmtree(history_dir)
            # Report success
            return True

        # Insert image md5sum into queue of last seen images:
        # If md5sum is already in queue...
        if whole_image_md5sum in prev_whole_image_md5sums:
            # Remove md5sum from queue
            prev_whole_image_md5sums.remove(whole_image_md5sum)
        else:
            # Otherwise extend 'stuck' timeout
            end_time_stuck = time.time() + fail_if_stuck_for
        # Insert md5sum at beginning of queue
        prev_whole_image_md5sums.insert(0, whole_image_md5sum)
        # Limit queue length to stuck_detection_history
        prev_whole_image_md5sums = \
            prev_whole_image_md5sums[:stuck_detection_history]

        # Sleep for a while
        time.sleep(sleep_duration)

    # Failure
    message = ("Barrier failed at step %s after %.2f seconds (%s)" %
               (current_step_num, time.time() - start_time, failure_message))

    # What should we do with this failure?
    if words[-1] == "optional":
        logging.info(message)
        return False
    else:
        # Collect information and put it in debug_dir
        if data_scrdump_filename and os.path.exists(data_scrdump_filename):
            # Read expected screendump image
            (ew, eh, edata) = \
                ppm_utils.image_read_from_ppm_file(data_scrdump_filename)
            # Write it in debug_dir
            ppm_utils.image_write_to_ppm_file(expected_scrdump_filename,
                                              ew, eh, edata)
            # Write the cropped version as well
            ppm_utils.get_region_md5sum(ew, eh, edata, x1, y1, dx, dy,
                                        expected_cropped_scrdump_filename)
            # Perform comparison
            (w, h, data) = ppm_utils.image_read_from_ppm_file(scrdump_filename)
            if w == ew and h == eh:
                (w, h, data) = ppm_utils.image_comparison(w, h, data, edata)
                ppm_utils.image_write_to_ppm_file(comparison_filename, w, h,
                                                  data)
        # Print error messages and fail the test
        long_message = message + "\n(see analysis at %s)" % debug_dir
        logging.error(long_message)
        raise error.TestFail(message)


def run_steps(test, params, env):
    vm = env.get_vm(params.get("vms", "main_vm").split(" ")[0])
    vm.verify_alive()

    steps_filename = params.get("steps")
    if not steps_filename:
        image_name = os.path.basename(params["image_name"])
        steps_filename = 'steps/%s.steps' % image_name

    steps_filename = utils_misc.get_path(test.virtdir, steps_filename)
    if not os.path.exists(steps_filename):
        raise error.TestError("Steps file not found: %s" % steps_filename)

    sf = open(steps_filename, "r")
    lines = sf.readlines()
    sf.close()

    vm.resume()

    current_step_num = 0
    current_screendump = None
    skip_current_step = False

    # Iterate over the lines in the file
    for line in lines:
        line = line.strip()
        if not line:
            continue
        logging.info(line)

        if line.startswith("#"):
            continue

        words = line.split()
        if words[0] == "step":
            current_step_num += 1
            current_screendump = None
            skip_current_step = False
        elif words[0] == "screendump":
            current_screendump = words[1]
        elif skip_current_step:
            continue
        elif words[0] == "sleep":
            timeout_multiplier = float(params.get("timeout_multiplier") or 1)
            time.sleep(float(words[1]) * timeout_multiplier)
        elif words[0] == "key":
            vm.send_key(words[1])
        elif words[0] == "var":
            if not handle_var(vm, params, words[1]):
                logging.error("Variable not defined: %s", words[1])
        elif words[0] == "barrier_2":
            if current_screendump:
                scrdump_filename = os.path.join(
                    ppm_utils.get_data_dir(steps_filename),
                    current_screendump)
            else:
                scrdump_filename = None
            if not barrier_2(vm, words, params, test.debugdir,
                             scrdump_filename, current_step_num):
                skip_current_step = True
        else:
            vm.send_key(words[0])
