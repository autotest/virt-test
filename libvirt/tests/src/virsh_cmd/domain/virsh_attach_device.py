"""
Module to exercize virsh attach-device command with various devices/options
"""

import os
import os.path
import logging
from string import ascii_lowercase
from autotest.client.shared import error
from virttest import virt_vm, virsh, remote, aexpect, utils_misc
from virttest.libvirt_xml.vm_xml import VMXML
# The backports module will take care of using the builtins if available
from virttest.staging.backports import itertools

# TODO: Move all these helper classes someplace else
class TestParams(object):

    """
    Organize test parameters and decouple from params names
    """

    def __init__(self, params, env, test, test_prefix='vadu_dev_obj_'):
        self.test_prefix = test_prefix
        self.test = test
        self.vmxml = None  # Can't be known yet
        self.virsh = None  # Can't be known yet
        self._e = env
        self._p = params

    @property
    def start_vm(self):
        # Required parameter
        return bool('yes' == self._p['start_vm'])

    @property
    def main_vm(self):
        # Required parameter
        return self._e.get_vm(self._p["main_vm"])

    @property
    def file_ref(self):
        default = "normal"
        return self._p.get('vadu_file_ref', default)

    @property
    def dom_ref(self):
        default = "name"
        return self._p.get('vadu_dom_ref', default)

    @property
    def dom_value(self):
        default = None
        return self._p.get('vadu_dom_value', default)

    @property
    def extra(self):
        default = None
        return self._p.get('vadu_extra', default)

    @property
    def status_error(self):
        default = 'no'
        return bool('yes' == self._p.get('status_error', default))

    @property
    def mmconfig(self):
        default = 'no'
        return bool('yes' == self._p.get('vadu_config_option', default))

    @property
    def preboot_function_error(self):
        return bool("yes" == self._p['vadu_preboot_function_error'])

    @property
    def pstboot_function_error(self):
        return bool("yes" == self._p['vadu_pstboot_function_error'])

    @property
    def domain_positional(self):
        default = 'no'
        return bool('yes' == self._p.get('vadu_domain_positional', default))

    @property
    def file_positional(self):
        default = 'no'
        return bool('yes' == self._p.get('vadu_file_positional', default))

    @property
    def devs(self):
        return self._p.objects('vadu_dev_objs')  # mandatory parameter

    def dev_params(self, class_name):
        """
        Return Dictionary after parsing out prefix + class name postfix

        e.g. vadu_dev_obj_meg_VirtIODisk = 100
             ^^^^^^^^^^^^^ ^  ^^^^^^^^^^    ^
        strip   prefix     |  classname     |
                           |                |
                           |                |
        Return        key--+         value--+
        """

        # Roll up all keys with '_class_name' into top-level
        # keys with same name and no '_class_name' postfix.
        #       See Params.object_params() docstring
        object_params = self._p.object_params(class_name)
        # Return variable to hold modified key names
        device_params = {}
        for prefixed_key, original_value in object_params.items():
            # They get unrolled, but originals always left behind, skip them
            if prefixed_key.count(class_name):
                continue
            if prefixed_key.startswith(self.test_prefix):
                stripped_key = prefixed_key[len(self.test_prefix):]
                device_params[stripped_key] = original_value
        # The 'count' key required by all VADU AttachDeviceBase subclasses
        if 'count' not in device_params.keys():
            # stick prefix back on so error message has meaning
            raise error.TestError('%scount is a required parameter'
                                  % (self.test_prefix))
        return device_params

    @staticmethod
    def cleanup(test_dev_list):
        xcpt_list = []
        for device in test_dev_list:
            try:
                device.cleanup()
                # Attempt to finish entire list before raising
                # any exceptions that occurred
            # ignore pylint W0703 - exception acumulated and raised below
            except Exception, xcept_obj:
                xcpt_list.append(xcept_obj)
        if xcpt_list:
            raise RuntimeError("One or more exceptions occurred during "
                               "cleanup: %s" % str(xcpt_list))


