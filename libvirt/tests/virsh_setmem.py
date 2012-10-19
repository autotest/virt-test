import re, logging
from autotest.client.shared import error
from virttest import libvirt_vm, virsh


def run_virsh_setmem(test, params, env):
    """
    Test command: virsh setmem.

    1) Prepare vm environment.
    2) Handle params
    3) Prepare libvirtd status.
    4) Run test command and wait for current memory's stable.
    5) Recover environment.
    4) Check result.
    TODO: support new libvirt with more options.
    """

    def login_to_get_vm_mem(vm):
        session = vm.login()
        meminfo = session.cmd_output("grep 'MemTotal:' /proc/meminfo")
        return int(re.search(r'\d+', meminfo).group(0))


    #Prepare vm
    vm_name = params.get("main_vm", "vm1")
    vm = env.get_vm(params["main_vm"])

    domid_result = virsh.domid(vm_name)
    domid = domid_result.strip()
    domuuid_result = virsh.domuuid(vm_name)
    domuuid = domuuid_result.strip()

    if params.get("start_vm") != "no":
        vm.wait_for_login()

    origin_mem = vm.get_used_mem()

    #Handle params for testcases
    vm_ref = params.get("setmem_vm_ref", "")
    setmem_vm = params.get("setmem_vm", "%s")
    mem_ref = params.get("setmem_mem_ref", "")
    options = params.get("setmem_options", "")
    options_prefix = params.get("setmem_options_prefix", "")
    options_suffix = params.get("setmem_options_suffix", "")

    if vm_ref == "domid":
        if domid == "-":
            vm_ref = domid
        else:
            vm_ref = int(domid)
    elif vm_ref == "domname":
        vm_ref = vm_name
    elif vm_ref == "domuuid":
        vm_ref = domuuid

    if mem_ref == "default_half":
        mem_ref = origin_mem/2

    setmem_vm = setmem_vm % vm_ref
    new_memory = mem_ref

    #Prepare libvirtd status
    libvirt = params.get("libvirt", "on")
    if libvirt == "off":
        libvirt_vm.service_libvirtd_control("stop")

    options = options_prefix + " " + options + " " + options_suffix

    result = virsh.setmem(setmem_vm, new_memory, options,
                                     ignore_status=True, debug=True)
    status = result.exit_status

    #Recover libvirtd status
    if libvirt == "off":
        libvirt_vm.service_libvirtd_control("start")

    #Get memory inside vm and outside vm
    if not status:
        if vm.state() == "shut off":
            vm.start()
        elif vm.state() == "paused":
            vm.resume()
        vm.wait_for_login()

        current_memory_outside = vm.get_used_mem()
        logging.info("\n======\nCurrent memory outside: %i\n======",
                                            current_memory_outside)
        current_memory_inside = login_to_get_vm_mem(vm)
        logging.info("\n======\nCurrent memory inside: %i\n======",
                                             current_memory_inside)

    #Check result
    vm_status_error = params.get("setmem_vm_status_error", "no")
    addition_status_error = params.get("addition_status_error", "no")
    status_error = (vm_status_error == "no") and (addition_status_error == "no")
    mem_status_error = params.get("mem_status_error", "no")
    #Expect result is decided by status_error.
    status_error = status_error and (mem_status_error == "no")
    delta_percentage = int(params.get("setmem_delta_per", "10"))
    if status_error:
        if status != 0:
            raise error.TestFail("Run failed with right command!")
        else:
            delta = abs(current_memory_outside - current_memory_inside)
            if new_memory and current_memory_outside != new_memory:
                raise error.TestFail(
                        "Run successful but result is not expected")
            if delta > (new_memory * delta_percentage)/100:
                raise error.TestFail(
                        "Run successful but result is not expected")
    else:
        if status == 0:
            raise error.TestFail("Run successful with wrong command")
