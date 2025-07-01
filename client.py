#!/usr/bin/env python3
"""
ChatFlow LAN Client
===================
Tkinter GUI client with Fernet-encrypted communication.

Key Points
----------
* Supports Login / Register flows and stays on the login screen until the
  server returns “Authenticated”.
* Runs a background receiver thread that remains alive after authentication
  and allows reconnection attempts without restarting the program.
* All console debugging prints have been removed; status messages are routed
  to the GUI.
"""

from __future__ import annotations
import socket
import threading
import queue
from pathlib import Path

import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, YES, END, LEFT, RIGHT, W, X
from ttkbootstrap.scrolled import ScrolledText
from cryptography.fernet import Fernet, InvalidToken

# ────────────────────────────── Configuration ──────────────────────────────
HOST, PORT = "0.0.0.0", 1234
KEY_FILE   = "fernet.key"              # must match the server key
BUF_SIZE   = 4096
# ────────────────────────────────────────────────────────────────────────────

FERNET = Fernet(Path(KEY_FILE).read_bytes())

# ───────────────────────────── Networking Thread ───────────────────────────
class ChatClient(threading.Thread):
    """
    Background thread that manages a single login/chat session.

    Queues
    ------
    msg_q  : GUI message queue – receives tuples:
             ('info',  str)   – informational status line
             ('auth_ok', '')  – authentication successful
             ('auth_fail', r) – authentication error text
             ('chat',   str)  – chat line from server
    send_q : queue.Queue – outbound messages from the GUI
    """
    def __init__(self, creds: dict[str, str],
                 msg_q: "queue.Queue[tuple[str, str]]",
                 send_q: "queue.Queue[str]"):
        super().__init__(daemon=True)
        self.creds   = creds
        self.msg_q   = msg_q
        self.send_q  = send_q
        self.sock    = socket.socket()
        self.running = True
        self.authenticated = False

    # ──────────────── internal helpers ────────────────
    def _send_token(self, text: str) -> None:
        """Encrypt and send a line to the server."""
        self.sock.sendall(FERNET.encrypt(text.encode()))

    def _handle_prompt(self, prompt: str) -> bool:
        """
        Respond to server handshake prompts.
        Returns True if the prompt was handled here.
        """
        if prompt == "Login or Reg":
            self._send_token(self.creds["mode"])
        elif prompt == "USER":
            self._send_token(self.creds["user"])
        elif prompt == "PW":
            self._send_token(self.creds["password"])
        else:
            return False
        return True

    # ──────────────── main thread loop ────────────────
    def run(self) -> None:
        try:
            self.sock.connect((HOST, PORT))
            self.msg_q.put(("info", f"Connected to {HOST}:{PORT}"))

            # launch receiver on a sub-thread
            threading.Thread(target=self._recv_loop, daemon=True).start()

            # sender loop – active only after auth_ok
            while self.running:
                try:
                    line = self.send_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if not self.authenticated:
                    continue
                if line.lower() in {"quit", "exit"}:
                    break
                self._send_token(line)
        finally:
            self.running = False
            try:
                self.sock.close()
            except OSError:
                pass
            self.msg_q.put(("info", "Disconnected"))

    # ──────────────── receiver loop ────────────────
    def _recv_loop(self) -> None:
        """Reads encrypted messages from the socket and pushes them to the GUI queue."""
        while self.running:
            try:
                chunk = self.sock.recv(BUF_SIZE)
                if not chunk:
                    break
                try:
                    plain = FERNET.decrypt(chunk).decode().strip()
                except InvalidToken:
                    continue

                for line in plain.splitlines():
                    # handshake flow
                    if self._handle_prompt(line):
                        continue
                    if line == "Authenticated":
                        self.authenticated = True
                        self.msg_q.put(("auth_ok", ""))
                        continue
                    if line.startswith(("Authentication failed",
                                        "User does not exist",
                                        "Incorrect password",
                                        "Bad registration data",
                                        "User already exists")):
                        self.msg_q.put(("auth_fail", line))
                        self.running = False
                        return
                    # normal chat
                    self.msg_q.put(("chat", line))
            except OSError:
                break
        self.running = False

