"""
Auto Ride On - small corner window.

This window is only the display and the ON/OFF switch. The controller itself runs in the main
app (auto_rideon_app.py), which keeps Zwift connected and reopens this window if it crashes
or freezes. Closing the window with the X quits the whole app.
"""
import json
import sys
import os
import socket
import tkinter as tk
import tkinter.font as tkfont

HERE = os.path.dirname(os.path.abspath(__file__))
CONTROL_PORT = 36867
POS_FILE = os.path.join(HERE, "gui_position.txt")

BG = "#1e1f24"
FG = "#e8e8ea"
MUTED = "#9a9ca5"
ON = "#22a559"
OFF = "#5a5d66"
WARN = "#e0a030"
IS_MAC = sys.platform == "darwin"
# macOS draws Tk point sizes smaller than Windows, so its sizes are a bit larger.
FONT = "Helvetica Neue" if IS_MAC else "Segoe UI"
SIZES = {"button": 17, "stats": 13, "small": 12, "bar": 11, "grip": 10} if IS_MAC else \
        {"button": 13, "stats": 10, "small": 9, "bar": 8, "grip": 7}
RESIZE_CURSOR = "resizebottomright" if IS_MAC else ("size_nw_se" if os.name == "nt" else "bottom_right_corner")
BAR_BG = "#15161a"             # slim custom title bar
BAR_H = 22 if IS_MAC else 18


class Link:
    """Connection to the main app. Each request is also the window's heartbeat."""

    def __init__(self):
        self.sock = None
        self.buf = b""

    def request(self, **cmd):
        cmd["from"] = "gui"
        for _ in (1, 2):
            try:
                if self.sock is None:
                    self.sock = socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=1)
                self.sock.sendall((json.dumps(cmd) + "\n").encode())
                while b"\n" not in self.buf:
                    chunk = self.sock.recv(65536)
                    if not chunk:
                        raise ConnectionError("closed")
                    self.buf += chunk
                line, self.buf = self.buf.split(b"\n", 1)
                return json.loads(line)
            except (OSError, ValueError):
                self.close()
        return None

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock, self.buf = None, b""


