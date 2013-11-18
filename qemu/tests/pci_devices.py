#!/usr/bin/python
"""
This is a autotest/virt-test test for testing PCI devices in various PCI setups

:author: Lukas Doktor <ldoktor@redhat.com>
:copyright: 2013 Red Hat, Inc.
"""
from autotest.client.shared import error
from virttest import env_process
from virttest import qemu_devices
from virttest import qemu_qtree
import logging
import random


class PCIBusInfo:

    def __init__(self, device):
        self.name = device.aobject
        if device.child_bus:
            bus = device.child_bus[0]
            self.type = bus.type == 'PCI'
            self.first = bus.first_port[0]
            self.last = bus.addr_lengths[0]
        else:
            self.type = True    # PCI
            self.first = 0      # (first usable)
            self.last = 32      # (last + 1)


def verify_qdev_vs_qtree(qdev, qtree):
    qdev_devices = {}
    qdev_devices_noid = []
    for bus in qdev.get_buses({'type': ('PCI', 'PCIE')}):
        for device in bus:
            if isinstance(device, str):
                logging.error("Not a device %s (bus %s)", device, bus)
                continue
            dev_id = device.get_param('id')
            addr = [int(_, 16) for _ in device.get_param('addr').split('.')]
            if len(addr) == 1:
                addr.append(0)
            addr = "%02x.%x" % (addr[0], addr[1])
            dev = {'id': dev_id,
                   'type': device.get_param('driver'),
                   'bus': device.get_param('bus'),
                   'addr': addr
                   }
            if dev_id is None:
                qdev_devices_noid.append(dev)
            else:
                qdev_devices[dev_id] = dev

    qtree_devices = {}
    qtree_devices_noid = []
    for node in qtree.get_nodes():
        if node.parent and node.parent.qtree.get('type') in ('PCI', 'PCIE'):
            dev_id = node.qtree.get('id')
            dev = {'id': dev_id,
                   'type': node.qtree.get('type'),
                   'bus': node.parent.qtree.get('id'),
                   'addr': node.qtree.get('addr')
                   }
            if dev_id is None:
                # HOOK for VGA
                if dev['type'] == 'VGA':
                    dev['type'] = None
                qtree_devices_noid.append(dev)
            else:
                qtree_devices[dev_id] = dev

    errors = ""
    for dev_id, device in qtree_devices.iteritems():
        if dev_id not in qdev_devices:
            errors += "Device %s is in qtree but not in qdev.\n" % dev_id
            continue
        for key, value in device.iteritems():
            err = ""
            if qdev_devices[dev_id][key] != value:
                err += "  %s != %s\n" % (qdev_devices[dev_id][key], value)
            if err:
                errors += ("Device %s properties mismatch:\n%s"
                           % (dev_id, err))

    for dev_id in qdev_devices:
        if dev_id not in qtree_devices:
            errors += "Device %s is in qdev but not in qtree\n" % dev_id

    for device in qtree_devices_noid:
        for qdev_device in qdev_devices_noid:
            if qdev_device == device:
                qdev_devices_noid.remove(device)
                break
        else:
            errors += "No match in qdev for device without id %s\n" % device
    for device in qdev_devices_noid:
        errors += "No match in qtree for device without id %s\n" % device

    return errors


def add_bus(qdev, params, bus_type, name, parent_bus):
    if bus_type == 'bridge':
        if parent_bus.type is True:    # PCI
            bus_type = 'pci-bridge'
        else:   # PCIE
            bus_type = 'i82801b11-bridge'
    elif bus_type == 'switch':
        bus_type = 'x3130'
    elif bus_type == 'root':
        bus_type = 'ioh3420'
    params['pci_controllers'] += " %s" % name
    params['type_%s' % name] = bus_type
    params['pci_bus_%s' % name] = parent_bus.name
    pci_params = params.object_params(name)
    bus = PCIBusInfo(qdev.pcic_by_params(name, pci_params))
    return params, bus


def add_devices_first(params, name_idxs, bus, add_device):
    params, name_idxs = add_device(params, name_idxs, bus.name, bus.first)
    return params, name_idxs


def add_devices_all(params, name_idxs, bus, add_device):
    for addr in xrange(bus.first, bus.last):
        params, name_idxs = add_device(params, name_idxs, bus.name, addr)
    return params, name_idxs