# ─────────────────────────────── GUI Frames ────────────────────────────────
class LoginFrame(ttk.Frame):
    """Login/Register screen; stays visible until authentication succeeds."""
    def __init__(self, master: "App", on_success):
        super().__init__(master, padding=30)
        self.master   = master
        self.on_success = on_success
        self.msg_q, self.send_q = master.msg_q, master.send_q
        self.client: ChatClient | None = None

        # — header —
        ttk.Label(self, text="ChatFlow",
                  font=("Helvetica", 20, "bold")).pack(pady=10)

        # — mode selector —
        self.mode = ttk.StringVar(value="Login")
        ttk.Radiobutton(self, text="Login",    variable=self.mode, value="Login").pack(side=LEFT, padx=5)
        ttk.Radiobutton(self, text="Register", variable=self.mode, value="Register").pack(side=LEFT)

        # — credential fields —
        self.user = ttk.Entry(self, width=25)
        self.pwd  = ttk.Entry(self, width=25, show="*")
        for label, widget in (("Username", self.user), ("Password", self.pwd)):
            ttk.Label(self, text=label).pack(anchor=W, pady=(15, 0))
            widget.pack(fill=X)

        # — connect button & status —
        self.btn = ttk.Button(self, text="Connect", command=self._connect)
        self.btn.pack(pady=20)
        self.status = ttk.Label(self, text="", bootstyle="danger")
        self.status.pack()

        self.after(100, self._poll_queue)

    # ───────── internal helpers ─────────
    def _set_status(self, txt: str, style: str = "danger") -> None:
        self.status.configure(text=txt, bootstyle=style)

    def _connect(self) -> None:
        """Validate fields and start a new ChatClient thread."""
        creds = {
            "mode": self.mode.get(),
            "user": self.user.get().strip(),
            "password": self.pwd.get().strip()
        }
        if not creds["user"] or not creds["password"]:
            self._set_status("All fields required")
            return

        # stop previous attempt if still running
        if self.client and self.client.running:
            self.client.running = False
            try:
                self.client.sock.close()
            except OSError:
                pass

        self.client = ChatClient(creds, self.msg_q, self.send_q)
        self.client.start()
        self.btn.configure(state=ttk.DISABLED)
        self._set_status("Connecting…", style="warning")

    def _poll_queue(self) -> None:
        """Handle authentication results coming from the worker thread."""
        try:
            while True:
                tag, payload = self.msg_q.get_nowait()
                if tag == "auth_ok":
                    self.on_success()
                    return
                if tag == "auth_fail":
                    self._set_status(payload)
                    self.btn.configure(state=ttk.NORMAL)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

class ChatFrame(ttk.Frame):
    """Main chat window, shown after successful login."""
    def __init__(self, master: "App"):
        super().__init__(master, padding=10)
        self.msg_q, self.send_q = master.msg_q, master.send_q

        # — scrollable chat output —
        self.output = ScrolledText(self, bootstyle="dark", height=20, state="disabled")
        self.output.pack(fill=BOTH, expand=YES, pady=(0, 10))

        # — input line & send button —
        self.entry = ttk.Entry(self)
        self.entry.pack(fill=X, side=LEFT, expand=YES)
        self.entry.bind("<Return>", self._send)
        ttk.Button(self, text="Send", command=self._send).pack(side=RIGHT, padx=5)

        self.after(100, self._poll_queue)

    def _append(self, txt: str, tag: str) -> None:
        """Write a line to the chat window."""
        widget = self.output.text
        widget.configure(state="normal")
        widget.insert(ttk.END, f"[{txt}]\n" if tag == "info" else f"{txt}\n")
        widget.configure(state="disabled")
        widget.yview_moveto(1.0)

    def _poll_queue(self) -> None:
        """Display incoming chat and info lines."""
        try:
            while True:
                tag, txt = self.msg_q.get_nowait()
                if tag in {"chat", "info"}:
                    self._append(txt, tag)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _send(self, *_):
        """Place user input onto the outbound queue."""
        line = self.entry.get().strip()
        if line:
            self.send_q.put(line)
            self.entry.delete(0, END)

# ───────────────────────────── Main Application ────────────────────────────
class App(ttk.Window):
    """Root Tk application window."""
    def __init__(self):
        super().__init__(title="ChatFlow")
        self.geometry("520x460")
        self.style.theme_use("darkly")
        self.msg_q: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.send_q: "queue.Queue[str]" = queue.Queue()
        self._show_login()

    def _show_login(self) -> None:
        self.login = LoginFrame(self, self._show_chat)
        self.login.pack(fill=BOTH, expand=YES)

    def _show_chat(self) -> None:
        self.login.destroy()
        ChatFrame(self).pack(fill=BOTH, expand=YES)

# ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    App().mainloop()
