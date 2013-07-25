import common
import os

from autotest.client import utils
from autotest.client.shared import service as shared_service
from autotest.client.shared import error
from virttest import remote


def get_remote_runner(session):
    def run(command):
        """
        Execute command with session and return a utils.CmdResult object.

        """
        status, output = session.cmd_status_output(command)
        return utils.CmdResult(command=command,
                               exit_status=status,
                               stdout=output,
                               stderr=output)
    return run


def get_name_of_init(remote_session=None):
    """
    Determine what executable is PID 1, aka init by checking /proc/1/exe
    This init detection will only run once and cache the return value.

    :return: executable name for PID 1, aka init
    :rtype:  str
    """
    if remote_session is None:
        return os.path.basename(os.readlink("/proc/1/exe"))
    else:
        status, output = remote_session.cmd_status_output("readlink /proc/1/exe")
        if status:
            raise error.TestError("remote_session %s is not suitable"
                                  " for get_name_of_init.\n Detail: %s."
                                  % output)
        return os.path.basename(output.strip())


def _get_service_result_parser(remote_session=None):
    """
    Get the ServiceResultParser using the auto-detect init command.

    :return: ServiceResultParser fro the current init command.
    :rtype: _ServiceResultParser
    """
    result_parser = shared_service._result_parsers[get_name_of_init()]
    _service_result_parser = shared_service._ServiceResultParser(result_parser)
    return _service_result_parser


def _get_service_command_generator(remote_session=None):
    """
    Lazy initializer for ServiceCommandGenerator using the auto-detect init command.

    :return: ServiceCommandGenerator for the current init command.
    :rtype: _ServiceCommandGenerator
    """
    init_name = get_name_of_init(remote_session)
    command_generator = shared_service._command_generators[init_name]
    return shared_service._ServiceCommandGenerator(command_generator)


def ServiceManager(remote_ip=None, remote_user="root",
                   remote_pwd=None):
    """
    Detect which init program is being used, init or systemd and return a
    class has methods to start/stop services.

    # Get the system service manager
    service_manager = ServiceManager()
    ## Or get the system service manager for remote host (guest).
    #service_manager = ServiceManager(remote_ip=YOUR.REMOTE.IP,
                                     remote_pwd=YOUR.REMOTE.PWD)

    # Stating service/unit "sshd"
    service_manager.start("sshd")

    # Getting a list of available units
    units = service_manager.list()

    # Disabling and stopping a list of services
    services_to_disable = ['ntpd', 'httpd']
    for s in services_to_disable:
        service_manager.disable(s)
        service_manager.stop(s)

    :return: SysVInitServiceManager or SystemdServiceManager
    :rtype: _GenericServiceManager
    """
    global _service_managers_dict
    try:
        # if remote_ip is None, local service manager is
        # stored in service_managers and the key is None.
        return _service_managers_dict[remote_ip]
    except (NameError, KeyError), detail:
        if isinstance(detail, NameError):
            _service_managers_dict = {}

        if remote_ip is None:
            # Service manager for local host.
            service_manager = shared_service._service_managers[get_name_of_init()]
            _service_managers_dict[None] = service_manager(
                                            _get_service_command_generator(),
                                            _get_service_result_parser())
        else:
            # service manager for remote host (guest).
            session = remote.wait_for_login('ssh', remote_ip, '22',
                                            remote_user, remote_pwd,
                                            r"[\#\$]\s*$")
            service_manager = shared_service._service_managers[get_name_of_init(session)]
            command_generator = _get_service_command_generator(session)
            result_parser = _get_service_result_parser(session)
            _service_managers_dict[remote_ip] = service_manager(command_generator,
                                                                result_parser,
                                                                run=get_remote_runner(session))

        return _service_managers_dict[remote_ip]


def _auto_create_specific_service_result_parser(remote_session=None):
    """
    Create a class that will create partial functions that generate result_parser
    for the current init command.

    :return: A ServiceResultParser for the auto-detected init command.
    :rtype: _ServiceResultParser
    """
    result_parser = shared_service._result_parsers[get_name_of_init(remote_session)]
    # remove list method
    command_list = [c for c in shared_service.COMMANDS if c not in ["list", "set_target"]]
    return shared_service._ServiceResultParser(result_parser, command_list)


def _auto_create_specific_service_command_generator(remote_session=None):
    """
    Create a class that will create partial functions that generate commands
    for the current init command.

    lldpad = SpecificServiceManager("lldpad",
     auto_create_specific_service_command_generator())
    lldpad.start()
    lldpad.stop()

    :return: A ServiceCommandGenerator for the auto-detected init command.
    :rtype: _ServiceCommandGenerator
    """
    init_name = get_name_of_init(remote_session)
    command_generator = shared_service._command_generators[init_name]
    # remove list method
    command_list = [c for c in shared_service.COMMANDS if c not in ["list", "set_target"]]
    return shared_service._ServiceCommandGenerator(command_generator, command_list)


def SpecificServiceManager(service_name, remote_ip=None,
                           remote_user='root', remote_pwd=None):
    """

    # Get the specific service manager for sshd
    sshd = SpecificServiceManager("sshd")
    ## Or get the specific service manager for sshd in remote host (guest).
    #sshd = SpecificServiceManager("sshd", remote_ip=YOUR.REMOTE.IP,
                                   remote_pwd=YOUR.REMOTE.PWD)
    sshd.start()
    sshd.stop()
    sshd.reload()
    sshd.restart()
    sshd.condrestart()
    sshd.status()
    sshd.enable()
    sshd.disable()
    sshd.is_enabled()

    :param service_name: systemd unit or init.d service to manager
    :type service_name: str
    :return: SpecificServiceManager that has start/stop methods
    :rtype: _SpecificServiceManager
    """
    if remote_ip is None:
        return shared_service._SpecificServiceManager(service_name,
                     _auto_create_specific_service_command_generator(),
                     _auto_create_specific_service_result_parser())
    else:
        session = remote.wait_for_login('ssh', remote_ip, '22',
                                        remote_user, remote_pwd,
                                        r"[\#\$]\s*$")
        command_generator = _auto_create_specific_service_command_generator(session)
        result_parser = _auto_create_specific_service_result_parser(session)
        return shared_service._SpecificServiceManager(service_name,
                                       command_generator,
                                       result_parser,
                                       run=get_remote_runner(session))
