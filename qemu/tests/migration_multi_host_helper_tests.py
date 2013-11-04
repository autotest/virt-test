import re
import time
from autotest.client.shared import error
from virttest import utils_test
from virttest import remote
from virttest import virt_vm
from virttest import utils_misc


class MiniSubtest(object):
    def __new__(cls, *args, **kargs):
        self = super(MiniSubtest, cls).__new__(cls)
        ret = None
        if args is None:
            args = []
        try:
            ret = self.test(*args, **kargs)
        finally:
            if hasattr(self, "clean"):
                self.clean()
        return ret


@error.context_aware
def run_migration_multi_host_helper_tests(test, params, env):
    """
    KVM multi-host migration test:

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    class hot_unplug_block_dev(MiniSubtest):
        def test(self):
            attempts = int(params.get("attempts", "100"))
            attempt_timeout = int(params.get("attempt_timeout", "1"))

            vms = params.get("vms").split(" ")
            vm = env.get_vm(vms[0])

            for block in params.objects("unplug_block"):
                for _ in range(attempts):
                    if vm.devices.simple_unplug(vm.devices["drive_%s" % block],
                                                vm.monitor)[1] is True:
                        break
                    else:
                        time.sleep(attempt_timeout)
                for _ in range(attempts):
                    if vm.devices.simple_unplug(vm.devices[block],
                                                vm.monitor)[1] is True:
                        break
                    else:
                        time.sleep(attempt_timeout)

    class hot_plug_block_dev(MiniSubtest):
        def test(self):
            def get_index(vm, index):
                while vm.index_in_use.get(str(index)):
                    index += 1
                return index

            attempts = int(params.get("attempts", "1"))
            attempt_timeout = int(params.get("attempt_timeout", "1"))

            vms = params.get("vms").split(" ")
            vm = env.get_vm(vms[0])

            devices = vm.devices

            for image_name in params.objects("plug_block"):
                # FIXME: Use qemu_devices for handling indexes
                image_params = params.object_params(image_name)
                if image_params.get("boot_drive") == "no":
                    continue
                if params.get("index_enable") == "yes":
                    drive_index = image_params.get("drive_index")
                    if drive_index:
                        index = drive_index
                    else:
                        vm.last_driver_index = get_index(vm,
                                                         vm.last_driver_index)
                        index = str(vm.last_driver_index)
                        vm.last_driver_index += 1
                else:
                    index = None
                image_bootindex = None
                image_boot = image_params.get("image_boot")
                if not re.search("boot=on\|off", devices.get_help_text(),
                                 re.MULTILINE):
                    if image_boot in ['yes', 'on', True]:
                        image_bootindex = str(vm.last_boot_index)
                        vm.last_boot_index += 1
                    image_boot = "unused"
                    image_bootindex = image_params.get('bootindex',
                                                       image_bootindex)
                else:
                    if image_boot in ['yes', 'on', True]:
                        if vm.last_boot_index > 0:
                            image_boot = False
                        vm.last_boot_index += 1
                image_params = params.object_params(image_name)
                if image_params.get("boot_drive") == "no":
                    continue
                devs = vm.devices.images_define_by_params(image_name,
                                                          image_params,
                                                          'disk',
                                                          index,
                                                          image_boot,
                                                          image_bootindex)
                for dev in devs:
                    for _ in range(attempts):
                        if (vm.devices.simple_hotplug(dev,
                                                      vm.monitor)[1] is True):
                            return
                        time.sleep(attempt_timeout)

    test_type = params.get("helper_test")
    if (test_type in locals()):
        tests_group = locals()[test_type]
        tests_group()
    else:
        raise error.TestFail("Test group '%s' is not defined in"
                             " cpuflags test" % test_type)
