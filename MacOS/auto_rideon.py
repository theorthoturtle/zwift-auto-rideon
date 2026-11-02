#!/usr/bin/env python3
"""
Zwift Auto Ride On - virtual controller.

Shows up in Zwift's Controls pairing screen as a Wi-Fi (DirCon) KICKR BIKE PRO controller,
then holds its Z / Ride On button for 3 s at a random time every 8-10 s, but only while
you're in a ride, moving or stopped (checked through Sauce for Zwift's local web API).
If Sauce isn't running, it presses whenever Zwift is connected.

The 8-10 s gap is counted from the end of one hold to the start of the next.

Usage:   python3 auto_rideon.py            (Ctrl-C to quit)
Options: --min 8 --max 10 --hold 3 --sauce http://127.0.0.1:1080 --no-sauce --verbose
"""
import argparse
import asyncio
import http.client
import json
import os
import random
import socket
import struct
import sys
import threading
import time
import urllib.parse
import uuid as uuidlib

from zeroconf import IPVersion, ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "auto_rideon.log")
IDENTITY_FILE = os.path.join(HERE, "identity.json")
SETTINGS_FILE = os.path.join(HERE, "gui_settings.txt")

DIRCON_PORT = 36866        # Zwift connects here
CONTROL_PORT = 36867       # the corner window talks to the app here (local only)


# =============================================================== protocol ==
def _varint(n):
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        if not n:
            out.append(b)
            return bytes(out)
        out.append(b | 0x80)


def pb_varint(field, value):
    return _varint(field << 3) + _varint(value)


def pb_bytes(field, data):
    data = data.encode() if isinstance(data, str) else data
    return _varint((field << 3) | 2) + _varint(len(data)) + data


def pb_read_varint(buf, i):
    shift = val = 0
    while True:
        b = buf[i]
        i += 1
        val |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return val, i


RIDE_SERVICE = uuidlib.UUID("0000fc82-0000-1000-8000-00805f9b34fb")   # Zwift Ride / KICKR BIKE controller
ASYNC_CHAR = uuidlib.UUID("00000002-19ca-4651-86e5-fa29dcdd09d1")     # buttons + heartbeat -> Zwift
SYNC_RX_CHAR = uuidlib.UUID("00000003-19ca-4651-86e5-fa29dcdd09d1")   # Zwift -> controller
SYNC_TX_CHAR = uuidlib.UUID("00000004-19ca-4651-86e5-fa29dcdd09d1")   # controller -> Zwift
PROP_WRITE, PROP_NOTIFY = 0x02, 0x04
CHARS = {SYNC_RX_CHAR: PROP_WRITE, ASYNC_CHAR: PROP_NOTIFY, SYNC_TX_CHAR: PROP_NOTIFY}

# DirCon message ids / result codes
MSG_DISCOVER_SERVICES, MSG_DISCOVER_CHARS, MSG_READ, MSG_WRITE, MSG_ENABLE_NOTIFY, MSG_NOTIFICATION = 1, 2, 3, 4, 5, 6
RC_OK, RC_UNKNOWN_MSG, RC_SERVICE_NOT_FOUND, RC_CHAR_NOT_FOUND = 0, 1, 3, 4

# Zwift controller protocol (opcodes / replies copied from a real KICKR BIKE PRO, see sniff_kickr.py)
RIDE_ON_HANDSHAKE = b"RideOn"
HANDSHAKE_REPLY = b"RideOn\x02\x03"
OP_GET, OP_GET_RESPONSE, OP_STATUS_RESPONSE = 0x00, 0x3C, 0x3E
SET_STATUS = {0x44: 0, 0x41: 1}            # "set" commands: 0 = OK, 1 = not supported
RAW_GET_RESPONSES = {
    16: "3c 08 10 12 00",                                   # client/server config: empty
    1280: "3c 08 80 0a 12 03 0a 01 05",                     # sensor relay page
    1024: ("3c 08 80 08 12 1d 08 d8 01 10 03 1a 0a 08 01 10 ff ff 03 18 fe ff 03"
           " 1a 0a 08 02 10 ff ff 03 18 fe ff 03"),         # controller input config (incl. Z button)
    771: "3c 08 83 06",                                     # battery state: no data
}


