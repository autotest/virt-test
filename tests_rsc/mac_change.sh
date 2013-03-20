#!/bin/bash

New_MAC_Addr=$1;
Old_MAC_Addr=$2;
IFACE=`ifconfig |grep -i $Old_MAC_Addr | awk '{print $1}'`

echo -e "New MAC address is: $New_MAC_Addr";
echo -e "Old MAC address is: $Old_MAC_Addr";
echo -e "Network Interface is: $IFACE";

echo -e "shutting down $IFACE...";
ifconfig $IFACE down;

echo -e "setting new mac_addr...";
ifconfig $IFACE hw ether $New_MAC_Addr;

echo -e "bring $IFACE up with new mac...";
ifconfig $IFACE up;

echo -e "stopping dhcp6c...";
killall dhcp6c;

echo -e "stopping dhclient...";
killall dhclient;

echo -e "starting dhcp6c...";
dhcp6c $IFACE;

echo -e "starting dhclient...";
dhclient $IFACE

echo
echo

ifconfig | grep -i $New_MAC_Addr
if [ $? -ne 0 ]
then
    echo "Failed to change MAC Address!"
    exit -1
fi

echo -e "Finished."

