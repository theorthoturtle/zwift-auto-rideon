"""
Auto Ride On - main app (no console window).

Runs the virtual controller and watches the corner window, which runs as its own program:
  * if the window crashes or closes unexpectedly, it is reopened within a few seconds
  * if the window freezes (no heartbeat for 15 s), it is closed and reopened
  * closing the window yourself (the X) quits the whole app
  * starting the app again while it's running just brings the window back
  * if the controller can't start, the window stays open and shows why
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auto_rideon as ar  # noqa: E402

GUI_SCRIPT = next((os.path.join(HERE, n) for n in ("auto_rideon_gui.py", "auto_rideon_gui.pyw")
                   if os.path.exists(os.path.join(HERE, n))), os.path.join(HERE, "auto_rideon_gui.py"))
FROZEN_AFTER = 15      # seconds without a heartbeat from the window = frozen
CHECK_EVERY = 2        # seconds between health checks
QUICK_EXIT = 5         # a window that dies this soon after opening counts as a crash loop...
MAX_BACKOFF = 60       # ...and is reopened after 2, 4, 8 ... up to 60 s instead of straight away


def already_running():
    """If another copy is running, ask it to show its window and return True."""
    try:
        with socket.create_connection(("127.0.0.1", ar.CONTROL_PORT), timeout=1) as s:
            s.sendall(b'{"cmd": "show"}\n')
            s.recv(4096)
        return True
    except OSError:
        return False


def pythonw():
    exe = sys.executable
    if os.name == "nt" and exe.lower().endswith("python.exe"):
        cand = exe[:-10] + "pythonw.exe"
        if os.path.exists(cand):
            return cand
    return exe


class Supervisor:
    def __init__(self):
        self.proc = None
        self.quitting = False
        self.launched_at = 0.0
        self.quick_exits = 0           # crashes in a row right after opening
        self.relaunch_at = None        # when to reopen a crashed window
        self.wake = threading.Event()

    def launch_gui(self, why):
        if why:
            ar.log(f"Window health check: {why} - reopening the window")
        flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
        self.proc = subprocess.Popen([pythonw(), GUI_SCRIPT], cwd=HERE, creationflags=flags)
        self.launched_at = time.time()
        self.relaunch_at = None
        ar.CONTROL.gui_seen = 0.0

    def kill_gui(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
                self.proc.wait(5)
            except Exception:
                pass

    def request_quit(self):           # called when you close the window with the X
        self.quitting = True
        self.wake.set()

    def request_show(self):           # called when the app is started again while running
        self.wake.set()

    def check(self, show):
        now = time.time()
        code = self.proc.poll()
        if code is not None:                              # window gone
            if self.relaunch_at is None:
                quick = now - self.launched_at < QUICK_EXIT
                self.quick_exits = self.quick_exits + 1 if quick else 0
                delay = min(MAX_BACKOFF, 2 ** self.quick_exits) if self.quick_exits > 1 else 0
                self.relaunch_at = now + delay
                if delay:
                    ar.log(f"Window health check: window keeps closing right after opening "
                           f"(exit code {code}) - trying again in {delay}s")
            if show or now >= self.relaunch_at:
                self.launch_gui(f"window closed unexpectedly (exit code {code})")
            return
        if ar.CONTROL.gui_seen and now - ar.CONTROL.gui_seen > QUICK_EXIT:
            self.quick_exits = 0                          # it has been running fine
        last = ar.CONTROL.gui_seen or self.launched_at
        if now - last > FROZEN_AFTER:
            self.kill_gui()
            self.launch_gui(f"window stopped responding for {int(now - last)}s")
        elif show:
            # reopen it so it comes to the front even if it was hidden or off-screen
            self.kill_gui()
            self.launch_gui("asked to show the window")

    def run(self):
        self.launch_gui(None)
        while not self.quitting:
            self.wake.wait(CHECK_EVERY)
            show = self.wake.is_set()
            self.wake.clear()
            if not self.quitting:
                self.check(show)
        self.kill_gui()


async def serve_status_only():
    """The controller stopped: keep answering the window so it can show the error."""
    try:
        server = await asyncio.start_server(ar.CONTROL.handle, "127.0.0.1", ar.CONTROL_PORT)
    except OSError as e:
        ar.log(f"Couldn't open the window connection either: {e}")
        return
    async with server:
        await server.serve_forever()


def main():
    if already_running():
        return
    sup = Supervisor()
    ar.CONTROL.on_quit = sup.request_quit
    ar.CONTROL.on_show = sup.request_show
    ar.STATUS.enabled = ar.load_enabled()

    def engine():
        try:
            asyncio.run(ar.main([]))
        except OSError as e:
            in_use = e.errno in (48, 98, 10048) or getattr(e, "winerror", None) == 10048
            ar.STATUS.error = ("Couldn't start: Auto Ride On is already running in another window"
                               if in_use else f"Couldn't start: {e}")
        except Exception as e:
            ar.STATUS.error = f"Error: {e}"
        ar.STATUS.error = ar.STATUS.error or "The controller stopped unexpectedly"
        ar.log(ar.STATUS.error)
        asyncio.run(serve_status_only())

    threading.Thread(target=engine, daemon=True).start()
    # give the engine a moment to open its control port before the window connects
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", ar.CONTROL_PORT), timeout=0.2).close()
            break
        except OSError:
            if ar.STATUS.error:
                break
            time.sleep(0.1)
    sup.run()
    ar.log("Window closed - quitting")
    os._exit(0)


if __name__ == "__main__":
    main()