class TestDeviceBase(object):

    """
    Base class for test devices creator and verification subclasses
    """

    # Class-specific unique string
    identifier = None
    # Parameters that come in from Cartesian:
    count = 0  # number of devices to make/test
    # flag for use in test and by operate() & function() methods
    booted = False

    def __init__(self, test_params):
        """
        Setup one or more device xml for a device based on TestParams instance
        """
        if self.__class__.identifier is None:
            identifier = utils_misc.generate_random_string(4)
            self.__class__.identifier = identifier
        # how many of this type of device to make
        self.test_params = test_params
        # Copy params for this class into attributes
        cls_name = self.__class__.__name__
        # Already have test-prefix stripped off
        for key, value in self.test_params.dev_params(cls_name).items():
            # Any keys with _anything are not used by this class
            if key.count('_') > 0:
                logging.debug("Removing key: %s from params for class %s",
                              test_params.test_prefix + key, cls_name)
                continue
            # Attempt to convert numbers
            try:
                setattr(self, key, int(value))
            except ValueError:
                setattr(self, key, value)
        if self.count < 1:
            raise error.TestError("Configuration for class %s count must "
                                  "be specified and greater than zero")
        logging.info("Setting up %d %s device(s)", self.count, cls_name)
        # Setup each device_xml instance
        self._device_xml_list = [self.init_device(index)
                                 # test_params.dev_params() enforces count
                                 for index in xrange(0, self.count)]

    def cleanup(self):
        """
        Remove any temporary files or processes created for testing
        """
        pass

    @property
    def device_xmls(self):
        """
        Return list of device_xml instances
        """
        return self._device_xml_list

    @property
    def operation_results(self):
        """
        Return a list of True/False lists for operation state per device
        """
        return [self.operate(index) for index in xrange(self.count)]

    @property
    def function_results(self):
        """
        Return a list of True/False lists for functional state per device
        """
        return [self.function(index) for index in xrange(self.count)]

    @staticmethod
    def good_results(results_list):
        """
        Return True if all member lists contain only True values
        """
        for outer in results_list:
            for inner in outer:
                if inner is False:
                    return False
        return True

    @staticmethod
    def bad_results(results_list):
        """
        Return True if all member lists contain only False values
        """
        for outer in results_list:
            for inner in outer:
                if inner is True:
                    return False
        return True

    # These should be overridden in subclasses
    def init_device(self, index):
        """
        Initialize and return instance of device xml for index
        """
        raise NotImplementedError

    def operate(self, index):
        """
        Return True/False (good/bad) result of operating on a device
        """
        # N/B: Take care of self.started
        raise NotImplementedError

    def function(self, index):
        """
        Return True/False device functioning
        """
        # N/B: Take care of self.test_params.start_vm
        raise NotImplementedError


def make_vadu_dargs(test_params, xml_filepath):
    """
    Return keyword argument dict for virsh attach, detach, update functions

    @param: test_params: a TestParams object
    @param: xml_filepath: Full path to device XML file (may not exist)
    """
    dargs = {}
    # Params value for domain reference (i.e. specific name, number, etc).
    if test_params.dom_value is None:  # No specific value set
        if test_params.dom_ref == "name":  # reference by runtime name
            domain = test_params.main_vm.name
        elif test_params.dom_ref == "id":
            domain = test_params.main_vm.get_id()
        elif test_params.dom_ref == "uuid":
            domain = test_params.main_vm.get_uuid()
        elif test_params.dom_ref == "bad_domain_hex":
            domain = "0x%x" % int(test_params.main_vm.get_id())
        elif test_params.dom_ref == "none":
            domain = None
        else:
            raise error.TestError("Parameter vadu_dom_ref or "
                                  "vadu_dom_value are required")
    else:  # Config. specified a vadu_dom_value
        domain = test_params.dom_value

    if test_params.file_ref == "normal":  # The default
        file_value = xml_filepath  # Use un-altered path
    elif test_params.file_ref == "empty":  # empty string
        file_value = ""  # Empty string argument will be passed!
    elif test_params.file_ref == "missing":
        file_value = os.path.join("path", "does", "not", "exist")
    elif test_params.file_ref == "none":
        file_value = None  # No file specified
    else:
        raise error.TestError("Parameter vadu_file_ref is reuqired")

    if test_params.domain_positional:  # boolean
        dargs['domainarg'] = domain
    else:
        dargs['domain_opt'] = domain

    if test_params.file_positional:
        dargs['filearg'] = file_value
    else:
        dargs['file_opt'] = file_value

    if test_params.mmconfig:
        dargs['flagstr'] = "--config"
    else:
        dargs['flagstr'] = ""

    if test_params.extra is not None:
        dargs['flagstr'] += " %s" % test_params.extra
    return dargs