def button_state(pressed_mask=0):
    # RideKeyPadStatus protobuf, field 1 (buttonMap); bits are active-low.
    return bytes([0x23, 0x08]) + _varint((~pressed_mask) & 0xFFFFFFFF)


PADDLES = bytes.fromhex("1a 04 08 00 10 00 1a 04 08 01 10 00")   # two analog paddles at rest
RELEASED = button_state(0)
RELEASED_FULL = RELEASED + PADDLES
Z_PRESSED = button_state(0x80) + PADDLES                         # Z button = Ride On
TRAINER_HEARTBEAT = bytes.fromhex("03 08 00 10 00 18 00 20 00 28 00 30 00")
BUTTON_INTERVAL = 0.1          # the bike repeats the button state every 100 ms while held
RELEASE_REPEATS = 8            # then ~8 "released" frames, one short one, then silence


def notification(char, data):
    """A complete DirCon notification packet (built once, sent to every connection)."""
    body = char.bytes + data
    return struct.pack(">BBBBH", 1, MSG_NOTIFICATION, 0, RC_OK, len(body)) + body


PKT_HEARTBEAT = notification(ASYNC_CHAR, TRAINER_HEARTBEAT)
PKT_PRESSED = notification(ASYNC_CHAR, Z_PRESSED)
PKT_RELEASED_FULL = notification(ASYNC_CHAR, RELEASED_FULL)
PKT_RELEASED = notification(ASYNC_CHAR, RELEASED)


# =============================================================== identity ==
class Identity:
    """This install's own serial, ID, network address and name: created once on first run and
    saved in identity.json, so every copy of the app looks like a different bike to Zwift."""

    def __init__(self):
        try:
            with open(IDENTITY_FILE, encoding="utf-8") as f:
                d = json.load(f)
            assert all(k in d for k in ("serial", "uid", "mac", "suffix"))
        except Exception:
            rnd = random.SystemRandom()
            hexs = lambda n: "".join(rnd.choice("0123456789ABCDEF") for _ in range(n))  # noqa: E731
            d = {"serial": "3225" + "".join(rnd.choice("0123456789") for _ in range(7)),
                 "uid": hexs(12),
                 "mac": "B4:6F:2D:" + ":".join(hexs(2) for _ in range(3)),
                 "suffix": hexs(4)}
            try:
                with open(IDENTITY_FILE, "w", encoding="utf-8") as f:
                    json.dump(d, f, indent=2)
            except OSError:
                pass
        self.serial = d["serial"][:11].ljust(11, "0")
        self.uid = d["uid"]
        self.mac = d["mac"]
        self.name = f"KICKR BIKE PRO {d['suffix']}"

    def dev_info_responses(self):
        """GET data object 0: two pages, in the same layout the real bike uses."""
        caps = b"".join(pb_bytes(8, pb_varint(1, t) + pb_varint(2, c))
                        for t, c in ((1, 0xA6), (2, 0), (8, 1), (4, 0)))
        part1 = (pb_varint(1, 0x203) + pb_bytes(2, bytes([0x1C, 0x00, 0x03, 0x03]))
                 + pb_bytes(3, "KICKR BIKE P") + pb_bytes(6, self.serial + "\x00" * 4) + caps)
        part2 = pb_bytes(7, "30") + pb_varint(9, 2) + pb_varint(10, 0x20) + pb_bytes(11, self.uid)
        return [bytes([OP_GET_RESPONSE]) + pb_varint(1, 0) + pb_bytes(2, pb_bytes(1, p)) for p in (part1, part2)]


