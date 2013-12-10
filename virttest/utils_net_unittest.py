#!/usr/bin/python

import unittest
import time
import logging
import random
import os
import tempfile
import cPickle

import common
from autotest.client import utils
from autotest.client.shared.test_utils import mock
import utils_net
import utils_misc
import cartesian_config
import utils_params


class FakeVm(object):

    def __init__(self, vm_name, params):
        self.name = vm_name
        self.params = params
        self.instance = (time.strftime("%Y%m%d-%H%M%S-") +
                         utils_misc.generate_random_string(8))

    def get_params(self):
        return self.params

    def is_alive(self):
        logging.info("Fake VM %s (instance %s)", self.name, self.instance)


class TestBridge(unittest.TestCase):

    class FakeCmd(object):
        iter = 0

        def __init__(self, *args, **kargs):
            self.fake_cmds = [
                """bridge name    bridge id        STP enabled    interfaces
virbr0        8000.52540018638c    yes        virbr0-nic
virbr1        8000.525400c0b080    yes        em1
                                              virbr1-nic
""",
                """bridge name    bridge id        STP enabled    interfaces
virbr0        8000.52540018638c    yes
""",
                """bridge name    bridge id        STP enabled    interfaces
""",
                """bridge name    bridge id        STP enabled    interfaces
virbr0        8000.52540018638c    yes        virbr0-nic
                                              virbr2-nic
                                              virbr3-nic
virbr1        8000.525400c0b080    yes        em1
                                              virbr1-nic
                                              virbr4-nic
                                              virbr5-nic
virbr2        8000.525400c0b080    yes        em1
                                              virbr10-nic
                                              virbr40-nic
                                              virbr50-nic
"""]

            self.stdout = self.get_stdout()
            self.__class__.iter += 1

        def get_stdout(self):
            return self.fake_cmds[self.__class__.iter]

    def setUp(self):
        self.god = mock.mock_god(ut=self)

        def utils_run(*args, **kargs):
            return TestBridge.FakeCmd(*args, **kargs)

        self.god.stub_with(utils, 'run', utils_run)

    def test_getstructure(self):

        br = utils_net.Bridge().get_structure()
        self.assertEqual(br, {'virbr1': ['em1', 'virbr1-nic'],
                              'virbr0': ['virbr0-nic']})

        br = utils_net.Bridge().get_structure()
        self.assertEqual(br, {'virbr0': []})

        br = utils_net.Bridge().get_structure()
        self.assertEqual(br, {})

        br = utils_net.Bridge().get_structure()
        self.assertEqual(br, {'virbr2': ['em1', 'virbr10-nic',
                                         'virbr40-nic', 'virbr50-nic'],
                              'virbr1': ['em1', 'virbr1-nic', 'virbr4-nic',
                                         'virbr5-nic'],
                              'virbr0': ['virbr0-nic', 'virbr2-nic',
                                         'virbr3-nic']})