class AttachDeviceBase(TestDeviceBase):

    """
    All operation behavior is same  all device types in this module
    """

    def operate(self, index):
        """
        Return True/False (good/bad) result of operating on a device
        """
        vadu_dargs = make_vadu_dargs(self.test_params,
                                     self.device_xmls[index].xml)
        # Acts as a dict for it's own API params
        self.test_params.virsh['debug'] = True
        vadu_dargs.update(self.test_params.virsh)
        cmdresult = self.test_params.virsh.attach_device(**vadu_dargs)
        self.test_params.virsh['debug'] = False
        # Command success is not enough, must also confirm activity worked
        if (cmdresult.exit_status == 0):
            if (cmdresult.stdout.count('attached successfully') or
                    cmdresult.stderr.count('attached successfully')):
                return True
        else:
            if (cmdresult.stderr.count("doesn't support option") or
                    cmdresult.stdout.count("doesn't support option")):
                # Just skip this test
                raise error.TestNAError
            if (cmdresult.stderr.count("XML error") or
                    cmdresult.stdout.count("XML error")):
                logging.error("Errant XML:")
                xmldevice = self.device_xmls[index]
                # All LibvirtXMLBase subclasses string-convert into raw XML
                for line in str(xmldevice).splitlines():
                    logging.error("     %s", line)
            return False

    # Overridden in classes below
    def init_device(self, index):
        raise NotImplementedError

    def function(self, index):
        raise NotImplementedError


class SerialFile(AttachDeviceBase):

    """
    Simplistic File-backed isa-serial device test helper

    Consumes Cartesian object parameters:
        count - number of devices to make
    """

    identifier = None
    type_name = "file"

    def make_filepath(self, index):
        """Return full path to unique filename per device index"""
        # auto-cleaned at end of test
        return os.path.join(self.test_params.test.tmpdir, 'serial_%s_%s-%d.log'
                            % (self.type_name, self.identifier, index))

    @staticmethod
    def make_source(filepath):
        """Create filepath on disk"""
        open(filepath, "wb")

    def init_device(self, index):
        filepath = self.make_filepath(index)
        self.make_source(filepath)
        serialclass = self.test_params.vmxml.get_device_class('serial')
        serial_device = serialclass(type_name=self.type_name,
                                    virsh_instance=self.test_params.virsh)
        serial_device.add_source(path=filepath)
        # Assume default domain serial device on port 0 and index starts at 0
        serial_device.add_target(port=str(index + 1))
        return serial_device

    def cleanup(self):
        for index in xrange(0, self.count):
            try:
                os.unlink(self.make_filepath(index))
            except OSError:
                pass  # Don't care if not there

    def function(self, index):
        # TODO: Try to read/write some serial data
        # Just a stub for now
        logging.info("STUB: Serial device functional test passed: %s",
                     str(not self.test_params.status_error))
        # Return an error if an error is expected
        return not self.test_params.status_error


class SerialPipe(SerialFile):

    """
    Simplistic pipe-backed isa-serial device
    """

    identifier = None
    type_name = "pipe"

    @staticmethod
    def make_source(filepath):
        try:
            os.unlink(filepath)
        except OSError:
            pass
        os.mkfifo(filepath)

    def init_device(self, index):
        return super(SerialPipe, self).init_device(index)  # stub for now


