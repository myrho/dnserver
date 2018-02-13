#!/usr/bin/env python3.6
import json
import logging
import os
import signal
import re
from socket import inet_aton
from datetime import datetime
from pathlib import Path
from textwrap import wrap
from time import sleep

from dnslib import DNSLabel, QTYPE, RR, dns
from dnslib.server import DNSServer, BaseResolver

from http.server import BaseHTTPRequestHandler, HTTPServer

SERIAL_NO = int((datetime.utcnow() - datetime(1970, 1, 1)).total_seconds())

handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
handler.setFormatter(logging.Formatter('%(asctime)s: %(message)s', datefmt='%H:%M:%S'))

logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

TYPE_LOOKUP = {
    'A': (dns.A, QTYPE.A),
    'AAAA': (dns.AAAA, QTYPE.AAAA),
    'CAA': (dns.CAA, QTYPE.CAA),
    'CNAME': (dns.CNAME, QTYPE.CNAME),
    'DNSKEY': (dns.DNSKEY, QTYPE.DNSKEY),
    'MX': (dns.MX, QTYPE.MX),
    'NAPTR': (dns.NAPTR, QTYPE.NAPTR),
    'NS': (dns.NS, QTYPE.NS),
    'PTR': (dns.PTR, QTYPE.PTR),
    'RRSIG': (dns.RRSIG, QTYPE.RRSIG),
    'SOA': (dns.SOA, QTYPE.SOA),
    'SRV': (dns.SRV, QTYPE.SRV),
    'TXT': (dns.TXT, QTYPE.TXT),
    'SPF': (dns.TXT, QTYPE.TXT),
}


class Record:
    def __init__(self, rname, rtype, args):
        self._rname = DNSLabel(rname)

        rd_cls, self._rtype = TYPE_LOOKUP[rtype]

        if self._rtype == QTYPE.SOA and len(args) == 2:
            # add sensible times to SOA
            args += (SERIAL_NO, 3600, 3600 * 3, 3600 * 24, 3600),

        if self._rtype == QTYPE.TXT and len(args) == 1 and isinstance(args[0], str) and len(args[0]) > 255:
            # wrap long TXT records as per dnslib's docs.
            args = wrap(args[0], 255),

        if self._rtype in (QTYPE.NS, QTYPE.SOA):
            ttl = 3600 * 24
        else:
            ttl = 300

        self.rr = RR(
            rname=self._rname,
            rtype=self._rtype,
            rdata=rd_cls(*args),
            ttl=ttl,
        )

    def set_ip(self, ip):
        if self._rtype == QTYPE.A:
            self.rr.rdata = dns.A(ip)

    def match_ip(self, ip):
        return self._rtype == QTYPE.A and str(self.rr.rdata).strip() == ip.strip()


    def match(self, q):
        return q.qname == self._rname and (q.qtype == QTYPE.ANY or q.qtype == self._rtype)

    def sub_match(self, q):
        return self._rtype == QTYPE.SOA and q.qname.matchSuffix(self._rname)

    def __str__(self):
        return str(self.rr)


class Resolver(BaseResolver):
    def __init__(self, zone_file, internal_zone_file):
        self.records = self.load_zones(zone_file)
        self.internal_records = self.load_zones(internal_zone_file)

    def zone_lines(self, zone_file):
        current_line = ''
        for line in zone_file.open():
            if line.startswith('#'):
                continue
            line = line.rstrip('\r\n\t ')
            if not line.startswith(' ') and current_line:
                yield current_line
                current_line = ''
            current_line += line.lstrip('\r\n\t ')
        if current_line:
            yield current_line

    def load_zones(self, zone_file):
        assert zone_file.exists(), f'zone files "{zone_file}" does not exist'
        logger.info('loading zone file "%s":', zone_file)
        zones = []
        for line in self.zone_lines(zone_file):
            try:
                rname, rtype, args_ = line.split(maxsplit=2)

                if args_.startswith('['):
                    args = tuple(json.loads(args_))
                else:
                    args = (args_,)
                record = Record(rname, rtype, args)
                zones.append(record)
                logger.info(' %2d: %s', len(zones), record)
            except Exception as e:
                raise RuntimeError(f'Error processing line ({e.__class__.__name__}: {e}) "{line.strip()}"') from e
        logger.info('%d zone resource records generated from zone file', len(zones))
        return zones

    def resolve(self, request, handler, client_ip):
        type_name = QTYPE[request.q.qtype]
        reply = request.reply()

        for record in self.records:
            if record.match_ip(client_ip):
                records = self.internal_records
                logger.debug("looking into internal records")
            else:
                records = self.records
                logger.debug("looking into external records")


        for record in records:
            if record.match(request.q):
                reply.add_answer(record.rr)

        if reply.rr:
            logger.info('found zone for %s[%s], %d replies', request.q.qname, type_name, len(reply.rr))
            return reply

        # no direct zone so look for an SOA record for a higher level zone
        for record in records:
            if record.sub_match(request.q):
                reply.add_answer(record.rr)

        if reply.rr:
            logger.info('found higher level SOA resource for %s[%s]', request.q.qname, type_name)
            return reply

        logger.info('no local zone found for %s[%s]', request.q.qname, type_name)
        return super().resolve(request, handler)

    def update(self, domain, external_ip, internal_ip=""):
        return self.updateRecords(self.records, domain, external_ip) and (internal_ip == "" or self.updateRecords(self.internal_records, domain, internal_ip))

    def updateRecords(self, records, domain, ip):
        for record in records:
            if record._rname == domain:
                logger.debug('updating %s', record._rname)
                record.set_ip(ip)
                return True
        logger.info('%s not found', domain)
        return False




def handle_sig(signum, frame):
    logger.info('pid=%d, got signal: %s, stopping...', os.getpid(), signal.Signals(signum).name)
    exit(0)

class WebServer(BaseHTTPRequestHandler):
    def is_ip(self, ip):
        # match matches from the beginning implicitly
        return re.match("(\d{1,3}\.){3}\d{1,3}", ip) != None

    def output(self, status, text):
        self.send_response(status)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(bytes(text, "utf-8"))
        return

    def do_POST(self):
        splits = self.path.split('/', 4)

        if len(splits) < 3:
            self.output(400, "missing parameters")
            return

        domain = splits[1]
        external_ip = splits[2]
        internal_ip = splits[3] if len(splits) == 4 else ""

        if not self.is_ip(external_ip) or internal_ip != "" and not self.is_ip(internal_ip):
            self.output(400, "invalid ip")
            return

        if resolver.update(domain, external_ip, internal_ip):
            self.output(200, "OK")
        else:
            self.output(404, "%s not found" % domain)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, handle_sig)

    port = int(os.getenv('PORT', 53))
    webPort = int(os.getenv('WEBPORT', 5000))
    zone_file = Path(os.getenv('ZONE_FILE', '/zones/zones.txt'))
    internal_zone_file = Path(os.getenv('INTERNAL_ZONE_FILE', '/zones/internal_zones.txt'))
    resolver = Resolver(zone_file, internal_zone_file)
    udp_server = DNSServer(resolver, port=port)
    tcp_server = DNSServer(resolver, port=port, tcp=True)

    logger.info('starting DNS server on port %d', port)
    udp_server.start_thread()
    tcp_server.start_thread()

    webServer = HTTPServer(("0.0.0.0", webPort), WebServer)
    logger.info('starting web server on port %d', webPort)

    try:
        webServer.serve_forever()
    except KeyboardInterrupt:
        pass
    webServer.server_close()
