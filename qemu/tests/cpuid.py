"""
Group of cpuid tests for X86 CPU
"""
import re, sys, traceback, os, string
from autotest.client.shared import error, utils
from autotest.client.shared import test as test_module
from virttest import utils_misc, env_process

import logging
logger = logging.getLogger(__name__)
dbg = logger.debug
info = logger.info

def run_cpuid(test, params, env):
    """
    Boot guest with different cpu_models and cpu flags and check if guest works correctly.

    @param test: kvm test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    qemu_binary = utils_misc.get_qemu_binary(params)

    cpu_model = params.get("cpu_model", "qemu64")

    xfail = False
    if (params.get("xfail") is not None) and (params.get("xfail") == "yes"):
        xfail = True

    class MiniSubtest(test_module.Subtest):
        """
        subtest base class for actual tests
        """
        def __new__(cls, *args, **kargs):
            self = test.__new__(cls)
            ret = None
            if args is None:
                args = []
            try:
                ret = self.test(*args, **kargs)
            finally:
                if hasattr(self, "clean"):
                    self.clean()
            return ret

        def clean(self):
            """
            cleans up running VM instance
            """
            if (hasattr(self, "vm")):
                vm = getattr(self, "vm")
                if vm.is_alive():
                    vm.pause()
                    vm.destroy(gracefully=False)

        def test(self):
            """
            stub for actual test code
            """
            raise error.TestFail("test() must be redifined in subtest")

    def print_exception(called_object):
        """
        print error including stack trace
        """
        exc_type, exc_value, exc_traceback = sys.exc_info()
        logging.error("In function (" + called_object.__name__ + "):")
        logging.error("Call from:\n" +
                      traceback.format_stack()[-2][:-1])
        logging.error("Exception from:\n" +
                      "".join(traceback.format_exception(
                                              exc_type, exc_value,
                                              exc_traceback.tb_next)))

    def cpu_models_to_test():
        """Return the list of CPU models to be tested, based on the
        cpu_models and cpu_model config options.

        Config option "cpu_model" may be used to ask a single CPU model
        to be tested. Config option "cpu_models" may be used to ask
        multiple CPU models to be tested.

        If cpu_models is "*", all CPU models reported by QEMU will be tested.
        """
        models_opt = params.get("cpu_models")
        model_opt = params.get("cpu_model")

        if (models_opt is None and model_opt is None):
            raise error.TestError("No cpu_models or cpu_model option is set")

        cpu_models = set()

        if models_opt == '*':
            cpu_models.update(utils_misc.get_qemu_cpu_models(qemu_binary))
        elif models_opt:
            cpu_models.update(models_opt.split())

        if model_opt:
            cpu_models.add(model_opt)

        return cpu_models

    class test_qemu_cpu_models_list(MiniSubtest):
        """
        check CPU models returned by <qemu> -cpu '?' are what is expected
        """
        def test(self):
            """
            test method
            """
            cpu_models = cpu_models_to_test()
            qemu_models = utils_misc.get_qemu_cpu_models(qemu_binary)
            missing = set(cpu_models) - set(qemu_models)
            if missing:
                raise error.TestFail("Some CPU models not in QEMU CPU model list: %s")
            added = set(qemu_models) - set(cpu_models)
            if added:
                logging.info("Extra CPU models in QEMU CPU listing: %s", added)

    def compare_cpuid_output(a, b):
        """
        Generates a list of (register, bit, va, vb) tuples for
        each bit that is different between a and b.
        """
        for reg in ('eax', 'ebx', 'ecx', 'edx'):
            for bit in range(32):
                ba = (a[reg] & (1 << bit)) >> bit
                bb = (b[reg] & (1 << bit)) >> bit
                if ba <> bb:
                    yield (reg, bit, ba, bb)

    def parse_cpuid_dump(output):
        dbg("parsing cpuid dump: %r", output)
        cpuid_re = re.compile("^ *(0x[0-9a-f]+) +0x([0-9a-f]+): +eax=0x([0-9a-f]+) ebx=0x([0-9a-f]+) ecx=0x([0-9a-f]+) edx=0x([0-9a-f]+)$")
        output_re = re.compile('(..x)=0x([0-9a-f]+)')
        out_lines = output.splitlines()
        if out_lines[0] <> '==START TEST==' or out_lines[-1] <> '==END TEST==':
            dbg("cpuid dump doesn't have expected delimiters")
            return None
        if out_lines[1] <> 'CPU:':
            dbg("cpuid dump doesn't start with 'CPU:' line")
            return None
        result = {}
        for l in out_lines[2:-1]:
            m = cpuid_re.match(l)
            if m is None:
                dbg("invalid cpuid dump line: %r", l)
                return None
            in_eax = int(m.group(1), 16)
            in_ecx = int(m.group(2), 16)
            out = {
                'eax':int(m.group(3), 16),
                'ebx':int(m.group(4), 16),
                'ecx':int(m.group(5), 16),
                'edx':int(m.group(6), 16),
            }
            result[(in_eax, in_ecx)] = out
        return result


    def get_guest_cpuid(self, cpu_model, feature=None, extra_params=None):
        test_kernel_dir = os.path.join(test.virtdir, "deps",
                                       "cpuid_test_kernel")
        os.chdir(test_kernel_dir)
        utils.make("cpuid_dump_kernel.bin")

        vm_name = params['main_vm']
        params_b = params.copy()
        params_b["kernel"] = os.path.join(test_kernel_dir, "cpuid_dump_kernel.bin")
        params_b["cpu_model"] = cpu_model
        params_b["cpu_model_flags"] = feature
        del params_b["images"]
        del params_b["nics"]
        if extra_params:
            params_b.update(extra_params)
        env_process.preprocess_vm(self, params_b, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.create()
        self.vm = vm
        vm.resume()

        timeout = float(params.get("login_timeout", 240))
        f = lambda: re.search("==END TEST==", vm.serial_console.get_output())
        if not utils_misc.wait_for(f, timeout, 1):
            raise error.TestFail("Could not get test complete message.")

        test_output = parse_cpuid_dump(vm.serial_console.get_output())
        if test_output is None:
            raise error.TestFail("Test output signature not found in "
                                 "output:\n %s", vm.serial_console.get_output())
        self.clean()
        return test_output

    def cpuid_to_vendor(cpuid_dump, idx):
        r = cpuid_dump[idx, 0]
        dst =  []
        map(lambda i:
            dst.append((chr(r['ebx'] >> (8 * i) & 0xff))), range(0, 4))
        map(lambda i:
            dst.append((chr(r['edx'] >> (8 * i) & 0xff))), range(0, 4))
        map(lambda i:
            dst.append((chr(r['ecx'] >> (8 * i) & 0xff))), range(0, 4))
        return ''.join(dst)

    class default_vendor(MiniSubtest):
        """
        Boot qemu with specified cpu models and
        verify that CPU vendor matches requested
        """
        def test(self):
            cpu_models = cpu_models_to_test()

            vendor = params.get("vendor")
            if vendor is None or vendor == "host":
                cmd = "grep 'vendor_id' /proc/cpuinfo | head -n1 | awk '{print $3}'"
                cmd_result = utils.run(cmd, ignore_status=True)
                vendor = cmd_result.stdout.strip()

            ignore_cpus = set(params.get("ignore_cpu_models","").split(' '))
            cpu_models = cpu_models - ignore_cpus

            for cpu_model in cpu_models:
                out = get_guest_cpuid(self, cpu_model)
                guest_vendor = cpuid_to_vendor(out, 0x00000000)
                logging.debug("Guest's vendor: " + guest_vendor)
                if guest_vendor != vendor:
                    raise error.TestFail("Guest vendor [%s], doesn't match "
                                         "required vendor [%s] for CPU [%s]" %
                                         (guest_vendor, vendor, cpu_model))

    class custom_vendor(MiniSubtest):
        """
        Boot qemu with specified vendor
        """
        def test(self):
            has_error = False
            vendor = params["vendor"]

            try:
                out = get_guest_cpuid(self, cpu_model, "vendor=" + vendor)
                guest_vendor0 = cpuid_to_vendor(out, 0x00000000)
                guest_vendor80000000 = cpuid_to_vendor(out, 0x80000000)
                logging.debug("Guest's vendor[0]: " + guest_vendor0)
                logging.debug("Guest's vendor[0x80000000]: " +
                              guest_vendor80000000)
                if guest_vendor0 != vendor:
                    raise error.TestFail("Guest vendor[0] [%s], doesn't match "
                                         "required vendor [%s] for CPU [%s]" %
                                         (guest_vendor0, vendor, cpu_model))
                if guest_vendor80000000 != vendor:
                    raise error.TestFail("Guest vendor[0x80000000] [%s], "
                                         "doesn't match required vendor "
                                         "[%s] for CPU [%s]" %
                                         (guest_vendor80000000, vendor,
                                          cpu_model))
            except:
                has_error = True
                if xfail is False:
                    raise
            if (has_error is False) and (xfail is True):
                raise error.TestFail("Test was expected to fail, but it didn't")

    def cpuid_to_level(cpuid_dump):
        r = cpuid_dump[0, 0]
        return r['eax']

    class custom_level(MiniSubtest):
        """
        Boot qemu with specified level
        """
        def test(self):
            has_error = False
            level = params["level"]
            try:
                out = get_guest_cpuid(self, cpu_model, "level=" + level)
                guest_level = str(cpuid_to_level(out))
                if guest_level != level:
                    raise error.TestFail("Guest's level [%s], doesn't match "
                                         "required level [%s]" %
                                         (guest_level, level))
            except:
                has_error = True
                if xfail is False:
                    raise
            if (has_error is False) and (xfail is True):
                raise error.TestFail("Test was expected to fail, but it didn't")

    def cpuid_to_family(cpuid_dump):
        # Intel Processor Identification and the CPUID Instruction
        # http://www.intel.com/Assets/PDF/appnote/241618.pdf
        # 5.1.2 Feature Information (Function 01h)
        eax = cpuid_dump[1, 0]['eax']
        family = (eax >> 8) & 0xf
        if family  == 0xf:
            # extract extendend family
            return family + ((eax >> 20) & 0xff)
        return family

    class custom_family(MiniSubtest):
        """
        Boot qemu with specified family
        """
        def test(self):
            has_error = False
            family = params["family"]
            try:
                out = get_guest_cpuid(self, cpu_model, "family=" + family)
                guest_family = str(cpuid_to_family(out))
                if guest_family != family:
                    raise error.TestFail("Guest's family [%s], doesn't match "
                                         "required family [%s]" %
                                         (guest_family, family))
            except:
                has_error = True
                if xfail is False:
                    raise
            if (has_error is False) and (xfail is True):
                raise error.TestFail("Test was expected to fail, but it didn't")

    def cpuid_to_model(cpuid_dump):
        # Intel Processor Identification and the CPUID Instruction
        # http://www.intel.com/Assets/PDF/appnote/241618.pdf
        # 5.1.2 Feature Information (Function 01h)
        eax = cpuid_dump[1, 0]['eax']
        model = (eax >> 4) & 0xf
        # extended model
        model |= (eax >> 12) & 0xf0
        return model

    class custom_model(MiniSubtest):
        """
        Boot qemu with specified model
        """
        def test(self):
            has_error = False
            model = params["model"]
            try:
                out = get_guest_cpuid(self, cpu_model, "model=" + model)
                guest_model = str(cpuid_to_model(out))
                if guest_model != model:
                    raise error.TestFail("Guest's model [%s], doesn't match "
                                         "required model [%s]" %
                                         (guest_model, model))
            except:
                has_error = True
                if xfail is False:
                    raise
            if (has_error is False) and (xfail is True):
                raise error.TestFail("Test was expected to fail, but it didn't")

    def cpuid_to_stepping(cpuid_dump):
        # Intel Processor Identification and the CPUID Instruction
        # http://www.intel.com/Assets/PDF/appnote/241618.pdf
        # 5.1.2 Feature Information (Function 01h)
        eax = cpuid_dump[1, 0]['eax']
        stepping = eax & 0xf
        return stepping

    class custom_stepping(MiniSubtest):
        """
        Boot qemu with specified stepping
        """
        def test(self):
            has_error = False
            stepping = params["stepping"]
            try:
                out = get_guest_cpuid(self, cpu_model, "stepping=" + stepping)
                guest_stepping = str(cpuid_to_stepping(out))
                if guest_stepping != stepping:
                    raise error.TestFail("Guest's stepping [%s], doesn't match "
                                         "required stepping [%s]" %
                                         (guest_stepping, stepping))
            except:
                has_error = True
                if xfail is False:
                    raise
            if (has_error is False) and (xfail is True):
                raise error.TestFail("Test was expected to fail, but it didn't")

    def cpuid_to_xlevel(cpuid_dump):
        # Intel Processor Identification and the CPUID Instruction
        # http://www.intel.com/Assets/PDF/appnote/241618.pdf
        # 5.2.1 Largest Extendend Function # (Function 80000000h)
        return cpuid_dump[0x80000000, 0x00]['eax']

    class custom_xlevel(MiniSubtest):
        """
        Boot qemu with specified xlevel
        """
        def test(self):
            has_error = False
            xlevel = params["xlevel"]
            if params.get("expect_xlevel") is not None:
                xlevel = params.get("expect_xlevel")

            try:
                out = get_guest_cpuid(self, cpu_model, "xlevel=" +
                                      params.get("xlevel"))
                guest_xlevel = str(cpuid_to_xlevel(out))
                if guest_xlevel != xlevel:
                    raise error.TestFail("Guest's xlevel [%s], doesn't match "
                                         "required xlevel [%s]" %
                                         (guest_xlevel, xlevel))
            except:
                has_error = True
                if xfail is False:
                    raise
            if (has_error is False) and (xfail is True):
                raise error.TestFail("Test was expected to fail, but it didn't")

    def cpuid_to_model_id(cpuid_dump):
        # Intel Processor Identification and the CPUID Instruction
        # http://www.intel.com/Assets/PDF/appnote/241618.pdf
        # 5.2.3 Processor Brand String (Functions 80000002h, 80000003h,
        # 80000004h)
        m_id = ""
        for idx in (0x80000002, 0x80000003, 0x80000004):
            regs = cpuid_dump[idx, 0]
            for name in ('eax', 'ebx', 'ecx', 'edx'):
                for shift in range(4):
                    c = ((regs[name] >> (shift * 8)) & 0xff)
                    if c == 0: # drop trailing \0-s
                        break
                    m_id += chr(c)
        return m_id

    class custom_model_id(MiniSubtest):
        """
        Boot qemu with specified model_id
        """
        def test(self):
            has_error = False
            model_id = params["model_id"]

            try:
                out = get_guest_cpuid(self, cpu_model, "model_id='%s'" %
                                      model_id)
                guest_model_id = cpuid_to_model_id(out)
                if guest_model_id != model_id:
                    raise error.TestFail("Guest's model_id [%s], doesn't match "
                                         "required model_id [%s]" %
                                         (guest_model_id, model_id))
            except:
                has_error = True
                if xfail is False:
                    raise
            if (has_error is False) and (xfail is True):
                raise error.TestFail("Test was expected to fail, but it didn't")

    def cpuid_regs_to_string(cpuid_dump, leaf, idx, regs):
        r = cpuid_dump[leaf, idx]
        signature = ""
        for i in regs:
            for shift in range(0, 4):
                c = chr((r[i] >> (shift * 8)) & 0xFF)
                if c in string.printable:
                    signature = signature + c
                else:
                    signature = "%s\\x%02x" % (signature, ord(c))
        logging.debug("(%s.%s:%s: signature: %s" % (leaf, idx, str(regs),
                                                    signature))
        return signature

    class cpuid_signature(MiniSubtest):
        """
        test signature in specified leaf:index:regs
        """
        def test(self):
            has_error = False
            flags = params.get("flags","")
            leaf = int(params.get("leaf","0x40000000"), 0)
            idx = int(params.get("index","0x00"), 0)
            regs = params.get("regs","ebx ecx edx").split()
            signature = params["signature"]
            try:
                out = get_guest_cpuid(self, cpu_model, flags)
                _signature = cpuid_regs_to_string(out, leaf, idx, regs)
                if _signature != signature:
                    raise error.TestFail("Guest's signature [%s], doesn't"
                                         "match required signature [%s]" %
                                         (_signature, signature))
            except:
                has_error = True
                if xfail is False:
                    raise
            if (has_error is False) and (xfail is True):
                raise error.TestFail("Test was expected to fail, but it didn't")

    class cpuid_bit_test(MiniSubtest):
        """
        test bits in specified leaf:func:reg
        """
        def test(self):
            has_error = False
            flags = params.get("flags","")
            leaf = int(params.get("leaf","0x40000000"), 0)
            idx = int(params.get("index","0x00"), 0)
            reg = params.get("reg","eax")
            bits = params["bits"].split()
            try:
                out = get_guest_cpuid(self, cpu_model, flags)
                r = out[leaf, idx][reg]
                logging.debug("CPUID(%s.%s).%s=0x%08x" % (leaf, idx, reg, r))
                for i in bits:
                    if (r & (1 << int(i))) == 0:
                        raise error.TestFail("CPUID(%s.%s).%s[%s] is not set" %
                                             (leaf, idx, reg, i))
            except:
                has_error = True
                if xfail is False:
                    raise
            if (has_error is False) and (xfail is True):
                raise error.TestFail("Test was expected to fail, but it didn't")

    class cpuid_reg_test(MiniSubtest):
        """
        test register value in specified leaf:index:reg
        """
        def test(self):
            has_error = False
            flags = params.get("flags","")
            leaf = int(params.get("leaf", "0x00"), 0)
            idx = int(params.get("index","0x00"), 0)
            reg = params.get("reg","eax")
            val = int(params["value"], 0)
            try:
                out = get_guest_cpuid(self, cpu_model, flags)
                r = out[leaf, idx][reg]
                logging.debug("CPUID(%s.%s).%s=0x%08x" % (leaf, idx, reg, r))
                if r != val:
                    raise error.TestFail("CPUID(%s.%s).%s is not 0x%08x" %
                                         (leaf, idx, reg, val))
            except:
                has_error = True
                if xfail is False:
                    raise
            if (has_error is False) and (xfail is True):
                raise error.TestFail("Test was expected to fail, but it didn't")


    # subtests runner
    test_type = params["test_type"]
    if test_type in locals():
        tests_group = locals()[test_type]
        try:
            tests_group()
        except:
            print_exception(tests_group)
            raise
    else:
        raise error.TestError("Test group '%s' is not defined in"
                              " test" % test_type)