class VirtIODiskBasic(AttachDeviceBase):

    """
    Simple File-backed virtio raw disk device
    """

    identifier = None
    count = 0  # number of devices to make
    meg = 0  # size of device in megabytes (1024**2)
    devidx = 1  # devnode name index to start at (0 == vda, 1 == vdb, etc)

    @staticmethod
    def devname_suffix(index):
        """
        Return letter code for index position, a, b, c...aa, ab, ac...
        """
        # http://stackoverflow.com/questions/14381940/
        # python-pair-alphabets-after-loop-is-completed/14382997#14382997
        def multiletters():
            """Generator of count-by-letter strings"""
            for num in itertools.count(1):
                for prod in itertools.product(ascii_lowercase, repeat=num):
                    yield ''.join(prod)
        return itertools.islice(multiletters(), index, index + 1).next()

    def make_image_file_path(self, index):
        """Create backing file for test disk device"""
        return os.path.join(self.test_params.test.tmpdir,
                            'disk_%s_%s_%d.raw'
                            % (self.__class__.__name__,
                               self.identifier,
                               index))

    def make_image_file(self, index):
        """Create sparse backing file by writing it's full path at it's end"""
        # Truncate file
        image_file_path = self.make_image_file_path(index)
        image_file = open(image_file_path, 'wb')
        byte_size = self.meg * 1024 * 1024
        # Make sparse file byte_size long (starting from 0)
        image_file.truncate(byte_size)
        # Write simple unique data to file before end
        image_file.seek(byte_size - len(image_file_path) - 1)
        # newline required by aexpect in function()
        image_file.write(image_file_path + '\n')
        image_file.close()

    def init_device(self, index):
        """
        Initialize and return instance of device xml for index
        """
        self.make_image_file(index)
        disk_class = self.test_params.vmxml.get_device_class('disk')
        disk_device = disk_class(type_name='file',
                                 virsh_instance=self.test_params.virsh)
        disk_device.driver = {'name': 'qemu', 'type': 'raw'}
        # No source elements by default
        source_properties = {'attrs':
                             {'file': self.make_image_file_path(index)}}
        source = disk_device.new_disk_source(**source_properties)
        disk_device.source = source  # Modified copy, not original
        dev_name = 'vd' + self.devname_suffix(self.devidx + index)
        disk_device.target = {'dev': dev_name, 'bus': 'virtio'}
        # libvirt will automatically add <address> element
        return disk_device

    def cleanup(self):
        for index in xrange(0, self.count):
            try:
                os.unlink(self.make_image_file_path(index))
            except OSError:
                pass  # Don't care if not there

    def function(self, index):
        """
        Return True/False (good/bad) result of a device functioning
        """
        dev_name = '/dev/vd' + self.devname_suffix(self.devidx + index)
        # Host image path is static known value
        test_data = self.make_image_file_path(index)
        byte_size = self.meg * 1024 * 1024
        # Place test data at end of device to also confirm sizing
        offset = byte_size - len(test_data)
        logging.info('Trying to read test data, %dth device %s, '
                     'at offset %d.', index, dev_name, offset)
        session = None
        try:
            session = self.test_params.main_vm.login()
            # aexpect combines stdout + stderr, throw away stderr
            output = session.cmd_output('tail -c %d %s'
                                        % (len(test_data) + 1, dev_name))
            session.close()
        except (virt_vm.VMAddressError, remote.LoginError,
                aexpect.ExpectError, aexpect.ShellError):
            try:
                session.close()
            except AttributeError:
                pass   # session == None
            logging.debug("VirtIODiskBasic functional test raised an exception")
            return False
        else:
            gotit = bool(output.count(test_data))
            logging.info("Test data detected in device: %s",
                         gotit)
            if not gotit:
                logging.debug("Expecting: '%s'", test_data)
                logging.debug("Received: '%s'", output)
            return gotit


def operational_action(test_params, test_devices, operational_results):
    """
    Call & store result list from operate() method on every device
    """
    if test_params.status_error:
        logging.info("Running operational tests: Failure is expected!")
    else:
        logging.info("Running operational tests")
    for device in test_devices:
        operational_results.append(device.operation_results)  # list of bools
    # STUB:
    # for device in test_devices:
    #    if test_params.status_error:
    #        operational_results = [False] * device.count
    #    else:
    #        operational_results = [True] * device.count


def preboot_action(test_params, test_devices, preboot_results):
    """
    Call & store result of function() method on every device
    """
    if test_params.preboot_function_error:
        logging.info("Running pre-reboot functional tests: Failure expected!")
    else:
        logging.info("Running pre-reboot functional tests")
    for device in test_devices:
        preboot_results.append(device.function_results)  # list of bools
    # STUB:
    # for device in test_devices:
    #    if test_params.status_error:
    #        preboot_results = [False] * device.count
    #    else:
    #        preboot_results = [True] * device.count


def postboot_action(test_params, test_devices, pstboot_results):
    """
    Call & store result of function() method on every device
    """
    if test_params.pstboot_function_error:
        logging.info("Running post-reboot functional tests: Failure expected!")
    else:
        logging.info("Running post-reboot functional tests")
    for device in test_devices:
        pstboot_results.append(device.function_results)  # list of bools
    # STUB:
    # for device in test_devices:
    #    if test_params.status_error:
    #        pstboot_results = [False] * device.count
    #    else:
    #        pstboot_results = [True] * device.count


