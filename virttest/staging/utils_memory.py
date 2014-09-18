import re
import glob
import math
import logging
import os
from virttest.libvirt_xml.vm_xml import VMXML
from autotest.client.shared import error


# Returns total memory in kb
def read_from_meminfo(key):
    cmd_result = utils.run('grep %s /proc/meminfo' % key, verbose=False)
    meminfo = cmd_result.stdout
    return int(re.search(r'\d+', meminfo).group(0))


def memtotal():
    return read_from_meminfo('MemTotal')


def freememtotal():
    return read_from_meminfo('MemFree')


def rounded_memtotal():
    # Get total of all physical mem, in kbytes
    usable_kbytes = memtotal()
    # usable_kbytes is system's usable DRAM in kbytes,
    #   as reported by memtotal() from device /proc/meminfo memtotal
    #   after Linux deducts 1.5% to 5.1% for system table overhead
    # Undo the unknown actual deduction by rounding up
    #   to next small multiple of a big power-of-two
    #   eg  12GB - 5.1% gets rounded back up to 12GB
    mindeduct = 0.015  # 1.5 percent
    maxdeduct = 0.055  # 5.5 percent
    # deduction range 1.5% .. 5.5% supports physical mem sizes
    #    6GB .. 12GB in steps of .5GB
    #   12GB .. 24GB in steps of 1 GB
    #   24GB .. 48GB in steps of 2 GB ...
    # Finer granularity in physical mem sizes would require
    #   tighter spread between min and max possible deductions

    # increase mem size by at least min deduction, without rounding
    min_kbytes = int(usable_kbytes / (1.0 - mindeduct))
    # increase mem size further by 2**n rounding, by 0..roundKb or more
    round_kbytes = int(usable_kbytes / (1.0 - maxdeduct)) - min_kbytes
    # find least binary roundup 2**n that covers worst-cast roundKb
    mod2n = 1 << int(math.ceil(math.log(round_kbytes, 2)))
    # have round_kbytes <= mod2n < round_kbytes*2
    # round min_kbytes up to next multiple of mod2n
    phys_kbytes = min_kbytes + mod2n - 1
    phys_kbytes = phys_kbytes - (phys_kbytes % mod2n)  # clear low bits
    return phys_kbytes


def numa_nodes():
    node_paths = glob.glob('/sys/devices/system/node/node*')
    nodes = [int(re.sub(r'.*node(\d+)', r'\1', x)) for x in node_paths]
    return (sorted(nodes))


def node_size():
    nodes = max(len(numa_nodes()), 1)
    return ((memtotal() * 1024) / nodes)


def get_huge_page_size():
    output = utils.system_output('grep Hugepagesize /proc/meminfo')
    return int(output.split()[1])  # Assumes units always in kB. :(


def get_num_huge_pages():
    raw_hugepages = utils.system_output('/sbin/sysctl vm.nr_hugepages')
    return int(raw_hugepages.split()[2])


def get_num_anon_hugepage(pid):
    num_anon = 0
    try:
        try:
            mem_info = open('/proc/%s/smaps' % pid, 'r')
            pattern = re.compile(r'^AnonHugePages*')
            for info in mem_infos:
                if pattern.match(info):
                    num_anon = num_anon + int(info.split()[1])
        except:
            logging.error(
                "There is something wrong while getting anon_hugepage.")
    finally:
        mem_info.close()
        return num_anon


def get_num_huge_pages_free():
    hugepages_free = 0
    try:
        try:
            mem_infos = open('/proc/meminfo', 'r')
            pattern = re.compile(r'^HugePages_Free*')
            for info in mem_infos:
                if pattern.match(info):
                    hugepages_free = int(info.split()[1])
        except:
            logging.error(
                "There is something wrong while getting huge_pages_free.")
    finally:
        mem_infos.close()
        return hugepages_free


def get_num_huge_pages_rsvd():
    hugepages_rsvd = 0
    try:
        try:
            mem_infos = open('/proc/meminfo', 'r')
            pattern = re.compile(r'^HugePages_Rsvd*')
            for info in mem_infos:
                if pattern.match(info):
                    hugepages_rsvd = int(info.split()[1])
        except:
            logging.error(
                "There is something wrong while getting hugepage_rsvd.")
    finally:
        mem_infos.close()
        return hugepages_rsvd


def set_num_huge_pages(num):
    utils.system('/sbin/sysctl vm.nr_hugepages=%d' % num)


def drop_caches():
    """Writes back all dirty pages to disk and clears all the caches."""
    utils.run("sync", verbose=False)
    # We ignore failures here as this will fail on 2.6.11 kernels.
    utils.run("echo 3 > /proc/sys/vm/drop_caches", ignore_status=True,
              verbose=False)


def read_from_vmstat(key):
    """
    Get specific item value from vmstat

    :param key: The item you want to check from vmstat
    :type key: String
    :return: The value of the item
    :rtype: int
    """
    vmstat = open("/proc/vmstat")
    vmstat_info = vmstat.read()
    vmstat.close()
    return int(re.findall("%s\s+(\d+)" % key, vmstat_info)[0])


