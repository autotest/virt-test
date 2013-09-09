import platform
from virttest import utils_misc

ARCH = platform.machine()

if ARCH == "ppc64":
    # From include/linux/sockios.h
    SIOCSIFHWADDR = 0x8924
    SIOCGIFHWADDR = 0x8927
    SIOCGIFFLAGS = 0x8913
    SIOCSIFFLAGS = 0x8914
    SIOCGIFADDR = 0x8915
    SIOCSIFADDR = 0x8916
    SIOCGIFNETMASK = 0x891B
    SIOCSIFNETMASK = 0x891C
    SIOCGIFINDEX = 0x8933
    SIOCBRADDIF = 0x89a2
    SIOCBRDELIF = 0x89a3
    # From linux/include/linux/if_tun.h
    TUNSETIFF = 0x800454ca
    TUNGETIFF = 0x400454d2
    TUNGETFEATURES = 0x400454cf
    TUNSETQUEUE = 0x800454d9
    IFF_MULTI_QUEUE = 0x0100
    IFF_TAP = 0x2
    IFF_NO_PI = 0x1000
    IFF_VNET_HDR = 0x4000
    # From linux/include/linux/if.h
    IFF_UP = 0x1
else:
    # From include/linux/sockios.h
    SIOCSIFHWADDR = 0x8924
    SIOCGIFHWADDR = 0x8927
    SIOCGIFFLAGS = 0x8913
    SIOCSIFFLAGS = 0x8914
    SIOCGIFADDR = 0x8915
    SIOCSIFADDR = 0x8916
    SIOCGIFNETMASK = 0x891B
    SIOCSIFNETMASK = 0x891C
    SIOCGIFINDEX = 0x8933
    SIOCBRADDIF = 0x89a2
    SIOCBRDELIF = 0x89a3
    # From linux/include/linux/if_tun.h
    TUNSETIFF = 0x400454ca
    TUNGETIFF = 0x800454d2
    TUNGETFEATURES = 0x800454cf
    TUNSETQUEUE = 0x400454d9
    IFF_MULTI_QUEUE = 0x0100
    IFF_TAP = 0x0002
    IFF_NO_PI = 0x1000
    IFF_VNET_HDR = 0x4000
    # From linux/include/linux/if.h
    IFF_UP = 0x1


def get_kvm_module_list():
    if ARCH == 'x86_64':
        return ["kvm", "kvm-%s" % utils_misc.get_cpu_vendor(verbose=False)]
    elif ARCH == 'ppc64':
        return ["kvm"]
