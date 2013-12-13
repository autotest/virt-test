import logging
import threading
import time
from autotest.client.shared import error
from virttest import virsh


# To get result in thread, using global parameters
# result of virsh migrate-setmaxdowntime command
global ret_setmmdt
# result of virsh migrate command
global ret_migration
ret_setmmdt = False
ret_migration = False


def thread_func_setmmdt(domain, downtime, extra, dargs):
    """
    Thread for virsh migrate-setmaxdowntime command.
    """
    global ret_setmmdt
    result = virsh.migrate_setmaxdowntime(domain, downtime, extra,
                                          **dargs)
    if result.exit_status:
        ret_setmmdt = False
        logging.error("Set max migration downtime failed.")
    else:
        ret_setmmdt = True


def thread_func_live_migration(vm, dest_uri, dargs):
    """
    Thread for virsh migrate command.
    """
    # Migrate the domain.
    debug = dargs.get("debug", "False")
    ignore_status = dargs.get("ignore_status", "False")
    options = "--live"
    extra = dargs.get("extra")
    global ret_migration
    result = vm.migrate(dest_uri, options, extra, ignore_status, debug)
    if result.exit_status:
        logging.error("Migrate %s to %s failed." % (vm.name, dest_uri))
        return

    if vm.is_alive():  # vm.connect_uri has been updated to dest_uri
        logging.info("Alive guest found on destination %s." % dest_uri)
    else:
        logging.error("VM not alive on destination %s" % dest_uri)
        return
    ret_migration = True


def cleanup_dest(vm, src_uri, dest_uri):
    """
    Cleanup migrated guest on destination.
    Then reset connect uri to src_uri
    """
    vm.connect_uri = dest_uri
    if vm.exists():
        if vm.is_persistent():
            vm.undefine()
        if vm.is_alive():
            vm.destroy()
    # Set connect uri back to local uri
    vm.connect_uri = src_uri


def run(test, params, env):
    """
    Test virsh migrate-setmaxdowntime command.

    1) Prepare migration environment
    2) Start migration and set migrate-maxdowntime
    3) Cleanup environment(migrated vm on destination)
    4) Check result
    """
    vm_ref = params.get("vm_ref", "name")
    dest_uri = params.get(
        "virsh_migrate_dest_uri", "qemu+ssh://EXAMPLE/system")
    src_uri = params.get(
        "virsh_migrate_src_uri", "qemu+ssh://EXAMPLE/system")
    pre_vm_state = params.get("pre_vm_state", "running")
    status_error = "yes" == params.get("status_error", "no")
    do_migrate = "yes" == params.get("do_migrate", "yes")
    downtime = params.get("migrate_maxdowntime", 1000)
    extra = params.get("setmmdt_extra")
    # A delay between threads
    delay_time = int(params.get("delay_time", 1))
    # timeout of threads
    thread_timeout = 180

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    domuuid = vm.get_uuid()
    # Confirm vm is running
    if not vm.is_alive():
        vm.start()
    vm.wait_for_login()
    domid = vm.get_id()
    if dest_uri.count('///') or dest_uri.count('EXAMPLE'):
        raise error.TestNAError("Set your destination uri first.")
    if src_uri.count('///') or src_uri.count('EXAMPLE'):
        raise error.TestNAError("Set your source uri first.")
    if src_uri == dest_uri:
        raise error.TestNAError("You should not set dest uri same as local.")

    setmmdt_dargs = {'debug': True, 'ignore_status': False, 'uri': src_uri}
    migrate_dargs = {'debug': True, 'ignore_status': False}

    # Confirm how to reference a VM.
    if vm_ref == "domname":
        vm_ref = vm_name
    elif vm_ref == "domid":
        vm_ref = domid
    elif vm_ref == "domuuid":
        vm_ref = domuuid

    # Prepare vm state
    if pre_vm_state == "paused":
        vm.pause()
    elif pre_vm_state == "shutoff":
        vm.destroy()

    try:
        # Set max migration downtime must be during migration
        # Using threads for synchronization
        threads = []
        if do_migrate:
            threads.append(threading.Thread(target=thread_func_live_migration,
                                            args=(vm, dest_uri,
                                                  migrate_dargs)))

        threads.append(threading.Thread(target=thread_func_setmmdt,
                                        args=(vm_ref, downtime, extra,
                                              setmmdt_dargs)))
        for thread in threads:
            thread.start()
            # Migration must be executing before setting maxdowntime
            time.sleep(delay_time)
        # Wait until thread is over
        for thread in threads:
            thread.join(thread_timeout)

    finally:
        # Clean up.
        if do_migrate:
            cleanup_dest(vm, src_uri, dest_uri)

        if vm.is_paused():
            vm.resume()

    # Check results.
    if status_error:
        if ret_setmmdt:
            raise error.TestFail("virsh migrate-setmaxdowntime succeed "
                                 "but not expected.")
    else:
        if do_migrate and not ret_migration:
            raise error.TestFail("Migration failed.")

        if not ret_setmmdt:
            raise error.TestFail("virsh migrate-setmaxdowntime failed.")