class TestVirtIface(unittest.TestCase):

    test_class = utils_net.VirtIface

    def setUp(self):
        # Do not depend on system-state
        self.test_class.arp_cache_macs = lambda x:[]
        # Use predictable value for mac generation
        self.test_class.LASTBYTE = -1
        self.test_class.MANGLE_PATHS = False
        self.test_class.FORCE_INTS = False


    def loop_equal(self, virtiface, test_keys, what_func):
        for prop in test_keys:
            attr_access_value = getattr(virtiface, prop)
            can_access_value = virtiface[prop]
            get_access_value = virtiface.get(prop, None)
            expected_value = what_func(prop)
            self.assertEqual(attr_access_value, can_access_value)
            self.assertEqual(can_access_value, expected_value)
            self.assertEqual(get_access_value, expected_value)

    def loop_notequal(self, virtiface, test_keys, what_func):
        for prop in test_keys:
            attr_access_value = getattr(virtiface, prop)
            can_access_value = virtiface[prop]
            get_access_value = virtiface.get(prop, None)
            expected_value = what_func(prop)
            self.assertEqual(attr_access_value, can_access_value)
            self.assertTrue(can_access_value != expected_value)
            self.assertTrue(get_access_value != expected_value)

    def test_empty(self):
        virtiface = self.test_class()
        self.assertEqual(len(virtiface.keys()), 0)
        self.assertEqual(len(virtiface.values()), 0)
        for prop in self.test_class.__all_slots__:
            self.assertRaises(KeyError, virtiface.__getitem__, prop)
            self.assertRaises(AttributeError, getattr, virtiface, prop)

    def test_random_get_set(self):
        # Generate random test property values
        testdict = {}
        props = self.test_class.__all_slots__
        for prop in props:
            testdict[prop] = utils_misc.generate_random_string(16)
        virtiface = self.test_class(testdict)
        self.loop_equal(virtiface, props, testdict.__getitem__)
        for prop in props:
            testdict[prop] = utils_misc.generate_random_string(16)
        self.loop_notequal(virtiface, props, testdict.__getitem__)

    def test_apendex_set(self):
        """
        Verify container ignores unknown key names
        """
        # Generate random test property values
        testdict = {}
        appendex = {}
        props = self.test_class.__all_slots__
        for prop in props:
            junk = utils_misc.generate_random_string(16)
            testdict[prop] = junk
            appendex[junk] = utils_misc.generate_random_string(16)
        virtiface = self.test_class(testdict)
        self.loop_equal(virtiface, props, testdict.__getitem__)
        virtiface.update(appendex)
        self.loop_equal(virtiface, props, testdict.__getitem__)
        appendex.update(testdict)
        virtiface = self.test_class(appendex)
        self.loop_equal(virtiface, props, testdict.__getitem__)

    def test_pickle(self):
        import cPickle
        testdict = {}
        props = self.test_class.__all_slots__
        for prop in props:
            testdict[prop] = utils_misc.generate_random_string(16)
        virtiface = self.test_class(testdict)
        picklestr = cPickle.dumps(virtiface, -1)
        del virtiface
        virtiface = cPickle.loads(picklestr)
        del picklestr
        self.loop_equal(virtiface, props, testdict.__getitem__)

    def test_genmac_simple(self):
        virtiface = self.test_class(nic_name='test')
        self.assertTrue(virtiface.needs_mac())
        virtiface.generate_mac_address(attempts=1)
        # Exact string length '12:45:78:01:34:67'
        self.assertEqual(len(virtiface.mac), 17)
        self.assertFalse(virtiface.needs_mac())
        self.assertTrue(bool(virtiface.mac.count(virtiface.MACPREFIX)))
        noprefix = virtiface.mac.replace(virtiface.MACPREFIX, '')
        # verify sequential counting of generate_byte()
        for index, byte in enumerate(virtiface.mac_str_to_int_list(noprefix)):
            self.assertEqual(index, byte)

    def test_genmac_conflict(self):
        existing = []
        # No need to go crazy
        for index in xrange(256):
            virtiface = self.test_class(nic_name='test')
            existing.append(virtiface.generate_mac_address(attempts=1))
        # reset, verify 256th generator attempt fails
        self.test_class.LASTBYTE = -1
        virtiface = self.test_class(nic_name='test')
        self.assertRaises(utils_net.NetError, virtiface.generate_mac_address,
                          existing, 1)

    def test_genmac_invalid(self):
        for prefix in ('fo:ob:ar'):
            virtiface = self.test_class(nic_name='test'+prefix)
            virtiface.mac = prefix
            self.assertRaises(utils_net.NetError, virtiface.generate_mac_address)


class TestLibvirtQemuIface(TestVirtIface):
    test_class = utils_net.LibvirtQemuIface

    def test_prefix(self):
        virtiface = self.test_class()
        self.assertEqual(virtiface.MACPREFIX, '52:54:00')


class TestLibvirtXenIface(TestVirtIface):
    test_class = utils_net.LibvirtXenIface

    def test_prefix(self):
        virtiface = self.test_class()
        self.assertEqual(virtiface.MACPREFIX, "00:16:3e")


class QemuIface(TestVirtIface):
    test_class = utils_net.QemuIface

    def test_prefix(self):
        virtiface = self.test_class()
        self.assertEqual(virtiface.MACPREFIX, '52:54:00')


class TestVirtNetBase(unittest.TestCase):
    """
    ABC Class for subclasses needing to test with mocked arp-cache
    """

    test_class = utils_net.VirtNetBase
    container_classes = (utils_net.VirtIface, utils_net.LibvirtQemuIface,
                         utils_net.LibvirtXenIface, utils_net.QemuIface)
    arp_cache = ['c8:d7:19:13:5d:55', '78:d6:f0:95:8b:fc',
                 '5c:ff:35:22:af:36', '00:24:d7:c5:da:0c',
                 '80:ee:73:63:4a:6d', 'd4:ae:52:c1:0c:ac',
                 '00:1b:21:3b:b7:9a', '00:1b:21:3b:b8:26']

    @classmethod
    def fake_arp_cache_macs(cls):
        for mac in cls.arp_cache:
            yield mac

    def setUp(self):
        # Mock all looking up arp cache and un-randomize mac generation
        for container_class in self.container_classes:
            container_class.arp_cache_macs = self.fake_arp_cache_macs
            container_class.LASTBYTE = -1


