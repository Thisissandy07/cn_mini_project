"""Polls every OpenFlow switch for flow and port statistics and logs the
network-side bandwidth to CSV. Run together with l2_switch.py:

    ryu-manager controller/l2_switch.py controller/stats_monitor.py
"""
import os
import time

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub

POLL = float(os.environ.get('POLL_INTERVAL', '1'))
FLOW_CSV = os.environ.get('SDN_FLOW_CSV', 'results/sdn_flows.csv')
PORT_CSV = os.environ.get('SDN_PORT_CSV', 'results/sdn_ports.csv')


def mget(match, key):
    """Read a field from an OFPMatch, None if the match does not have it."""
    try:
        return match[key]
    except Exception:
        return None


class StatsMonitor(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self.prev_flow = {}     # (dpid, src, dst, udp_dst) -> (bytes, pkts, duration)
        self.prev_port = {}     # (dpid, port) -> (rx_bytes, tx_bytes, wall_time)

        for path in (FLOW_CSV, PORT_CSV):
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        self.flow_f = open(FLOW_CSV, 'w')
        self.flow_f.write('epoch_s,dpid,ipv4_src,ipv4_dst,udp_dst,byte_count,packet_count,'
                          'duration_s,delta_bytes,delta_s,sdn_mbps,cum_mbps\n')
        self.port_f = open(PORT_CSV, 'w')
        self.port_f.write('epoch_s,dpid,port,rx_bytes,tx_bytes,rx_mbps,tx_mbps,'
                          'rx_dropped,tx_dropped\n')
        self.poller = hub.spawn(self._poll_loop)
        self.logger.info('stats monitor: polling every %.1fs -> %s, %s', POLL, FLOW_CSV, PORT_CSV)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(dp.id, None)

    def _poll_loop(self):
        while True:
            for dp in list(self.datapaths.values()):
                p, ofp = dp.ofproto_parser, dp.ofproto
                dp.send_msg(p.OFPFlowStatsRequest(dp))
                dp.send_msg(p.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY))
            hub.sleep(POLL)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_reply(self, ev):
        dpid = ev.msg.datapath.id
        now = time.time()
        for st in ev.msg.body:
            udp_dst = mget(st.match, 'udp_dst')
            if udp_dst is None:
                continue                       # only per-UDP-flow rules
            src = mget(st.match, 'ipv4_src')
            dst = mget(st.match, 'ipv4_dst')
            dur = st.duration_sec + st.duration_nsec / 1e9
            key = (dpid, src, dst, udp_dst)
            prev = self.prev_flow.get(key)
            if prev and st.byte_count >= prev[0] and dur > prev[2]:
                d_bytes = st.byte_count - prev[0]
                d_t = dur - prev[2]            # switch-side time between samples
            else:                              # first sample or rule was reinstalled
                d_bytes, d_t = st.byte_count, dur
            self.prev_flow[key] = (st.byte_count, st.packet_count, dur)
            mbps = d_bytes * 8.0 / d_t / 1e6 if d_t > 0 else 0.0
            cum = st.byte_count * 8.0 / dur / 1e6 if dur > 0 else 0.0
            self.flow_f.write('%.3f,%d,%s,%s,%d,%d,%d,%.3f,%d,%.3f,%.4f,%.4f\n' % (
                now, dpid, src, dst, udp_dst, st.byte_count, st.packet_count,
                dur, d_bytes, d_t, mbps, cum))
        self.flow_f.flush()

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_reply(self, ev):
        dpid = ev.msg.datapath.id
        now = time.time()
        for st in ev.msg.body:
            if st.port_no >= ofproto_v1_3.OFPP_MAX:
                continue                       # skip the LOCAL port
            key = (dpid, st.port_no)
            prev = self.prev_port.get(key)
            rx_m = tx_m = 0.0
            if prev and now > prev[2]:
                dt = now - prev[2]
                rx_m = max(st.rx_bytes - prev[0], 0) * 8.0 / dt / 1e6
                tx_m = max(st.tx_bytes - prev[1], 0) * 8.0 / dt / 1e6
            self.prev_port[key] = (st.rx_bytes, st.tx_bytes, now)
            self.port_f.write('%.3f,%d,%d,%d,%d,%.4f,%.4f,%d,%d\n' % (
                now, dpid, st.port_no, st.rx_bytes, st.tx_bytes, rx_m, tx_m,
                st.rx_dropped, st.tx_dropped))
        self.port_f.flush()
