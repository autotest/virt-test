import logging, os, re
from autotest.client import utils
from autotest.client.shared import error
from virttest import postprocess_iozone


def run_iozone_windows(test, params, env):
    """
    Run IOzone for windows on a windows guest:
    1) Log into a guest
    2) Execute the IOzone test contained in the winutils.iso
    3) Get results
    4) Postprocess it with the IOzone postprocessing module

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    def get_drive(session):
        """
        return WIN_UTILS drive letter;
        """
        cmd = "wmic datafile where \"FileName='software_install_64' and "
        cmd += "extension='bat'\" get drive"
        info = session.cmd(cmd, timeout=600)
        device = re.search(r'(\w):', info, re.M)
        if not device:
                raise error.TestError("WIN_UTILS drive not found...")
        device = device.group(1)
        return device.upper()


    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    results_path = os.path.join(test.resultsdir,
                                'raw_output_%s' % test.iteration)
    analysisdir = os.path.join(test.resultsdir, 'analysis_%s' % test.iteration)

    # Run IOzone and record its results
    drive_letter = get_drive(session)
    c = params.get("iozone_cmd") % drive_letter
    t = int(params.get("iozone_timeout"))
    logging.info("Running IOzone command on guest, timeout %ss", t)
    results = session.cmd_output(cmd=c, timeout=t)
    utils.open_write_close(results_path, results)

    # Postprocess the results using the IOzone postprocessing module
    logging.info("Iteration succeed, postprocessing")
    a = postprocess_iozone.IOzoneAnalyzer(list_files=[results_path],
                                          output_dir=analysisdir)
    a.analyze()
    p = postprocess_iozone.IOzonePlotter(results_file=results_path,
                                         output_dir=analysisdir)
    p.plot_all()