class TestVirtNet(TestVirtNetBase):

    def test_init(self):
        for container_class in self.container_classes:
            virtnet = self.test_class(container_class, iterable=None)
            self.assertEqual(len(virtnet), 0)

    def test_pickleable(self):
        for container_class in self.container_classes:
            props = container_class.__all_slots__
            init_list = []
            for index in xrange(0, 255):  #  max Linux nics
                testdict = {}
                junk = utils_misc.generate_random_string(16)
                for prop in props:
                    # generating lots of random stuff is expensive
                    testdict[prop] = "%s_%d_%s_%s" % (container_class.__name__,
                                                      index,
                                                      prop,
                                                      junk)
                init_list.append(testdict)
            # Verify parameter order also
            virtnet = self.test_class(container_class, init_list)
            # File objects are not pickle-able
            virtnet.last_source = tempfile.TemporaryFile()
            picklestr = cPickle.dumps(virtnet, -1)
            del virtnet
            virtnet = cPickle.loads(picklestr)
            del picklestr
            for index, value in enumerate(virtnet):
                testdict = init_list[index]
                for prop in props:
                    self.assertEqual(value[prop], testdict[prop])

    def test_nameindex(self):
        for container_class in self.container_classes:
            props = container_class.__all_slots__
            init_list = []
            name_list = []
            for index in xrange(0, 8):  #  reasonable server-nic count
                testdict = {}
                for prop in props:
                    testdict[prop] = utils_misc.generate_random_string(16)
                init_list.append(testdict)
                name_list.append(testdict['nic_name'])
            virtnet = self.test_class(container_class=container_class,
                                      iterable=init_list)
            for index, value in enumerate(virtnet):
                nic_name = value['nic_name']
                self.assertEqual(name_list[index], nic_name)
                self.assertEqual(virtnet.nic_name_index(nic_name), index)

    def test_generate_macs(self):
        for container_class in self.container_classes:
            # Verify __init__ with only container_class
            virtnet = self.test_class(container_class)
            # Verify using only Base VirtIface slots
            props = utils_net.VirtIface.__all_slots__
            for index in xrange(0, 8):  #  reasonable server-nic count
                testdict = {}
                for prop in props:
                    testdict[prop] = utils_misc.generate_random_string(16)
                # mac address must be special format
                testdict.pop('mac')
                virtnet.append(testdict)
            mac_list = self.arp_cache
            for nic in virtnet:
                nic.generate_mac_address(virtnet.all_macs())
                mac_list.append(nic.mac)
            # Reset to same known namespace search
            container_class.LASTBYTE = -1
            # Verify self check also:
            for nic in virtnet:
                # can't complete already complete mac and compare to self
                del mac_list[mac_list.index(nic.mac)]
                del nic.mac
                nic.generate_mac_address(virtnet.all_macs())
                self.assertTrue(nic.mac not in mac_list)