def read_from_smaps(pid, key):
    """
    Get specific item value from the smaps of a process include all sections.

    :param pid: Process id
    :type pid: String
    :param key: The item you want to check from smaps
    :type key: String
    :return: The value of the item in kb
    :rtype: int
    """
    smaps = open("/proc/%s/smaps" % pid)
    smaps_info = smaps.read()
    smaps.close()

    memory_size = 0
    for each_number in re.findall("%s:\s+(\d+)" % key, smaps_info):
        memory_size += int(each_number)

    return memory_size


def read_from_numa_maps(pid, key):
    """
    Get the process numa related info from numa_maps. This function
    only use to get the numbers like anon=1.

    :param pid: Process id
    :type pid: String
    :param key: The item you want to check from numa_maps
    :type key: String
    :return: A dict using the address as the keys
    :rtype: dict
    """
    numa_maps = open("/proc/%s/numa_maps" % pid)
    numa_map_info = numa_maps.read()
    numa_maps.close()

    numa_maps_dict = {}
    numa_pattern = r"(^[\dabcdfe]+)\s+.*%s[=:](\d+)" % key
    for address, number in re.findall(numa_pattern, numa_map_info, re.M):
        numa_maps_dict[address] = number

    return numa_maps_dict


def get_buddy_info(chunk_sizes, nodes="all", zones="all"):
    """
    Get the fragement status of the host. It use the same method
    to get the page size in buddyinfo.
    2^chunk_size * page_size
    The chunk_sizes can be string make up by all orders that you want to check
    splited with blank or a mathematical expression with '>', '<' or '='.
    For example:
    The input of chunk_size could be: "0 2 4"
    And the return  will be: {'0': 3, '2': 286, '4': 687}
    if you are using expression: ">=9"
    the return will be: {'9': 63, '10': 225}

    :param chunk_size: The order number shows in buddyinfo. This is not
                       the real page size.
    :type chunk_size: string
    :param nodes: The numa node that you want to check. Default value is all
    :type nodes: string
    :param zones: The memory zone that you want to check. Default value is all
    :type zones: string
    :return: A dict using the chunk_size as the keys
    :rtype: dict
    """
    buddy_info = open("/proc/buddyinfo")
    buddy_info_content = buddy_info.read()
    buddy_info.close()

    re_buddyinfo = "Node\s+"
    if nodes == "all":
        re_buddyinfo += "(\d+)"
    else:
        re_buddyinfo += "(%s)" % "|".join(nodes.split())

    if not re.findall(re_buddyinfo, buddy_info_content):
        logging.warn("Can not find Nodes %s" % nodes)
        return None
    re_buddyinfo += ".*?zone\s+"
    if zones == "all":
        re_buddyinfo += "(\w+)"
    else:
        re_buddyinfo += "(%s)" % "|".join(zones.split())
    if not re.findall(re_buddyinfo, buddy_info_content):
        logging.warn("Can not find zones %s" % zones)
        return None
    re_buddyinfo += "\s+([\s\d]+)"

    buddy_list = re.findall(re_buddyinfo, buddy_info_content)

    if re.findall("[<>=]", chunk_sizes) and buddy_list:
        size_list = range(len(buddy_list[-1][-1].strip().split()))
        chunk_sizes = [str(_) for _ in size_list if eval("%s %s" % (_,
                                                                    chunk_sizes))]

        chunk_sizes = ' '.join(chunk_sizes)

    buddyinfo_dict = {}
    for chunk_size in chunk_sizes.split():
        buddyinfo_dict[chunk_size] = 0
        for _, _, chunk_info in buddy_list:
            chunk_info = chunk_info.strip().split()[int(chunk_size)]
            buddyinfo_dict[chunk_size] += int(chunk_info)

    return buddyinfo_dict


def set_transparent_hugepage(setflag=False):
    if setflag == True:
        str_flag = 'always'
    else:
        str_flag = 'never'
    RH_THP_PATH = "/sys/kernel/mm/redhat_transparent_hugepage"
    UPSTREAM_THP_PATH = "/sys/kernel/mm/transparent_hugepage"
    if os.path.isdir(RH_THP_PATH):
        thp_path = RH_THP_PATH
    elif os.path.isdir(UPSTREAM_THP_PATH):
        thp_path = UPSTREAM_THP_PATH
    else:
        raise error.TestFail("System doesn't support transparent "
                             "hugepages")
    re = os.system("echo %s > %s/enabled" % (str_flag, thp_path))
    if re == 0:
        logging.debug("RUNNING: \"echo %s > %s/enabled\"" %
                      (str_flag, thp_path))
        logging.debug("Setting SUCCESS!")
    else:
        raise error.TestFail("setting transparent_hugepage FAIL!")


def get_transparent_hugepage():
    RH_THP_PATH = "/sys/kernel/mm/redhat_transparent_hugepage"
    UPSTREAM_THP_PATH = "/sys/kernel/mm/transparent_hugepage"
    if os.path.isdir(RH_THP_PATH):
        thp_path = RH_THP_PATH
    elif os.path.isdir(UPSTREAM_THP_PATH):
        thp_path = UPSTREAM_THP_PATH
    output = utils.system_output('cat %s/enabled' % thp_path)
    if output[0] == '[always]':
        return True
    else:
        return False
