#!/usr/bin/env python3
import argparse
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel

def run(bw, delay, loss):
    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink, autoSetMacs=True)
    net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)

    h1 = net.addHost('h1', ip='10.0.0.1/24')   # UDP client
    h2 = net.addHost('h2', ip='10.0.0.2/24')   # background traffic
    h3 = net.addHost('h3', ip='10.0.0.3/24')   # UDP server
    h4 = net.addHost('h4', ip='10.0.0.4/24')
    s1 = net.addSwitch('s1', protocols='OpenFlow13')
    s2 = net.addSwitch('s2', protocols='OpenFlow13')

    for h in (h1, h2):
        net.addLink(h, s1, bw=100)
    for h in (h3, h4):
        net.addLink(h, s2, bw=100)
    # bottleneck link: tc parameters apply here
    net.addLink(s1, s2, bw=bw, delay=delay, loss=loss)

    net.start()
    CLI(net)
    net.stop()

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--bw', type=float, default=10)       # Mbps
    p.add_argument('--delay', default='5ms')
    p.add_argument('--loss', type=float, default=0)      # percent
    a = p.parse_args()
    setLogLevel('info')
    run(a.bw, a.delay, a.loss)
