import logging
from autotest.client.shared import error
from virttest import virsh

UINT32_MAX = (1 << 32) - 1
INT64_MAX = (1 << 63) - 1
UINT64_MAX = (1 << 64) - 1
DEFAULT = INT64_MAX / (1024 * 1024)


def run(test, params, env):
    """
    Test command: virsh migrate-setspeed <domain> <bandwidth>
                  virsh migrate-getspeed <domain>.

    1) Prepare test environment.
    2) Try to set the maximum migration bandwidth (in MiB/s)
       for a domain through valid and invalid command.
    3) Recover test environment.
    4) Check result.
    """

    # MAIN TEST CODE ###
    # Process cartesian parameters
    vm_name = params.get("main_vm")
    bandwidth = params.get("bandwidth", "default")
    options_extra = params.get("options_extra", "")
    status_error = "yes" == params.get("status_error", "yes")
    virsh_dargs = {'debug': True}

    if bandwidth == "zero":
        expected_value = 0
    elif bandwidth == "one":
        expected_value = 1
    elif bandwidth == "default":
        expected_value = DEFAULT
    elif bandwidth == "UINT32_MAX":
        expected_value = UINT32_MAX
    elif bandwidth == "INT64_MAX":
        expected_value = INT64_MAX
    elif bandwidth == "UINT64_MAX":
        expected_value = UINT64_MAX
    elif bandwidth == "INVALID_VALUE":
        expected_value = UINT64_MAX + 1
    else:
        expected_value = bandwidth

    orig_value = virsh.migrate_getspeed(vm_name).stdout.strip()

    # Run test case
    try:
        result = virsh.migrate_setspeed(vm_name, expected_value,
                                        options_extra, **virsh_dargs)
        status = result.exit_status
        err = result.stderr.strip()

        # Check status_error
        if status_error:
            if status == 0 or err == "":
                raise error.TestFail("Expect fail, but run successfully!")

            # no need to perform getspeed if status_error is true
            return
        else:
            if status != 0 or err != "":
                raise error.TestFail("Run failed with right "
                                     "virsh migrate-setspeed command")

        result = virsh.migrate_getspeed(vm_name, **virsh_dargs)
        status = result.exit_status
        actual_value = result.stdout.strip()
        err = result.stderr.strip()

        if status != 0 or err != "":
            raise error.TestFail("Run failed with virsh migrate-getspeed")

        logging.info("The expected bandwidth is %s MiB/s, "
                     "the actual bandwidth is %s MiB/s"
                     % (expected_value, actual_value))

        if int(actual_value) != int(expected_value):
            raise error.TestFail("Bandwidth value from getspeed "
                                 "is different from expected value "
                                 "set by setspeed")
    finally:
        #restore bandwidth to default
        virsh.migrate_setspeed(vm_name, orig_value)