def get_responses(identity, obj_id):
    if obj_id == 0:
        return identity.dev_info_responses()
    if obj_id in RAW_GET_RESPONSES:
        return [bytes.fromhex(RAW_GET_RESPONSES[obj_id])]
    return [bytes([OP_GET_RESPONSE]) + pb_varint(1, obj_id) + pb_bytes(2, b"")]


# ================================================================ logging ==
LOG_MAX_BYTES = 2_000_000      # start a fresh log (keeping the previous one) past ~2 MB
VERBOSE = False                # --verbose: also log every message to/from Zwift


class Log:
    def __init__(self):
        self.f = None
        self.lock = threading.Lock()

    def open(self):
        self.f = open(LOG_PATH, "w", encoding="utf-8")
        self.last_flush = time.monotonic()

    def write(self, line, flush):
        with self.lock:
            if self.f is None:
                return
            self.f.write(line + "\n")
            now = time.monotonic()
            if flush or now - self.last_flush > 2:     # batch the chatty lines, flush the important ones
                self.f.flush()
                self.last_flush = now
                if self.f.tell() > LOG_MAX_BYTES:
                    self.f.close()
                    os.replace(LOG_PATH, LOG_PATH + ".old")
                    self.f = open(LOG_PATH, "w", encoding="utf-8")


_LOG = Log()

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(*parts, console=True):
    line = time.strftime("%H:%M:%S ") + " ".join(str(p) for p in parts)
    if (console or VERBOSE) and sys.stdout:
        try:
            print(line, flush=True)
        except Exception:
            pass
    _LOG.write(line, flush=console)


def trace(*parts):
    """Raw protocol traffic: only recorded with --verbose."""
    if VERBOSE:
        log(*parts, console=False)


# ================================================================= status ==
class Status:
    """Shared state the corner window reads and controls."""

    def __init__(self):
        self.enabled = True           # False = stay connected but don't send Ride Ons
        self.sent = 0                 # presses
        self.next_at = 0.0
        self.pressing = False
        self.in_ride = None           # True / False / None (Sauce not reachable)
        self.controller = None
        self.error = None
        self.reached = 0              # estimated riders reached this session
        self.last_reached = None      # riders reached by the most recent press
        self.given = set()            # riders counted this ride (one Ride On per rider per ride)
        self.not_in_ride_since = None

    @property
    def connected(self):
        return bool(self.controller and self.controller.connected)

    def as_dict(self):
        return {"enabled": self.enabled, "connected": self.connected, "sent": self.sent,
                "reached": self.reached, "estimate": True, "last_reached": self.last_reached,
                "pressing": self.pressing, "in_ride": self.in_ride,
                "next_in": max(0.0, self.next_at - time.time()), "error": self.error}


STATUS = Status()


# ========================================================== DirCon server ==
class Session:
    """One TCP connection from Zwift (it may hold several at once)."""
    _ids = 0

    def __init__(self, writer):
        Session._ids += 1
        self.id = Session._ids
        self.writer = writer
        self.ready = False            # handshake done
        self.peer = (writer.get_extra_info("peername") or ("?",))[0]

    def send(self, msg_id, seq, rc, body=b""):
        pkt = struct.pack(">BBBBH", 1, msg_id, seq, rc, len(body)) + body
        self.writer.write(pkt)
        trace(f"  [{self.id}] ->", pkt.hex(" "))

    def notify(self, char, data):
        self.send(MSG_NOTIFICATION, 0, RC_OK, char.bytes + data)