def add_devices_random(params, name_idxs, bus, add_device):
    params, name_idxs = add_device(params, name_idxs, bus.name, bus.first)
    params, name_idxs = add_device(params, name_idxs, bus.name,
                                   random.randrange(bus.first + 1,
                                                    bus.last - 1))
    params, name_idxs = add_device(params, name_idxs, bus.name, bus.last - 1)
    return params, name_idxs


def add_device_usb(params, name_idxs, parent_bus, addr, device):
    idx = name_idxs.get(device[0], 0) + 1
    name_idxs[device[0]] = idx
    name = "test_%s%d" % (device[0], idx)
    params['usbs'] += ' %s' % name
    params['pci_bus_%s' % name] = parent_bus
    params['pci_addr_%s' % name] = addr
    params['usb_type_%s' % name] = device[1]
    if not params.get('reserved_slots_%s' % parent_bus):
        params['reserved_slots_%s' % parent_bus] = ""
    params['reserved_slots_%s' % parent_bus] += " %02x-00" % addr
    logging.debug("Add test device %s %s %s addr:%s", name, device[1],
                  parent_bus, addr)
    return params, name_idxs


def add_device_usb_ehci(params, name_idxs, parent_bus, addr):
    return add_device_usb(params, name_idxs, parent_bus,
                          addr, ('ehci', 'usb-ehci'))


def add_device_usb_xhci(params, name_idxs, parent_bus, addr):
    return add_device_usb(params, name_idxs, parent_bus,
                          addr, ('xhci', 'nec-usb-xhci'))


def add_device_random(params, name_idxs, parent_bus, addr):
    variants = (add_device_usb_ehci, add_device_usb_xhci)
    return random.choice(variants)(params, name_idxs, parent_bus, addr)


@error.context_aware
def run_pci_devices(test, params, env):
    """
    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    error.context("Creating early names representation")
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    qdev = vm.make_create_command()    # parse params into qdev

    error.context("Getting main PCI bus info")

    error.context("Processing test params")
    test_params = params['test_setup']
    test_devices = params['test_devices']
    test_device_type = params['test_device_type']
    if not params.get('pci_controllers'):
        params['pci_controllers'] = ''
    _lasts = [PCIBusInfo(qdev.get_by_properties({'aobject': 'pci.0'})[0])]
    _lasts[0].first = 7     # first 6 slots might be already occupied on pci.0
    _lasts[0].last -= 1     # last port is usually used by the VM
    use_buses = []
    names = {}
    logging.info("Test setup")
    for line in test_params.split('\\n'):
        _idx = 0
        out = ""
        for device in line.split('->'):
            device = device.strip()
            if device:
                if device == 'devices':
                    use_buses.append(_lasts[_idx])
                    out += "->(test_devices)"
                    break
                idx = names.get(device, 0) + 1
                name = "pci_%s%d" % (device, idx)
                names[device] = idx
                params, bus = add_bus(qdev, params, device, name, _lasts[_idx])
                # we inserted a device, increase the upper bus first idx
                _lasts[_idx].first += 1
                out += "->%s" % (name)
                _idx += 1
                if len(_lasts) > _idx:
                    _lasts = _lasts[:_idx]
                _lasts.append(bus)
            else:
                _idx += 1
                out += " " * (len(_lasts[_idx].name) + 2)
        logging.info(out)

    add_devices = {'first': add_devices_first,
                   'all': add_devices_all}.get(test_devices,
                                               add_devices_random)
    add_device = {'xhci': add_device_usb_xhci}.get(test_device_type,
                                                   add_device_random)
    name_idxs = {}
    for bus in use_buses:
        params, name_idxs = add_devices(params, name_idxs, bus, add_device)
    params['start_vm'] = 'yes'
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    qtree = qemu_qtree.QtreeContainer()

    error.context("Verify qtree vs. qemu devices", logging.info)
    info_qtree = vm.monitor.info('qtree', False)
    qtree.parse_info_qtree(info_qtree)
    errors = verify_qdev_vs_qtree(vm.devices, qtree)
    if errors:
        logging.error(info_qtree)
        logging.error(qtree.get_qtree().str_qtree())
        logging.error(errors)
        raise error.TestFail("Errors occurred while comparing info qtree vs. "
                             "the internal representation. Please check the "
                             "log for details.")

    error.context("Verify VM booted properly.", logging.info)
    vm.wait_for_login()
