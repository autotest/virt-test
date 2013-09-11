#!/usr/bin/python
import os,logging,re
from autotest.client.shared import utils,error
from virttest import virsh

def net_list():
    """
    @return: returns all the libvirt network bridge names e.g. default,virbr1
    Name                 State      Autostart     Persistent
    --------------------------------------------------
    default              active     no            yes
    vdsm-virbr2          active     yes           yes
    virbr1               inactive   no            yes
    """

    nets=[]
    op=virsh.net_list('--all', ignore_status=True)
    op=op.stdout.strip().splitlines()
    if op:
        op=op[2:]
        for line in op:
            netlist=line.split(None,3)
            nets.append(netlist[0])
    return nets

def vir_brdg():
    """
    @return: returns all the libvirt network bridges e.g. virbr0,virbr1
    """
    v_brdgs=[]
    v_nets=net_list()
    for v_net in v_nets:
        op=virsh.net_info(v_net, ignore_status=True)
        op=op.stdout.strip()
        if op:
            v_brdg = op.split()[-1]
            v_brdgs.append(v_brdg)
    return v_brdgs

def int_faces():
    """
    @return: returns all the interfaces available in the system,eth0
    eth1 ..... virbr0,vnet1 etc.
    """

    i_faces=[]
    op=utils.run("netstat -i -a", ignore_status=True)
    op=op.stdout.strip().splitlines()
    if op:
        op=op[2:]
        for line in op:
            i_facelist=line.split(None,2)
            i_faces.append(i_facelist[0])
    return i_faces

def bridged_ifaces():
    """
    @return: returns all the interfaces which are bridged
    Below is brctl show output
    bridge name bridge id               STP enabled     interfaces
    br0         8000.e41f13180acc       yes             eth0
                                                        vnet1
    virbr0      8000.525400895d70       yes             virbr0-nic
                                                        vnet0
                                                        vnet2
                                                        vnet3
    returns eth0,vnet1,vribr0-nic...vnet3
    """

    brgd_ifaces=[]
    op=utils.run("brctl show",ignore_status=True)
    op=op.stdout.splitlines()
    if op:
        op=op[1:]
        for line in op:
            brgd_ifacelist=line.split('\t')
            if brgd_ifacelist[-1] != '':
                brgd_ifaces.append(brgd_ifacelist[-1])
            else:
                brgd_ifaces.append('lo')
    return brgd_ifaces

def bridge_ifaces():
    """
    @return: returns all bridge interfaces
    From the above commented brctl show output, it returns br0,virbr0
    """
    brg_ifaces=[]
    op=utils.run("brctl show",ignore_status=True)
    op=op.stdout.strip().splitlines()
    if op:
        op=op[1:]
        for line in op:
            brg_ifacelist=line.split('\t')
            if brg_ifacelist[0] != '':
                brg_ifaces.append(brg_ifacelist[0])
                curr_brg=brg_ifacelist[0]
            else:
                brg_ifaces.append(curr_brg)
    return brg_ifaces

def brg_details():
    """
    In "brctl show" does not show the bridge info of all subnetwork interface
    underneath the bridge. for example in the brctl output of bridged_ifaces
    method,bridge name of vnet0,vnet1,vnet2. Ideally it should be virbr0 in
    this case. This method create a list  by mapping proper bridge values for
    all the bridged interface
    """
    cur_bridge=''
    cur_interface=[]
    cur_nic=''
    brg_int_nic={}
    brg_int_nic_all=[]
    bridges=bridge_ifaces()
    interfaces=bridged_ifaces()
    for ind in range(len(interfaces)):
        if bridges[ind] != cur_bridge:
            if cur_bridge != '':
                brg_int_nic['name']=cur_bridge
                brg_int_nic['interface']=cur_interface
                brg_int_nic['nic']=cur_nic
                brg_int_nic_all.append(brg_int_nic)
                brg_int_nic={}
            cur_bridge=bridges[ind]
            cur_interface=[]
            cur_interface.append(interfaces[ind])
            cur_nic=interfaces[ind]
        else:
            cur_interface.append(interfaces[ind])
    brg_int_nic['name']=cur_bridge
    brg_int_nic['interface']=cur_interface
    brg_int_nic['nic']=cur_nic
    brg_int_nic_all.append(brg_int_nic)
    return brg_int_nic_all

