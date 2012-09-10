#!/bin/bash

brname='vbr0'

add_br()
{
    echo "add new private bridge"
    /usr/sbin/brctl addbr $brname
    echo 1 > /proc/sys/net/ipv6/conf/$brname/disable_ipv6
    echo 1 > /proc/sys/net/ipv4/ip_forward
    /usr/sbin/brctl stp $brname on
    /usr/sbin/brctl setfd $brname 0
    ifconfig $brname 192.168.58.1
    ifconfig $brname up
    iptables -t nat -A POSTROUTING -s 192.168.58.254/24 ! -d 192.168.58.254/24 -j MASQUERADE
    /etc/init.d/dnsmasq stop
    /etc/init.d/tftpd-hpa stop 2>/dev/null
    dnsmasq --strict-order --bind-interfaces --listen-address 192.168.58.1 --dhcp-range 192.168.58.2,192.168.58.254 $tftp_cmd
}

del_br()
{
    echo "cleanup bridge setup"
    kill -9 `pgrep dnsmasq|tail -1`
    ifconfig $brname down
    /usr/sbin/brctl delbr $brname
    iptables -t nat -D POSTROUTING -s 192.168.58.254/24 ! -d 192.168.58.254/24 -j MASQUERADE
}


del_br 2>/dev/null

if [[ $# > 0 ]];then
    if [[ $1 = 'tftp' ]];then
        tftp_cmd=" --enable-tftp --tftp-root $AUTODIR/tests/kvm/images/tftpboot --dhcp-boot pxelinux.0 --dhcp-no-override"
    fi
    add_br
fi
