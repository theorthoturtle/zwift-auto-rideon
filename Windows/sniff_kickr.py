#!/usr/bin/env python3
"""
Records how a real Wi-Fi KICKR BIKE talks to Zwift, so Auto Ride On can copy it exactly.

It finds the bike on the network, connects to it the same way Zwift does, repeats
Zwift's controller handshake, and logs everything the bike sends back -- including
the exact messages for each button you press. Nothing is written to the trainer
(no resistance, ERG or gear changes).

Run it (Record KICKR Buttons.bat on Windows, .command on a Mac) and follow the on-screen prompts (hold Ride On, tap it, shift up/down).
The log is saved as sniff_kickr.log.
"""
import os
import socket
import struct
import sys
import time
import uuid as uuidlib

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SERVICE_TYPE = "_wahoo-fitness-tnp._tcp.local."
FC82 = uuidlib.UUID("0000fc82-0000-1000-8000-00805f9b34fb")
ASYNC_CHAR = uuidlib.UUID("00000002-19ca-4651-86e5-fa29dcdd09d1")
SYNC_RX_CHAR = uuidlib.UUID("00000003-19ca-4651-86e5-fa29dcdd09d1")
SYNC_TX_CHAR = uuidlib.UUID("00000004-19ca-4651-86e5-fa29dcdd09d1")
NAMES = {ASYNC_CHAR: "ASYNC(buttons)", SYNC_RX_CHAR: "SYNC_RX", SYNC_TX_CHAR: "SYNC_TX"}

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sniff_kickr.log")
LOG = None                     # opened by main()


def log(*a, console=None):
    line = " ".join(str(x) for x in (time.strftime("%H:%M:%S") + f".{int(time.time()*1000)%1000:03d}",) + a)
    raw = line.split(" ", 1)[1].lstrip().startswith(("->", "<-"))
    if console if console is not None else not raw:
        print(line, flush=True)
    if LOG:
        LOG.write(line + "\n")
        LOG.flush()


class Found(ServiceListener):
    def __init__(self):
        self.devices = {}

    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name, timeout=3000)
        if info:
            self.devices[name] = info

    update_service = add_service

    def remove_service(self, *a):
        pass


def local_ips():
    ips = {"127.0.0.1"}
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.connect(("10.255.255.255", 1))
        ips.add(u.getsockname()[0])
        u.close()
    except OSError:
        pass
    return ips


def find_bike(wait=6):
    zc = Zeroconf()
    found = Found()
    ServiceBrowser(zc, SERVICE_TYPE, found)
    time.sleep(wait)
    zc.close()
    bikes = []
    for name, info in found.devices.items():
        props = {k.decode(errors="replace"): (v or b"").decode(errors="replace")
                 for k, v in (info.properties or {}).items()}
        addrs = [socket.inet_ntoa(a) for a in info.addresses if len(a) == 4]
        log("Found on network:", name.split("._")[0], addrs, console=True)
        log("   details:", info.port, props, console=False)
        if not addrs or addrs[0] in local_ips():
            continue  # skip Auto Ride On's own fake controller running on this PC
        has_controller = "FC82" in props.get("ble-service-uuids", "").upper()
        bikes.append((name, addrs[0], info.port, has_controller))
    # devices with the Zwift controller service first, KICKR BIKEs before plain trainers
    bikes.sort(key=lambda b: (not b[3], "BIKE" not in b[0].upper()))
    return bikes


def choose(bikes):
    """Pick the device to record; asks when there's more than one."""
    if len(bikes) == 1:
        return bikes[0]
    print()
    for i, (name, ip, _, ctl) in enumerate(bikes, 1):
        print(f"  {i}) {name.split('._')[0]}  ({ip}){'' if ctl else '  - no controller service'}")
    try:
        pick = input(f"Which one? [1-{len(bikes)}, Enter = 1]: ").strip()
        return bikes[int(pick) - 1] if pick else bikes[0]
    except (ValueError, IndexError, EOFError):
        return bikes[0]


class DirCon:
    def __init__(self, ip, port):
        self.s = socket.create_connection((ip, port), timeout=5)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.seq = 0
        self.buf = b""

    def send(self, msg_id, body=b""):
        pkt = struct.pack(">BBBBH", 1, msg_id, self.seq & 0xFF, 0, len(body)) + body
        self.seq += 1
        log("  ->", pkt.hex(" "))
        self.s.sendall(pkt)

    def recv_one(self, timeout):
        self.s.settimeout(timeout)
        end = time.time() + timeout
        while True:
            if len(self.buf) >= 6:
                ln = struct.unpack(">H", self.buf[4:6])[0]
                if len(self.buf) >= 6 + ln:
                    pkt, self.buf = self.buf[:6 + ln], self.buf[6 + ln:]
                    return pkt
            left = end - time.time()
            if left <= 0:
                return None
            self.s.settimeout(left)
            try:
                chunk = self.s.recv(4096)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("bike closed the connection")
            self.buf += chunk

    def request(self, msg_id, body=b"", timeout=3):
        self.send(msg_id, body)
        end = time.time() + timeout
        while time.time() < end:
            pkt = self.recv_one(end - time.time())
            if pkt is None:
                break
            self.show(pkt)
            if pkt[1] == msg_id:
                return pkt
        return None

    def show(self, pkt):
        msg_id, rc = pkt[1], pkt[3]
        body = pkt[6:]
        if msg_id == 0x06 and len(body) >= 16:
            ch = uuidlib.UUID(bytes=body[:16])
            data = body[16:]
            extra = ""
            if ch == ASYNC_CHAR and data[:1] == b"\x23":
                extra = "  " + describe_buttons(data)
            log("  <- NOTIFY", NAMES.get(ch, str(ch)[:8]), data.hex(" "), extra)
        else:
            log("  <-", pkt.hex(" "), f"(rc={rc})" if rc else "")