# Save a little typing
all_true = TestDeviceBase.good_results
all_false = TestDeviceBase.bad_results


def analyze_negative_results(test_params, operational_results,
                             preboot_results, pstboot_results):
    """
    Analyze available results, return error message if fail
    """
    if not all_false(operational_results):
        return ("Negative testing operational test passed")
    if test_params.start_vm and preboot_results:
        if not all_false(preboot_results):
            return ("Negative testing pre-boot functionality test passed")
    if pstboot_results:
        if not all_false(pstboot_results):
            return ("Negative testing post-boot functionality "
                    "test passed")


def analyze_positive_results(test_params, operational_results,
                             preboot_results, pstboot_results):
    """
    Analyze available results, return error message if fail
    """
    if not all_true(operational_results):
        return ("Positive operational test failed")
    if test_params.start_vm and preboot_results:
        if not all_true(preboot_results):
            if not test_params.preboot_function_error:
                return ("Positive pre-boot functionality test failed")
            # else: An error was expected
    if pstboot_results:
        if not all_true(pstboot_results):
            if not test_params.pstboot_function_error:
                return ("Positive post-boot functionality test failed")


def analyze_results(test_params, operational_results,
                    preboot_results, pstboot_results):
    """
    Analyze available results, raise error message if fail
    """
    fail_msg = None  # Pass: None, Fail: failure reason
    if test_params.status_error:  # Negative testing
        fail_msg = analyze_negative_results(test_params, operational_results,
                                            preboot_results, pstboot_results)
    else:  # Positive testing
        fail_msg = analyze_positive_results(test_params, operational_results,
                                            preboot_results, pstboot_results)
    if fail_msg is not None:
        raise error.TestFail(fail_msg)


def run(test, params, env):
    """
    Test virsh {at|de}tach-interface command.

    1) Prepare test environment and its parameters
    2) Operate virsh on one or more devices
    3) Check functionality of each device
    4) Check functionality of mmconfig option
    5) Restore domain
    6) Handle results
    """

    logging.info("Preparing initial VM state")
    # Prepare test environment and its parameters
    test_params = TestParams(params, env, test)
    if test_params.start_vm:
        # Make sure VM is working
        test_params.main_vm.verify_alive()
        test_params.main_vm.wait_for_login().close()
    else:  # VM not suppose to be started
        if test_params.main_vm.is_alive():
            test_params.main_vm.destroy(gracefully=True)
    # Capture backup of original XML early in test
    test_params.vmxml = VMXML.new_from_inactive_dumpxml(
        test_params.main_vm.name)
    # All devices should share same access state
    test_params.virsh = virsh.Virsh(ignore_status=True)
    logging.info("Creating %d test device instances", len(test_params.devs))
    # Create test objects from cfg. class names via subclasses above
    test_devices = [globals()[class_name](test_params)  # instantiate
                    for class_name in test_params.devs]  # vadu_dev_objs
    operational_results = []
    preboot_results = []
    pstboot_results = []
    try:
        operational_action(test_params, test_devices, operational_results)
        #  Can't do functional testing with a cold VM, only test hot-attach
        preboot_action(test_params, test_devices, preboot_results)

        logging.info("Preparing test VM state for post-boot functional testing")
        if test_params.start_vm:
            # Hard-reboot required
            test_params.main_vm.destroy(gracefully=True,
                                        free_mac_addresses=False)
        try:
            test_params.main_vm.start()
        except virt_vm.VMStartError:
            raise error.TestFail('VM Failed to start for some reason!')
        # Signal devices reboot is finished
        for test_device in test_devices:
            test_device.booted = True
        test_params.main_vm.wait_for_login().close()
        postboot_action(test_params, test_devices, pstboot_results)
        analyze_results(test_params, operational_results,
                        preboot_results, pstboot_results)
    finally:
        logging.info("Restoring VM from backup, then checking results")
        test_params.main_vm.destroy(gracefully=False,
                                    free_mac_addresses=False)
        test_params.vmxml.undefine()
        test_params.vmxml.restore()  # Recover the original XML
        test_params.vmxml.define()
        if not test_params.start_vm:
            # Test began with not start_vm, shut it down.
            test_params.main_vm.destroy(gracefully=True)
        # Device cleanup can raise multiple exceptions, do it last:
        logging.info("Cleaning up test devices")
        test_params.cleanup(test_devices)