def is_bridged(opt):
    """
    @return: Is it bridged?
    """
    return(opt in bridged_ifaces())

def is_bridge(opt):
    """
    @return: Is it a bridge?
    """
    return (opt in bridge_ifaces())

def eth_of_brdg(opt):
    """
    @return: the nic interface of the bridge device e.g. eth0 for br0
    """
    all_bridges=brg_details()
    for line in all_bridges:
        if line['name'] == opt:
            break
    return line['nic']

def brdg_of_eth(opt):
    """
    @return: the bridge name of the bridged device e.g. br0 for eth0 or
    virbr0 for vnet0
    """
    all_bridges=brg_details()
    for line in all_bridges:
        if line['nic'] == opt:
            break
    return line['name']

def input_ifaces():
    """
    @return: For all the iface test, bridged inetrface and libvirt
    networks are excluded. This method would create a list which
    is having all the inetrface but not the bridged device and libvirt
    network device. Means it would not include eth0,vnet0..vnet2,virbr0,
    vribr1 etc. among all the interfaces available in the host
    """
    in_ifaces=[]
    ifaces=int_faces()
    vbridges= vir_brdg()
    brgdifaces=bridged_ifaces()
    for iface in ifaces:
        if iface not in vbridges and iface not in brgdifaces:
            in_ifaces.append(iface)
    return in_ifaces


def is_suse():
    """
    @return:Is it a suse?
    """
    iss_file=open("/etc/issue",'r')
    iss_file_content=iss_file.read()
    rs=re.match('suse',iss_file.read())
    return (rs is not None)

def net_scr():
    """
    @return: network script path
    """
    if is_suse():
        return '/etc/sysconfig/network/ifcfg-'
    else:
        return '/etc/sysconfig/network-scripts/ifcfg-'

def network_scripts_backup(opt):
    """
    @return: Take the backup of network script files
    """
    utils.run("cp %s%s ifcfg-%s-org" %(net_scr(),opt,opt))
    if is_bridge(opt):
        utils.run("cp %s%s ifcfg-%s-org"%(net_scr(),eth_of_brdg(opt),eth_of_brdg(opt)))

def network_scripts_restore(opt):
    """
    @return: Restore the backup scipt files
    """
    utils.run("mv ifcfg-%s-org %s%s" %(opt,net_scr(),opt))
    if is_bridge(opt):
        utils.run("mv ifcfg-%s-org %s%s"%(eth_of_brdg(opt),net_scr(),eth_of_brdg(opt)))




def is_scr_avail(opt):
    """
    @return:If the network script is available for the interface
    """
    return os.path.exists("%s%s"%(net_scr(),opt))

def mac_of_iface(opt):
    """
    @return: Get the mac address from ifconfig
    """
    ifconf=utils.run("ifconfig %s"%opt,ignore_status=True)
    ifconf=ifconf.stdout.strip().splitlines()
    first_line=ifconf[0].split(None,5)
    return first_line[4]


def create_iface_xml(opt):
    """
    @return:create iface-xml file
    """
    utils.run("touch tmp-%s.xml"%opt)
    f = open('tmp-%s.xml'%opt,'rw+')

    if is_bridge(opt) is False:
        f.write('<interface type=\'ethernet\' name=\'%s\'>\n'%opt)
        f.write('  <start mode=\'none\'/>\n')
        if opt != 'lo':
            f.write('  <mac address=\'%s\'/>\n'%mac_of_iface(opt))
        f.write('</interface>\n')
    else:
        f.write('<interface type=\'bridge\' name=\'%s\'>\n'%opt)
        f.write('  <start mode=\'none\'/>\n')
        f.write('  <bridge>\n')
        f.write('    <interface type=\'ethernet\' name=\'%s\'>\n'%eth_of_brdg(opt))
        if eth_of_brdg(opt) != 'lo':
            f.write('      <mac address=\'%s\'/>\n'%mac_of_iface(eth_of_brdg(opt)))
        f.write('    </interface>\n')
        f.write('  </bridge>\n')
        f.write('</interface>\n')
    f.close()