class TestVirtNetParams(TestVirtNetBase):

    nettests_cartesian = ("""
    nettype = user
    netdst = virbr0
    nic_model = virtio

    variants:
        - onevm:
            vms = vm1
        - twovms:
            vms = vm1 vm2
        - threevms:
            vms = vm1 vm2 vm3

    variants:
        - libvirt:
            vm_type = libvirt
            variants:
                - xen:
                    is_xen = 'yes'
                    nics = nic1
                    cclass = LibvirtXenIface
                - qemu:
                    nics = nic1 nic2
                    cclass = LibvirtQemuIface
        - qemu_kvm:
            vm_type = qemu
            rom_file = something_or_other
            queues = 1
            nics = nic1 nic2 nic3 nic4
            cclass = QemuIface

    variants:
        -propsundefined:
        -defaultprops:
            mac = 9a
            nic_model = virtio
            nettype = bridge
            netdst = virbr0
            vlan = 0
        -mixedpropsone:
            mac_nic1 = 9a:01
            nic_model_nic1 = rtl8139
            nettype_nic1 = bridge
            netdst_nic1 = virbr1
            vlan_nic1 = 1
            ip_nic1 = 192.168.122.101
            netdev_nic1 = foobar
        -mixedpropstwo:
            only twovms
            nics_vm1 = nic1 nic2
            nics_vm2 = nic2 nic3
            mac_nic2 = 9a:02
            nic_model_nic2 = e1000
            nettype_nic3 = network
            netdst_nic1 = eth2
            vlan_nic2 = 2
            ip_nic3 = 192.168.122.102
            netdev_nic1 = barfoo
            mac_nic2 = 9a:02
            nic_model_nic3 = e1000
            nettype_nic1 = network
            netdst_nic2 = eth2
            vlan_nic3 = 3
            ip_nic1 = 192.168.122.102
            netdev_nic2 = foobar
        -mixedpropsthree:
            mac_nic1 = 01:02:03:04:05:06
            mac_nic2 = 07:08:09:0a:0b:0c
            mac_nic4 = 0d:0e:0f:10:11:12
        -mixedpropsfour:
            nettype_nic3 = bridge
            netdst_nic3 = virbr3
            netdev_nic3 = qwerty
    """)

    # cache parsed result for re-use
    _params = None

    # Allow other test classes to share this and save some time/menory
    @classmethod
    def params_generator(cls):
        if cls._params is None:
            parser = cartesian_config.Parser()
            parser.parse_string(cls.nettests_cartesian)
            cls._params = [utils_params.Params(dct)
                           for dct in parser.get_dicts()]
        # return a generator over copies of source dicts
        return (dct.copy() for dct in cls._params)

    def test_params(self):
        param_names1 = [dct['name'] for dct in self.params_generator()]
        param_names2 = [dct['name'] for dct in self.params_generator()]
        self.assertEqual(param_names1, param_names2)

    def test_counting(self):
        for params in self.params_generator():
            for container_class in self.container_classes:
                nics = {}
                vms = {}
                for vm_name in params.objects('vms'):
                    # Need a copy of # nics for comparison
                    vm_params = params.object_params(vm_name)
                    nics[vm_name] = len(vm_params.objects('nics'))
                    # Attach virtnet_params onto fakevm
                    fakevm = FakeVm(vm_name, params)
                    name_is_too_long = utils_net.VirtNetParams(container_class)
                    fakevm.virtnet_params = name_is_too_long
                    self.assertEqual(len(name_is_too_long), 0)
                    vms[vm_name] = fakevm
                for vm_name, fakevm in vms.items():
                    fakevm.virtnet_params.load_from(params, vm_name)
                    vm_nics = len(fakevm.virtnet_params)
                    self.assertEqual(vm_nics, nics[vm_name])

    def test_macgen(self):
        for params in self.params_generator():
            for container_class in self.container_classes:
                vms = {}
                for vm_name in params.objects('vms'):
                    # Need a copy of # nics for comparison
                    vm_params = params.object_params(vm_name)
                    # Attach virtnet_params onto fakevm
                    fakevm = FakeVm(vm_name, params)
                    name_is_too_long = utils_net.VirtNetParams(container_class)
                    name_is_too_long.load_from(params, vm_name)
                    fakevm.virtnet_params = name_is_too_long
                    vms[vm_name] = fakevm
                for vm_name, fakevm in vms.items():
                    existing_macs = fakevm.virtnet_params.all_macs()
                    for mac in self.arp_cache:
                        self.assertTrue(mac in existing_macs)
                    for nic in vms[vm_name].virtnet_params:
                        nic.generate_mac_address(existing_macs)
                biglist = [mac for mac in vms.values()[0].virtnet_params.all_macs()]
                # List will get smaller if dups exist
                biglist.sort()
                nodups = list(set(biglist))
                self.assertEqual(len(nodups), len(biglist))