class Controller:
    def __init__(self, identity, hold_seconds=3.0):
        self.identity = identity
        self.sessions = set()
        self.hold_seconds = hold_seconds
        self.was_connected = False

    @property
    def connected(self):
        return any(s.ready for s in self.sessions)

    async def broadcast(self, pkt):
        """Send one prebuilt packet to every connected Zwift session."""
        for s in [s for s in self.sessions if s.ready]:
            try:
                s.writer.write(pkt)
                await s.writer.drain()
            except (ConnectionError, OSError) as e:
                log(f"[{s.id}] send failed: {e}", console=False)

    async def handle(self, reader, writer):
        sock = writer.get_extra_info("socket")
        if sock is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except OSError:
                pass
        s = Session(writer)
        self.sessions.add(s)
        log(f"[{s.id}] Zwift opened a connection from {s.peer} ({len(self.sessions)} open)", console=False)
        reason = "closed by Zwift"
        try:
            while True:
                hdr = await reader.readexactly(6)
                _ver, msg_id, seq, _rc, length = struct.unpack(">BBBBH", hdr)
                body = await reader.readexactly(length) if length else b""
                trace(f"  [{s.id}] <-", (hdr + body).hex(" "))
                await self.dispatch(s, msg_id, seq, body)
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        except (ConnectionError, OSError) as e:
            reason = f"error: {e}"
        finally:
            self.sessions.discard(s)
            log(f"[{s.id}] connection ended ({reason}); {len(self.sessions)} still open", console=False)
            writer.close()
            self.report()

    def report(self):
        now = self.connected
        if now != self.was_connected:
            log("Connected to Zwift - controller ready" if now else "Lost connection to Zwift (it usually reconnects)")
            self.was_connected = now

    async def dispatch(self, s, msg_id, seq, body):
        uid = body[:16]
        if msg_id == MSG_DISCOVER_SERVICES:
            s.send(msg_id, seq, RC_OK, RIDE_SERVICE.bytes)
        elif msg_id == MSG_DISCOVER_CHARS:
            if uid != RIDE_SERVICE.bytes:
                return s.send(msg_id, seq, RC_SERVICE_NOT_FOUND, uid)
            s.send(msg_id, seq, RC_OK, uid + b"".join(c.bytes + bytes([p]) for c, p in CHARS.items()))
        elif msg_id == MSG_READ:
            s.send(msg_id, seq, RC_OK, uid)
        elif msg_id == MSG_ENABLE_NOTIFY:
            ok = len(uid) == 16 and uuidlib.UUID(bytes=uid) in CHARS
            s.send(msg_id, seq, RC_OK if ok else RC_CHAR_NOT_FOUND, uid)
        elif msg_id == MSG_WRITE:
            s.send(msg_id, seq, RC_OK, uid)
            if uid == SYNC_RX_CHAR.bytes:
                await self.on_command(s, body[16:])
        else:
            log(f"[{s.id}] unknown DirCon message {msg_id}", console=False)
            s.send(msg_id, seq, RC_UNKNOWN_MSG)

    async def on_command(self, s, data):
        if data.startswith(RIDE_ON_HANDSHAKE):
            s.notify(SYNC_TX_CHAR, HANDSHAKE_REPLY)
            s.ready = True
            s.notify(ASYNC_CHAR, TRAINER_HEARTBEAT)
            self.report()
        elif data[:1] == bytes([OP_GET]) and len(data) > 1:
            try:
                tag, i = pb_read_varint(data, 1)
                obj_id = pb_read_varint(data, i)[0] if tag == 0x08 else 0
            except IndexError:
                obj_id = 0
            for msg in get_responses(self.identity, obj_id):
                s.notify(SYNC_TX_CHAR, msg)
                await s.writer.drain()
                await asyncio.sleep(0.02)
            log(f"[{s.id}] answered GET {obj_id}", console=False)
        elif data and data[0] in SET_STATUS:
            s.notify(SYNC_TX_CHAR, bytes([OP_STATUS_RESPONSE]) + pb_varint(1, data[0])
                     + pb_varint(2, SET_STATUS[data[0]]))
        else:
            log(f"[{s.id}] unhandled command {data.hex(' ')}", console=False)

    async def press_ride_on(self):
        """Hold Z the way the real bike reports it: pressed frame every 100 ms, then release."""
        try:
            end = time.monotonic() + self.hold_seconds
            while time.monotonic() < end:
                await self.broadcast(PKT_PRESSED)
                await asyncio.sleep(BUTTON_INTERVAL)
        finally:
            for _ in range(RELEASE_REPEATS):
                await self.broadcast(PKT_RELEASED_FULL)
                await asyncio.sleep(BUTTON_INTERVAL)
            await self.broadcast(PKT_RELEASED)

    async def keepalive(self):
        # Like the bike: no button frames while idle, just a trainer status message once a second.
        while True:
            await asyncio.sleep(1)
            await self.broadcast(PKT_HEARTBEAT)


