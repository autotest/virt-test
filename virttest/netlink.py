import struct

STRUCT_NLMSGHDR = 'IHHII'

NETLINK_ROUTE = 0

#Core message type
        
NLMSG_NOOP, NLMSG_ERROR, NLMSG_DONE, NLMSG_OVERRUN = range(1, 5)
        
#Flags values
NLM_F_REQUEST = 0x001
NLM_F_ACK     = 0x004


RTM_NEWLINK, RTM_DELLINK, RTM_GETLINK, RTM_SETLINK = range(16, 20)
RTM_NEWADDR, RTM_DELADDR, RTM_GETADDR = range(20, 23)


AF_PACKET = 17

           
def netlink_pack(msgtype, flags, seq, pid, data):
    return struct.pack(STRUCT_NLMSGHDR, 16 + len(data),
                       msgtype, flags, seq, pid) + data

def netlink_unpack(data):
    out = []
    while data:
        length, msgtype, flags, seq, pid = struct.unpack(STRUCT_NLMSGHDR,
                                                         data[:16])
        if len(data) < length:
            raise RuntimeError("Buffer overrun!")
        out.append((msgtype, flags, seq, pid, data[16:length]))
        data = data[length:]

    return out


