from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, udp


class L2Switch(app_manager.RyuApp):
    """Learning switch. UDP traffic gets its own per-flow rule
    (src IP, dst IP, UDP dst port) so the switch keeps per-flow counters."""
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.mac_to_port = {}

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def features_handler(self, ev):
        dp = ev.msg.datapath
        p, ofp = dp.ofproto_parser, dp.ofproto
        match = p.OFPMatch()
        actions = [p.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions)

    def add_flow(self, dp, prio, match, actions, idle=0):
        p, ofp = dp.ofproto_parser, dp.ofproto
        inst = [p.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(p.OFPFlowMod(datapath=dp, priority=prio, match=match,
                                 instructions=inst, idle_timeout=idle))

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        p, ofp = dp.ofproto_parser, dp.ofproto
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth.ethertype == 0x88cc:          # ignore LLDP
            return
        ip = pkt.get_protocol(ipv4.ipv4)
        u = pkt.get_protocol(udp.udp)

        table = self.mac_to_port.setdefault(dp.id, {})
        table[eth.src] = in_port
        out = table.get(eth.dst, ofp.OFPP_FLOOD)
        actions = [p.OFPActionOutput(out)]

        if out != ofp.OFPP_FLOOD:
            if ip is not None and u is not None:
                match = p.OFPMatch(in_port=in_port, eth_type=0x0800, ip_proto=17,
                                   ipv4_src=ip.src, ipv4_dst=ip.dst, udp_dst=u.dst_port)
                self.add_flow(dp, 10, match, actions, idle=30)
            else:
                match = p.OFPMatch(in_port=in_port, eth_dst=eth.dst, eth_src=eth.src)
                self.add_flow(dp, 1, match, actions, idle=30)

        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(p.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                   in_port=in_port, actions=actions, data=data))