def edit_iface_xml(opt):
    """
    Edit the iface-dumpxml file, currently start option is not available
    in iface-dumpxml file. So this method add the start option to the iface
    -dumpxml file.
    """
    scr_file=open("%s%s"%(net_scr(),opt),'r')
    start_mode=False
    for line in scr_file:
        line=re.sub("\n",'',line)
        rs=re.match("^ONBOOT=",line)
        if rs is not None:
            onbt=line.split("=",2)
            onbt[1]=re.sub(r'\"|\'','',onbt[1])
            if onbt[1].lower() in ('',False):
                start_mode=False
            else:
                start_mode=True
                break
    dumpxml=virsh.iface_dumpxml(opt,ignore_status=True)
    xml_param=dumpxml.stdout.strip().splitlines()
    if start_mode:
        xml_param.insert(1,'  <start mode=\'onboot\'/>')
    else:
        xml_param.insert(1,'  <start mode=\'none\'/>')
    utils.run("touch tmp-%s.xml"%opt)
    f = open('tmp-%s.xml'%opt,'rw+')
    for line in xml_param:
        f.write("%s\n"%line)
    f.close()

def destroy_iface_xml(opt):
    """
    remove the iface-dumpxml file
    """
    utils.run("rm -f tmp-%s.xml"%opt)


def is_ipaddr_ifcon(opt):
    """
    Is ipaddress available to the interface thru ifconfig. If yes,
    iface start/destroy and bridge/unbridge is not allowed
    """
    op=utils.run("ifconfig %s"%opt,ignore_status=True)
    op=op.stdout.strip()
    rs=re.search(r'\binet\b',op)
    return (rs is not None)

def is_ipaddr_scr(opt):
    """
    Is ipaddress available to the interface thru network script. If yes,
    iface start/destroy and bridge/unbridge is not allowed
    """

    found=False
    if is_scr_avail(opt):
        scr_file=open("%s%s"%(net_scr(),opt),'r')
        for line in scr_file:
            line=re.sub(r'\n','',line)
            rs=re.match(r'^IPADDR=',line)
            if rs is not None:
                ipad=line.split('=',2)
                if ipad[1] not in ('\'\'','\"\"') or ipad[1]:
                    found=True
                    break
        scr_file.close()
    return found

def is_ipaddr(opt):
    """
    Is ipaddress available to the interface thru ifconfig or script.
    If yes, iface start/destroy and bridge/unbridge is not allowed
    """

    return (is_ipaddr_scr(opt) or is_ipaddr_ifcon(opt))

def ifup(opt):
    """
    Make the inetrface up
    """
    utils.run("ifup %s"%opt)

def ifdown(opt):
    """
    Make the inetrface down
    """
    utils.run("ifdown %s"%opt)

def is_up(opt):
    """
    Check if the interface is up
    """
    op=utils.run("ifconfig %s"%opt,ignore_status=True)
    op=op.stdout.strip()
    rs=re.search(r'\bUP\b',op)
    return (rs is not None)



def virsh_ifaces(opt):
    """
    Create the list of dicts for the output of virsh iface-list
    """
    ifaces = []
    iface = {}
    output=virsh.iface_list(opt,ignore_status=True)
    ifacelist = output.stdout.strip().splitlines()
    ifacelist = ifacelist[2:]
    for line in ifacelist:
        linesplit = line.split(None, 3)
        iface['name']= linesplit[0]
        try:
            iface['mac']= linesplit[2]
        except IndexError:
            iface['mac']=''
        iface['state']= linesplit[1]
        ifaces.append(iface)
        iface = {}
    return ifaces

def check_vir_iface(opt,opt1):
    """
    check the details of the interface from virsh iface-list
    """
    iface_all=virsh_ifaces(opt1)
    found=0
    iface_dtl = {'avail':False,'mac':'','state':''}
    for line in iface_all:
        if line['name']==opt:
            iface_dtl['avail']=True
            iface_dtl['mac']=line['mac']
            iface_dtl['state']=line['state']
            break
    return iface_dtl

def iface_vir_mac(opt):
    """
    Get the interface name from mac address available in virsh iface-list --all
    """
    iface_all=virsh_ifaces('--all')
    iface_name=''
    for line in iface_all:
        if line['mac']==opt:
            iface_name=line['name']
            break
    return iface_name