# ================================================================== Sauce ==
class Sauce:
    """Small client for Sauce for Zwift's local web API. Reuses one HTTP connection per thread."""

    def __init__(self, base):
        u = urllib.parse.urlparse(base)
        self.host, self.port = u.hostname or "127.0.0.1", u.port or 80
        self.local = threading.local()

    def get(self, path, timeout=2.0):
        for attempt in (1, 2):                      # retry once on a stale kept-alive connection
            conn = getattr(self.local, "conn", None)
            if conn is None:
                conn = self.local.conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
            try:
                conn.request("GET", path)
                r = conn.getresponse()
                data = r.read()
                return json.loads(data) if r.status == 200 else None
            except (OSError, http.client.HTTPException, ValueError):
                conn.close()
                self.local.conn = None
        return None

    def in_ride(self):
        """True if Sauce has live ride data for you (moving or stopped), False if not, None if unreachable."""
        ad = self.get("/api/athlete/v1/self", timeout=1.5)
        if ad is None:
            return None
        if not ad.get("state"):
            return False
        age = ad.get("age")
        if age is None and ad.get("updated"):
            age = time.time() * 1000 - ad["updated"]
        return age is not None and age < 5000

    def nearby_rideons(self):
        """{athleteId: (Ride Ons received, |gap s|)} for nearby riders (not you), or None."""
        data = self.get("/api/nearby/v2?resource=state")
        if not isinstance(data, list):
            return None
        out = {}
        for x in data:
            aid, st = x.get("athleteId"), x.get("state") or {}
            if aid and not x.get("self") and isinstance(st.get("rideons"), int):
                gap = x.get("gap")
                out[aid] = (st["rideons"], abs(gap) if isinstance(gap, (int, float)) else 9999)
        return out


# ================================================ counting riders reached ==
# Zwift doesn't tell Sauce who receives your Ride Ons, so this watches nearby riders' Ride On
# totals. A bomb lands on all its riders at once, so it counts the burst of increases right when
# yours fires, subtracts the Ride Ons other people would give in that time anyway, caps it at 5,
# and skips riders already counted this ride.
MAX_PER_PRESS = 5
SAMPLE_EVERY = 0.5             # seconds between samples of nearby riders
WINDOW_START, WINDOW_END = 2.5, 7.0   # seconds after the press starts when your Ride Ons show up
BURST = 2.5                    # a bomb's Ride Ons land within this many seconds of each other
NEW_RIDE_AFTER = 120           # out of a ride this long = the next ride starts a fresh list