class TestVirtNetDB(TestVirtNetBase):

    def setUp(self):
        tmpfile = tempfile.NamedTemporaryFile(suffix='db',
                                              prefix='tmp-%s'
                                              % self.id())
        self.dbfilename = tmpfile.name
        # Minor possibility for name-race, since file is deleted.
        tmpfile.close()

    def tearDown(self):
        if os.path.exists(self.dbfilename):
            os.unlink(self.dbfilename)
        if os.path.exists(self.dbfilename + '.lock'):
            os.unlink(self.dbfilename + '.lock')

    def test_multi_class_db(self):
        # Verify multiple container classes can all exist in same db
        for container_class in self.container_classes:
            virtnetdb = utils_net.VirtNetDB(container_class)
            virtnetdb.append({'nic_name':'nic1'})
            virtnetdb.append({'nic_name':'nic2'})
            virtnetdb.append({'nic_name':'nic3'})
            virtnetdb.append({'nic_name':'nic4'})
            vm_name = virtnetdb.container_class.__name__
            virtnetdb.store_to(self.dbfilename, vm_name)
        for container_class in self.container_classes:
            vm_name = container_class.__name__
            # NO container_class, load should convert to VirtIface
            virtnetdb = utils_net.VirtNetDB()
            virtnetdb.load_from(self.dbfilename, vm_name)
            self.assertEqual(len(virtnetdb), 4)
            for nic in virtnetdb:
                self.assertEqual(nic.__class__.__name__, vm_name)

    def test_multi_class_vm(self):
        # Verify multiple container classes can all exist in same db vm entry
        virtnetdb = utils_net.VirtNetDB()
        for container_class in self.container_classes:
            virtnetdb.container_class = container_class
            virtnetdb.append({'nic_name':container_class.__name__})
        virtnetdb.store_to(self.dbfilename, 'foobar')
        del virtnetdb
        virtnetdb = utils_net.VirtNetDB()
        virtnetdb.load_from(self.dbfilename, 'foobar')
        for nic in virtnetdb:
            self.assertEqual(nic.__class__.__name__, nic.nic_name)

    def test_params_to_db(self):
        for params in TestVirtNetParams.params_generator():
            cclass = getattr(utils_net, params['cclass'])
            for vm_name in params.objects('vms'):
                db_key = params['name'] + '_' + vm_name
                virtnetparams = utils_net.VirtNetParams(cclass)
                virtnetparams.load_from(params, vm_name)
                virtnetdb = virtnetparams.convert_to(utils_net.VirtNetDB)
                virtnetdb.store_to(self.dbfilename, db_key)
        for params in TestVirtNetParams.params_generator():
            cclass = getattr(utils_net, params['cclass'])
            for vm_name in params.objects('vms'):
                db_key = params['name'] + '_' + vm_name
                virtnetdb = utils_net.VirtNetDB() #  container_class is loaded
                virtnetdb.load_from(self.dbfilename, db_key)
                virtnetparams = utils_net.VirtNetParams(cclass)
                virtnetparams.load_from(params, vm_name)
                self.assertEqual(virtnetdb, virtnetparams)


class TestVirtNetLibvirt(TestVirtNetBase):

    class DummyVirsh(object):

        VIRSH_EXEC = 'Dummy'

        def __init__(self, params):
            self.params = params

        def domiflist(self, vm_name, *args, **dargs):
            del args
            del dargs
            vm_params = self.params.object_params(vm_name)
            stdout = ("Interface  Type       Source     Model       MAC\n"
                      "---------------------------------------------------"
                      "----\n")
            linefmt = ("vnet%(idx)-6d "
                       "%(nettype)-10.10s "
                       "%(netdst)-10.10s "
                       "%(model)-11.11s "
                       "%(mac)-s\n")
            idx = 0
            for nic_name in vm_params.objects('nics'):
                nic_params = vm_params.object_params(nic_name)
                idx += 1
                data = {'idx':idx,
                        'nettype':nic_params.get('nettype', 'user')}
                if data['nettype'] == 'user':
                    data['netdst'] = '-'
                else:
                    data['netdst'] = nic_params.get('netdst', 'virbr0')
                data['model'] = nic_params.get('nic_model', 'rtl8139')
                if nic_params.get('mac') is not None:
                    data['mac'] = nic_params['mac']
                else:
                    data['mac'] = 'au:to:ge:ne:ra:td'
                stdout += linefmt % data
            return utils.CmdResult('domiflist', stdout, None, 0)

        def dom_list(self, *args, **dargs):
            del args
            del dargs
            stdout = (" Id    Name                           State\n"
                      "----------------------------------------------"
                      "------\n")
            linefmt = (" -     "
                       "%(vm_name)-30.30s "
                       "%(state)-14.14s\n")
            for vm_name in self.params.objects('vms'):
                data = {'vm_name':vm_name}
                data['state'] = random.choice(['shut off', 'running'])
                stdout += linefmt % data
            return utils.CmdResult('list', stdout, None, 0)

    def test_compare_to_params(self):
        for params in TestVirtNetParams.params_generator():
            cclass = getattr(utils_net, params['cclass'])
            virsh = TestVirtNetLibvirt.DummyVirsh(params)
            for vm_name in params.objects('vms'):
                virtnetparams = utils_net.VirtNetParams(cclass)
                virtnetparams.load_from(params, vm_name)
                virtnetlibvirt = utils_net.VirtNetLibvirt(cclass)
                # Required b/c type-checking is done before calling
                virtnetlibvirt._virsh_class = TestVirtNetLibvirt.DummyVirsh
                virtnetlibvirt.load_from(virsh, vm_name)
                # domiflist always autogenerates & sets a mac if one isn't
                # But mac is optional param, so sometimes must ignore it
                for nic in virtnetlibvirt:
                    if nic.get('mac') == 'au:to:ge:ne:ra:td':
                        virtnetlibvirt.do_not_compare.add('mac')
                        break
                self.assertEqual(virtnetlibvirt, virtnetparams)

if __name__ == '__main__':
    unittest.main()