BUTTONS = {0x1: "LEFT", 0x2: "UP", 0x4: "RIGHT", 0x8: "DOWN", 0x10: "A", 0x20: "B", 0x40: "Y",
           0x80: "Z/RIDE-ON", 0x100: "SHIFT_UP_L", 0x200: "SHIFT_DN_L", 0x400: "POWERUP_L",
           0x1000: "SHIFT_UP_R", 0x2000: "SHIFT_DN_R", 0x4000: "POWERUP_R"}


def is_trainer_heartbeat(pkt):
    # the 1-per-second trainer status message; recorded once, then skipped to keep the log readable
    body = pkt[6:]
    if pkt[1] == 0x06 and body[:16] == ASYNC_CHAR.bytes and body[16:17] == b"\x03":
        global _hb_seen
        if not _hb_seen:
            _hb_seen = True
            return False
        return True
    return False


_hb_seen = False


def describe_buttons(data):
    try:
        if data[1] != 0x08:
            return "(unknown layout)"
        val = shift = 0
        i = 2
        while True:
            b = data[i]
            i += 1
            val |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
        pressed = [n for m, n in BUTTONS.items() if not val & m]
        return "pressed: " + (", ".join(pressed) if pressed else "none")
    except IndexError:
        return ""


def main():
    global LOG
    LOG = open(LOG_PATH, "w", encoding="utf-8")
    log("Looking for the bike on the network...")
    bikes = find_bike()
    if not bikes:
        log("No KICKR found. Make sure it's on and on the same network, then try again.")
        return
    name, ip, port, _ = choose(bikes)
    log(f"Connecting to {name} at {ip}:{port}")
    d = DirCon(ip, port)

    r = d.request(0x01)
    services = [uuidlib.UUID(bytes=r[6 + i:6 + i + 16]) for i in range(0, len(r) - 6, 16)] if r else []
    log("Services:", [str(s) for s in services], console=False)
    notifiable = []
    for svc in services:
        rr = d.request(0x02, svc.bytes)
        if not rr:
            continue
        body = rr[6 + 16:]
        for i in range(0, len(body) - 16, 17):
            ch = uuidlib.UUID(bytes=body[i:i + 16])
            props = body[i + 16]
            if props & 0x04:
                notifiable.append(ch)

    log("Listening on", len(notifiable), "channels", console=True)
    log("   channels:", [str(c)[:8] for c in notifiable], console=False)
    for ch in notifiable:
        d.request(0x05, ch.bytes + b"\x01")
    log("Sending Zwift's handshake and info requests...")
    d.request(0x04, SYNC_RX_CHAR.bytes + b"RideOn\x02\x04")
    time.sleep(0.5)
    d.request(0x04, SYNC_RX_CHAR.bytes + b"\x00\x08\x00")
    time.sleep(0.5)
    d.request(0x04, SYNC_RX_CHAR.bytes + b"\x00\x08\x10")
    time.sleep(1)
    log("Asking for the extra settings Zwift requests from a controller...")
    for cmd in ("44 20 01", "44 08 01", "41 08 05", "00 08 80 0a", "00 08 80 08", "00 08 83 06"):
        log("  Zwift-style request:", cmd, console=False)
        d.request(0x04, SYNC_RX_CHAR.bytes + bytes.fromhex(cmd))
        answers = []
        end = time.time() + 0.8
        while time.time() < end:
            pkt = d.recv_one(0.2)
            if pkt and not is_trainer_heartbeat(pkt):
                d.show(pkt)
                body = pkt[6:]
                if pkt[1] == 0x06 and body[:16] == SYNC_TX_CHAR.bytes:
                    answers.append(body[16:].hex(" "))
        print(f"  Asked {cmd:<12} -> bike answered: {' | '.join(answers) if answers else '(nothing)'}", flush=True)

    steps = [("Listening (no need to press anything)...", 6)]
    try:
        for msg, secs in steps:
            log(msg)
            end = time.time() + secs
            while time.time() < end:
                pkt = d.recv_one(min(0.5, max(0.05, end - time.time())))
                if pkt and not is_trainer_heartbeat(pkt):
                    d.show(pkt)
    except KeyboardInterrupt:
        pass
    log("Done. Full log saved to", LOG_PATH, console=True)
    try:   # open the log so it can be scrolled
        if os.name == "nt":
            os.startfile(LOG_PATH)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", "-t", LOG_PATH], check=False)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("ERROR:", repr(e))
    if os.name == "nt":
        input("Press Enter to close...")
