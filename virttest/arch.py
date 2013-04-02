import platform
from virttest import utils_misc

ARCH = platform.machine()

def get_kvm_module_list():
    if ARCH == 'x86_64':
        return ["kvm", "kvm-%s" % utils_misc.get_cpu_vendor(verbose=False)]
    elif ARCH == 'ppc64':
        return ["kvm"]