class App:
    def __init__(self, root):
        self.root = root
        self.link = Link()
        self.status = None
        self.missed = 0
        root.title("Auto Ride On")
        try:
            if IS_MAC:
                root.iconphoto(True, tk.PhotoImage(file=os.path.join(HERE, "icon.png")))
            else:
                root.iconbitmap(os.path.join(HERE, "auto_rideon.ico"))
        except tk.TclError:
            pass
        root.configure(bg=BG)
        # No Windows title bar: a slim one of our own (drag to move, x to close) and a corner
        # grip to resize. Everything inside scales with the window size.
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.quit_app)

        self.bar = tk.Frame(root, bg=BAR_BG, height=BAR_H)
        self.bar.pack(fill="x", side="top")
        self.bar.pack_propagate(False)
        title = tk.Label(self.bar, text="Auto Ride On", font=(FONT, SIZES["bar"]), bg=BAR_BG, fg=MUTED, padx=6)
        title.pack(side="left")
        close = tk.Label(self.bar, text="\u2715", font=(FONT, SIZES["bar"]), bg=BAR_BG, fg=MUTED, padx=7, cursor="hand2")
        close.pack(side="right", fill="y")
        close.bind("<Button-1>", lambda e: self.quit_app())
        close.bind("<Enter>", lambda e: close.config(bg="#c42b1c", fg="white"))
        close.bind("<Leave>", lambda e: close.config(bg=BAR_BG, fg=MUTED))
        for w in (self.bar, title):
            w.bind("<ButtonPress-1>", self.drag_start)
            w.bind("<B1-Motion>", self.drag_move)
            w.configure(cursor="fleur")

        # Fonts scale with the window size (base sizes below are for the default size).
        self.base_sizes = {k: SIZES[k] for k in ("button", "stats", "small")}
        self.fonts = {
            "button": tkfont.Font(family=FONT, size=SIZES["button"], weight="bold"),
            "stats": tkfont.Font(family=FONT, size=SIZES["stats"], weight="bold"),
            "small": tkfont.Font(family=FONT, size=SIZES["small"]),
        }
        if IS_MAC:
            # macOS buttons ignore background colours, so the switch is a clickable label there.
            self.button = tk.Label(root, font=self.fonts["button"], fg="white", cursor="hand2", pady=4)
            self.button.bind("<Button-1>", lambda e: self.toggle())
        else:
            self.button = tk.Button(root, font=self.fonts["button"], bd=0, relief="flat",
                                    fg="white", activeforeground="white", cursor="hand2",
                                    command=self.toggle)
        self.button.pack(fill="x", padx=10, pady=(10, 6), ipady=2)
        self.conn = tk.Label(root, font=self.fonts["small"], bg=BG, fg=MUTED, anchor="w")
        self.conn.pack(fill="x", padx=12)
        self.stats = tk.Label(root, font=self.fonts["stats"], bg=BG, fg=FG, anchor="w")
        self.stats.pack(fill="x", padx=12, pady=(4, 0))
        self.info = tk.Label(root, font=self.fonts["small"], bg=BG, fg=MUTED, anchor="w")
        self.info.pack(fill="x", padx=12, pady=(0, 10))

        # Default size: wide enough for the longest status line at normal text size.
        self.base_w = self.fonts["stats"].measure("Riders reached: ~000   ·   Presses: 000") + 30
        self.conn.configure(wraplength=self.base_w - 24, justify="left")   # long messages wrap
        self.base_h = None
        self.scale = 1.0
        self.rescale_job = None
        self.save_job = None
        self.last_render = None
        self.render()
        root.update_idletasks()
        self.base_h = root.winfo_reqheight()
        self.min_w, self.min_h = int(self.base_w * 0.6), int((self.base_h - BAR_H) * 0.6) + BAR_H
        self.grip = tk.Label(root, text="\u25e2", font=(FONT, SIZES["grip"]), bg=BG, fg="#55575f", bd=0, padx=1, pady=0)
        try:
            self.grip.configure(cursor=RESIZE_CURSOR)
        except tk.TclError:
            pass
        self.grip.place(relx=1.0, rely=1.0, anchor="se")
        self.grip.bind("<ButtonPress-1>", self.resize_start)
        self.grip.bind("<B1-Motion>", self.resize_move)
        self.place()
        root.bind("<Configure>", self.on_configure)
        if IS_MAC:
            root.after(200, lambda: (root.lift(), root.attributes("-topmost", True)))
        self.tick()

    # ---- position and size: bottom-right corner at first, then wherever (and however big) you left it
    def desktop(self):
        """(left, top, right, bottom) of the whole desktop, all monitors included."""
        if os.name == "nt":
            try:
                import ctypes
                m = ctypes.windll.user32.GetSystemMetrics
                x, y = m(76), m(77)            # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN
                return x, y, x + m(78), y + m(79)   # SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def place(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        left, top, right, bottom = self.desktop()
        w, h = self.base_w, self.base_h
        try:
            with open(POS_FILE, encoding="utf-8") as f:
                vals = [int(v) for v in f.read().split(",")]
            x, y = vals[0], vals[1]
            if len(vals) >= 4:
                w = min(max(vals[2], self.min_w), sw)
                h = min(max(vals[3], self.min_h), sh)
            if left <= x < right - 40 and top <= y < bottom - 40:
                self.root.geometry(f"{w}x{h}+{x}+{y}")
                self.apply_scale(w, h)
                return
        except (OSError, ValueError, IndexError):
            pass
        self.root.geometry(f"{w}x{h}+{sw - w - 16}+{sh - h - 90}")   # above the taskbar

    # ---- moving and resizing (the window has no Windows frame)
    def drag_start(self, ev):
        self.drag_from = (ev.x_root - self.root.winfo_x(), ev.y_root - self.root.winfo_y())

    def drag_move(self, ev):
        dx, dy = self.drag_from
        self.root.geometry(f"+{ev.x_root - dx}+{ev.y_root - dy}")

    def resize_start(self, ev):
        self.resize_from = (ev.x_root, ev.y_root, self.root.winfo_width(), self.root.winfo_height())

    def resize_move(self, ev):
        x0, y0, w0, h0 = self.resize_from
        w = max(self.min_w, w0 + ev.x_root - x0)
        h = max(self.min_h, h0 + ev.y_root - y0)
        self.root.geometry(f"{w}x{h}")

    def on_configure(self, ev):
        if ev.widget is not self.root:
            return
        if self.save_job:                     # save once, shortly after moving/resizing stops
            self.root.after_cancel(self.save_job)
        self.save_job = self.root.after(500, self.remember_position)
        if self.rescale_job:
            self.root.after_cancel(self.rescale_job)
        self.rescale_job = self.root.after(60, lambda: self.apply_scale(ev.width, ev.height))

    def apply_scale(self, w, h):
        """Grow or shrink the text and button to fit the window."""
        self.rescale_job = None
        scale = max(0.6, min(w / self.base_w, (h - BAR_H) / (self.base_h - BAR_H), 4.0))
        if abs(scale - self.scale) < 0.02:
            return
        self.scale = scale
        for name, font in self.fonts.items():
            font.configure(size=max(6, round(self.base_sizes[name] * scale)))
        pad = max(4, round(10 * scale))
        self.button.pack_configure(padx=pad, pady=(pad, round(6 * scale)))
        for lbl in (self.conn, self.stats, self.info):
            lbl.pack_configure(padx=pad + 2)
        self.conn.configure(wraplength=max(100, w - 2 * pad - 4))

    def remember_position(self, _ev=None):
        self.save_job = None
        try:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            w, h = self.root.winfo_width(), self.root.winfo_height()
            if w > 1 and h > 1:
                with open(POS_FILE, "w", encoding="utf-8") as f:
                    f.write(f"{x},{y},{w},{h}")
        except (OSError, tk.TclError):
            pass

    # ---- talking to the main app
    def tick(self):
        st = self.link.request(cmd="status")
        if st is None:
            self.missed += 1
            if self.missed >= 20:          # ~10 s without the main app: it has quit, so close too
                self.root.destroy()
                return
        else:
            self.missed = 0
            self.status = st
        self.render()
        self.root.after(500, self.tick)

    def toggle(self):
        if self.status is None:
            return
        st = self.link.request(cmd="set_enabled", on=not self.status["enabled"])
        if st:
            self.status = st
            self.render()

    def quit_app(self):
        if self.save_job:
            self.root.after_cancel(self.save_job)
        self.remember_position()
        self.link.request(cmd="quit")
        self.root.destroy()

    # ---- drawing
    def set_button(self, text, color):
        if IS_MAC:
            self.button.config(text=text, bg=color)
        else:
            self.button.config(text=text, bg=color, activebackground=color)

    def render(self):
        st = self.status
        key = None if st is None else (st["enabled"], st["connected"], st.get("error"), st["pressing"],
                                       st["in_ride"], int(st["next_in"] + 0.99), st["reached"],
                                       st["estimate"], st["sent"], st["last_reached"])
        if st is not None and key == self.last_render:
            return                                 # nothing on screen would change
        self.last_render = key
        if st is None:
            self.set_button("Ride Ons: ...", OFF)
            self.conn.config(text="Starting...", fg=WARN)
            self.stats.config(text="")
            self.info.config(text="")
            return
        on = st["enabled"]
        if st.get("error"):                       # the controller isn't running: say why
            self.set_button("Not running", OFF)
            self.conn.config(text=st["error"], fg=WARN)
            self.stats.config(text="")
            self.info.config(text="")
            return
        self.set_button("Ride Ons: ON" if on else "Ride Ons: OFF", ON if on else OFF)
        if st["connected"]:
            self.conn.config(text="● Connected to Zwift", fg=ON)
        else:
            self.conn.config(text="○ Waiting for Zwift to connect", fg=WARN)

        if st["pressing"]:
            detail = "Sending Ride On..."
        elif not on:
            detail = "Paused (still connected)"
        elif not st["connected"]:
            detail = ""
        elif st["in_ride"] is False:
            detail = "Not in a ride - waiting"
        else:
            detail = f"Next in {int(st['next_in'] + 0.99)}s"
        reached = st["reached"]
        self.stats.config(text=f"Riders reached: {'~' if st['estimate'] and reached else ''}{reached}"
                               f"   ·   Presses: {st['sent']}")
        last = "" if st["last_reached"] is None else f"Last: {st['last_reached']}/5"
        self.info.config(text="   ·   ".join(x for x in (last, detail) if x))


def main():
    if os.name == "nt":
        try:  # show our own icon instead of Python's (Windows only)
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AutoRideOn.App")
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