class RideOnWatcher:
    def __init__(self, sauce):
        self.sauce = sauce
        self.last = None             # latest {aid: (count, gap)}
        self.events = []             # (time, aid, gap) whenever a rider's total went up
        self.quiet_time = 0.0        # seconds observed outside press windows...
        self.quiet_events = 0        # ...and increases seen in them
        self.busy_until = 0.0
        self.rate = 0.3              # learned: other people's Ride Ons per second

    async def run(self):
        prev_t = None
        while True:
            snap = await asyncio.to_thread(self.sauce.nearby_rideons)
            t = time.time()
            if snap is None:
                self.last = prev_t = None
            else:
                ups = 0
                if self.last is not None:
                    for aid, (n, gap) in snap.items():
                        old = self.last.get(aid)
                        if old is not None and n > old[0]:
                            self.events.append((t, aid, gap))
                            ups += aid not in STATUS.given
                if prev_t is not None and t > self.busy_until:
                    self.quiet_time += t - prev_t
                    self.quiet_events += ups
                    if self.quiet_time >= 30:
                        self.rate = 0.7 * self.rate + 0.3 * self.quiet_events / self.quiet_time
                        self.quiet_time, self.quiet_events = 0.0, 0
                self.last, prev_t = snap, t
                if self.events and t - self.events[0][0] > 120:
                    self.events = [e for e in self.events if t - e[0] < 120]
            await asyncio.sleep(SAMPLE_EVERY)

    def mark_press(self, start):
        self.busy_until = max(self.busy_until, start + WINDOW_END + 1)

    def measure(self, start):
        """(riders this press reached, log detail)."""
        first = {}
        for t, aid, gap in self.events:
            if start + WINDOW_START <= t <= start + WINDOW_END and aid not in first and aid not in STATUS.given:
                first[aid] = (t, gap)
        cands = sorted((t, gap, aid) for aid, (t, gap) in first.items())
        best, j = [], 0
        for i in range(len(cands)):               # largest group within BURST seconds (two pointers)
            while cands[i][0] - cands[j][0] > BURST:
                j += 1
            if i - j + 1 > len(best):
                best = cands[j:i + 1]
        noise = self.rate * BURST
        n = max(0, min(MAX_PER_PRESS, round(len(best) - noise)))
        chosen = [aid for _, _, aid in sorted(best, key=lambda c: c[1])[:n]]   # closest riders first
        offsets = " ".join(f"{t - start:.1f}" for t, _, _ in cands)
        return chosen, f"burst {len(best)}, expected noise {noise:.1f}, increases at +s: [{offsets}]"

    async def measure_later(self, start):
        await asyncio.sleep(max(0.0, start + WINDOW_END + SAMPLE_EVERY - time.time()))
        if self.last is None:
            STATUS.last_reached = None
            return log("Press reached ? rider(s) [Sauce not available]")
        chosen, detail = self.measure(start)
        STATUS.given.update(chosen)
        STATUS.reached += len(chosen)
        STATUS.last_reached = len(chosen)
        log(f"Press reached {len(chosen)} new rider(s)  [{detail}; already counted this ride: {len(STATUS.given)}]")


def note_ride_state(in_ride):
    """Track whether you're in a ride; start a fresh 'already counted' list on a new ride."""
    STATUS.in_ride = in_ride
    now = time.time()
    if in_ride is False:
        STATUS.not_in_ride_since = STATUS.not_in_ride_since or now
    elif in_ride:
        if STATUS.not_in_ride_since and now - STATUS.not_in_ride_since >= NEW_RIDE_AFTER and STATUS.given:
            log(f"New ride - clearing the list of {len(STATUS.given)} riders already counted")
            STATUS.given.clear()
        STATUS.not_in_ride_since = None


async def ride_watch(sauce):
    """Keeps the in-ride state current (also while paused)."""
    while True:
        note_ride_state(await asyncio.to_thread(sauce.in_ride))
        await asyncio.sleep(10)


_background = set()           # keeps running background tasks referenced until they finish


