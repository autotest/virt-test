import sys
import re
import logging

from autotest_lib.client.common_lib import error
from autotest_lib.client.virt import virt_vm

@error.context_aware
def run_cluster_size_check(test, params, env):
    """
    KVM cluster size check test:
    1) Create image without cluster_size option
    2) Verify if the cluster_size is default value
    3) Create image with cluster_size option
    4) Verify if the cluster_size is the set value

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """

    def memory_size(size):
        try:
            value = int(size)
        except ValueError:
            unit = size[-1] 
            value = int(size[:-1])
            if unit.upper() == "G":
                value = value * 1073741824
            elif unit.upper() == "M":
                value = value * 1048576
            elif unit.upper() == "K":
                value = value * 1024
            elif unit.upper() == "B":
                pass
            else:
                value = -1
 
        return value

    def check_cluster_size(parttern, expect):
        cfail = 0
        image = params.get("images")
        error.context("Create image", logging.info)
        output = virt_vm.create_image(params.object_params(image),
                                      test.bindir,
                                      check_output=True)
        error.context("Check the cluster size from output", logging.info)
        cluster_size = re.findall(parttern, output)
        if cluster_size:
            if cluster_size[0] != expect:
                logging.error("Cluster size mismatch")
                logging.error("Cluster size report by command: %s"
                              % cluster_size)
                logging.error("Cluster size expect: %s" % expect)
                cfail += 1
                fail_log += "Cluster size mismatch when set it to "
                fail_log += "%s.\n" % params["cluster_size"]
        else:
            logging.error("Can not get the cluster size from command: %s"
                           % output)
            cfail += 1
            fail_log += "Can not get the cluster size from command:"
            fail_log += " %s\n" % output
        return cfail

    fail = 0
    fail_log = ""
    csize_parttern = params.get("cluster_size_parttern")
    cluster_size_set = params.get("cluster_size_set")

    for cluster_size in re.split("\s+", cluster_size_set.strip()):
        if cluster_size == "default":
            params["cluster_size"] = ""
            csize_expect = params.get("cluster_size_default", "65536")
        else:
            params["cluster_size"] = cluster_size
            csize_expect = str(memory_size(cluster_size))

        error.context("Check cluster size as cluster size set to %s"
                      % cluster_size)

        fail += check_cluster_size(csize_parttern, csize_expect)

    error.context("Finall result check")
    if fail > 0:
        raise error.TestFail("Cluster size check failed %s times:\n%s"
                             % (fail, fail_log))
