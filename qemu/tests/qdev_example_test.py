from autotest.client.shared import error
import logging


@error.context_aware
def run_qdev_example_test(test, params, env):   # pylint: disable=W0613
    vm = env.get_vm(params["main_vm"])
    pre = vm.devices.str_short()
    if params.get('hotplug'):
        vm.monitor.info("pci")
        for name in params.get('hotplug').split():
            devs = vm.devices.images_define_by_params(name,
                                                params.object_params(name),
                                                'disk')
            for dev in devs:
                ret = vm.devices.hotplug(dev, vm.monitor)
                if ret is True:
                    logging.warn('%s added and verified automatically', dev)
                elif ret is False:
                    logging.warn('%s verification failed, dev is not added', dev)
                else:
                    logging.warn('%s added now I should verify the state', dev)
                    # I should verify the results here...
                    vm.devices.hotplug_verified()
        vm.monitor.info("pci")
    logging.warn(pre)
    logging.warn(vm.devices.str_short())