def avail_vir_iface(opt):
    """
    check the presence of the inetrface in the virsh iface-list --all
    """
    vir_iface_detail=check_vir_iface(opt,'--all')
    return vir_iface_detail['avail']

def mac_vir_iface(opt):
    """
    get the mac of the inetrface in the virsh iface-list --all
    """
    vir_iface_detail=check_vir_iface(opt,'--all')
    return vir_iface_detail['mac']

def state_vir_iface(opt):
    """
    get the state of the inetrface in the virsh iface-list --all
    """
    vir_iface_detail=check_vir_iface(opt,'--all')
    return vir_iface_detail['state']

def avail_vir_iface_active(opt):
    """
    check the presence of the inetrface in the virsh iface-list
    """
    vir_iface_detail=check_vir_iface(opt,'')
    return vir_iface_detail['avail']

def mac_vir_iface_active(opt):
    """
    get the mac of the inetrface in the virsh iface-list
    """
    vir_iface_detail=check_vir_iface(opt,'')
    return vir_iface_detail['mac']

def state_vir_iface_active(opt):
    """
    get the state of the inetrface in the virsh iface-list
    """
    vir_iface_detail=check_vir_iface(opt,'')
    return vir_iface_detail['state']

def avail_vir_iface_inactive(opt):
    """
    check the presence of the inetrface in the virsh iface-list --inactive
    """
    vir_iface_detail=check_vir_iface(opt,'--inactive')
    return vir_iface_detail['avail']

def mac_vir_iface_inactive(opt):
    """
    get the mac of the inetrface in the virsh iface-list --inactive
    """
    vir_iface_detail=check_vir_iface(opt,'--inactive')
    return vir_iface_detail['mac']

def state_vir_iface_inactive(opt):
    """
    get the state of the inetrface in the virsh iface-list --inactive
    """
    vir_iface_detail=check_vir_iface(opt,'--inactive')
    return vir_iface_detail['state']

def chk_state_vir_iface(opt):
    """
    check the state of the inetrface in the virsh iface-list --all
    with respect to ofconfig
    """
    if is_up(opt):
        return (state_vir_iface(opt) == 'active')
    else:
        return (state_vir_iface(opt) == 'inactive')

def chk_mac_vir_iface(opt):
    """
    check the mac of the inetrface in the virsh iface-list --all
    with respect to ofconfig. For lo, virsh returns diffrent values
    """

    if opt != 'lo':
        return (mac_vir_iface(opt) ==  mac_of_iface(opt).lower())
    else:
        if is_suse():
            return (mac_vir_iface(opt) == '')
        else:
            return (mac_vir_iface(opt) == '00:00:00:00:00:00')

def chk_state_vir_iface_inactive(opt):
    """
    check the state of the inetrface in the virsh iface-list --inactive
    with respect to ofconfig
    """

    if is_up(opt):
        return (state_vir_iface_inactive(opt) == 'active')
    else:
        return (state_vir_iface_inactive(opt) == 'inactive')

def chk_mac_vir_iface_inactive(opt):
    """
    check the mac of the inetrface in the virsh iface-list --inactive
    with respect to ofconfig. For lo, virsh returns diffrent values
    """

    if opt != 'lo':
        return (mac_vir_iface_inactive(opt) ==  mac_of_iface(opt).lower())
    else:
        if is_suse():
            return (mac_vir_iface_inactive(opt) == '')
        else:
            return (mac_vir_iface_inactive(opt) == '00:00:00:00:00:00')

def chk_state_vir_iface_active(opt):
    """
    check the state of the inetrface in the virsh iface-list
    with respect to ofconfig
    """

    if is_up(opt):
        return (state_vir_iface_active(opt) == 'active')
    else:
        return (state_vir_iface_active(opt) == 'inactive')

def chk_mac_vir_iface_active(opt):
    """
    check the mac of the inetrface in the virsh iface-list
    with respect to ofconfig. For lo, virsh returns diffrent values
    """

    if opt != 'lo':
        return (mac_vir_iface_active(opt) ==  mac_of_iface(opt).lower())
    else:
        if is_suse():
            return (mac_vir_iface_active(opt) == '')
        else:
            return (mac_vir_iface_active(opt) == '00:00:00:00:00:00')