def run_in_background(coro):
    task = asyncio.ensure_future(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def ride_on_loop(ctl, args, sauce, watcher):
    while True:
        delay = random.uniform(args.min, args.max)
        STATUS.next_at = time.time() + delay
        await asyncio.sleep(delay)
        if not STATUS.enabled or not ctl.connected:
            continue
        if sauce:
            note_ride_state(await asyncio.to_thread(sauce.in_ride))
            if STATUS.in_ride is False or not STATUS.enabled:
                continue
        log("Pressing Ride On...")
        STATUS.pressing = True
        start = time.time()
        if watcher:
            watcher.mark_press(start)
        try:
            await ctl.press_ride_on()
            STATUS.sent += 1
            log(f"Ride On button held {ctl.hold_seconds:g}s ({STATUS.sent})")
            if watcher:
                run_in_background(watcher.measure_later(start))
        except ConnectionError as e:
            log("Send failed:", e)
        finally:
            STATUS.pressing = False


# ========================================================= window control ==
def load_enabled():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return f.read().strip() != "off"
    except OSError:
        return True


def save_enabled(on):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            f.write("on" if on else "off")
    except OSError:
        pass


class ControlServer:
    """Local JSON-lines server for the corner window. Each window request is also its heartbeat."""

    def __init__(self):
        self.gui_seen = 0.0
        self.on_quit = None          # set by the supervisor (auto_rideon_app.pyw)
        self.on_show = None

    async def handle(self, reader, writer):
        try:
            while line := await reader.readline():
                try:
                    req = json.loads(line)
                except ValueError:
                    continue
                if req.get("from") == "gui":
                    self.gui_seen = time.time()
                cmd = req.get("cmd")
                if cmd == "set_enabled":
                    STATUS.enabled = bool(req.get("on"))
                    save_enabled(STATUS.enabled)
                    log("Ride Ons turned " + ("ON" if STATUS.enabled else "OFF") + " from the window")
                elif cmd == "quit" and self.on_quit:
                    self.on_quit()
                elif cmd == "show" and self.on_show:
                    self.on_show()
                writer.write((json.dumps(STATUS.as_dict()) + "\n").encode())
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()


CONTROL = ControlServer()


# =================================================================== main ==
def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


async def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min", type=float, default=8, help="shortest wait between Ride Ons (s)")
    ap.add_argument("--max", type=float, default=10, help="longest wait between Ride Ons (s)")
    ap.add_argument("--hold", type=float, default=3.0, help="seconds to hold the button")
    ap.add_argument("--sauce", default="http://127.0.0.1:1080", help="Sauce for Zwift web server URL")
    ap.add_argument("--no-sauce", action="store_true", help="press whenever connected, without checking Sauce")
    ap.add_argument("--verbose", action="store_true", help="log every message to and from Zwift")
    args = ap.parse_args(argv)

    global VERBOSE
    VERBOSE = args.verbose
    _LOG.open()
    identity = Identity()
    log(f"Full log: {LOG_PATH}")
    log(f"This install's identity: {identity.name}, serial {identity.serial}, ID {identity.uid}", console=False)

    ctl = Controller(identity, hold_seconds=args.hold)
    STATUS.controller = ctl
    server = await asyncio.start_server(ctl.handle, "0.0.0.0", DIRCON_PORT)
    control = await asyncio.start_server(CONTROL.handle, "127.0.0.1", CONTROL_PORT)

    ip = local_ip()
    info = ServiceInfo(
        "_wahoo-fitness-tnp._tcp.local.",
        f"{identity.name}._wahoo-fitness-tnp._tcp.local.",
        addresses=[socket.inet_aton(ip)],
        port=DIRCON_PORT,
        properties={"mac-address": identity.mac.replace(":", "-"),
                    "serial-number": identity.serial[2:],
                    "ble-service-uuids": "0xFC82"},
        server=f"{identity.name.replace(' ', '-').lower()}.local.",
    )
    zc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    await zc.async_register_service(info, strict=False)   # Wahoo's service type is longer than mDNS allows
    log(f'Advertising "{identity.name}" on {ip}:{DIRCON_PORT}')
    log("In Zwift: Pair Devices > Controls > pick it. Ctrl-C to quit.")

    sauce = None if args.no_sauce else Sauce(args.sauce)
    watcher = RideOnWatcher(sauce) if sauce else None
    tasks = [server.serve_forever(), control.serve_forever(), ctl.keepalive(),
             ride_on_loop(ctl, args, sauce, watcher)]
    if sauce:
        tasks += [ride_watch(sauce), watcher.run()]
    try:
        async with server, control:
            await asyncio.gather(*tasks)
    finally:
        await zc.async_unregister_service(info)
        await zc.async_close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
