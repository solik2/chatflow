#!/usr/bin/env python3
"""
Tkinter chat client with a dark theme.

✓ First screen:  Login / Register form
✓ After success: Scrollable chat + entry box
✓ Background thread keeps the socket alive and pushes
  incoming text into a thread-safe queue that the UI polls.

Requires:
    pip install ttkbootstrap
"""

import socket, threading, queue, sys, ssl
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from pathlib import Path
from getpass import getpass   # fallback for CLI if GUI fails
from functools import partial
import tkinter as tk 

# -------------- configuration -----------------
HOST, PORT = "192.168.1.63", 1234        # edit or pass via CLI
BUF = 1024
CA_CERT = "tls/ca.crt"
# ----------------------------------------------

class ChatClient(threading.Thread):
    """Networking layer → puts messages into q, reads from send_q."""
    def __init__(self, creds, msg_q, send_q):
        super().__init__(daemon=True)
        self.creds, self.q, self.send_q = creds, msg_q, send_q
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # ------- helpers mirroring old terminal client -------
    def _dispatch_server_prompt(self, msg):
        if msg == "Login or Reg":
            self.sock.sendall(self.creds["mode"].encode())
        elif msg == "USER":
            self.sock.sendall(self.creds["user"].encode())
        elif msg == "PW":
            self.sock.sendall(self.creds["password"].encode())
        else:
            return False
        return True
    # ------------------------------------------------------

    def run(self):
        try:
            # 1. Plain TCP socket
            raw_sock = socket.create_connection((HOST, PORT))
            # 2. SSL context for server-authenticated TLS
            ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH,cafile=CA_CERT)
            ctx.check_hostname = False             # LAN: no DNS; disable hostname match
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            # 3. TLS-wrapped socket
            self.sock = ctx.wrap_socket(raw_sock, server_hostname="chatserver.local")
            # 4. Connect and perform handshake
            self.q.put(("info", f"Connected to {HOST}:{PORT}"))

            # receiver loop
            recv_t = threading.Thread(target=self._recv_loop, daemon=True)
            recv_t.start()

            # sender loop
            while True:
                line = self.send_q.get()
                if line in {"exit", "quit"}:
                    break
                self.sock.sendall(line.encode())
        finally:
            self.sock.close()
            self.q.put(("info", "Disconnected"))

    def _recv_loop(self):
        while True:
            try:
                data = self.sock.recv(BUF)
                if not data:
                    break
                msg = data.decode().strip()

                # handshake prompts
                if self._dispatch_server_prompt(msg):
                    continue

                # auth result or chat content
                self.q.put(("chat", msg))
            except ssl.SSLError as e:
                print("TLS error:", e)
                self.disconnect()
                return
            except OSError:
                break

class LoginFrame(ttk.Frame):
    """First screen: collects creds, starts ChatClient."""
    def __init__(self, master, start_chat_cb):
        super().__init__(master, padding=30)
        self.start_chat_cb = start_chat_cb
        ttk.Label(self, text="ChatFlow", font=("Helvetica", 20, "bold")).pack(pady=10)

        self.mode = ttk.StringVar(value="Login")
        ttk.Radiobutton(self, text="Login", variable=self.mode, value="Login").pack(side=LEFT, padx=5)
        ttk.Radiobutton(self, text="Register", variable=self.mode, value="Register").pack(side=LEFT)

        self.user_entry = ttk.Entry(self, width=25)
        self.pass_entry = ttk.Entry(self, width=25, show="*")
        for lbl, widget in (("Username", self.user_entry), ("Password", self.pass_entry)):
            ttk.Label(self, text=lbl).pack(anchor=W, pady=(15, 0))
            widget.pack(fill=X)

        ttk.Button(self, text="Connect", command=self._submit).pack(pady=20)

    def _submit(self):
        creds = {
            "mode": self.mode.get(),
            "user": self.user_entry.get().strip(),
            "password": self.pass_entry.get().strip()
        }
        if not creds["user"] or not creds["password"]:
            ttk.Messagebox.show_error("Please fill in both fields")
            return
        self.start_chat_cb(creds)

class ChatFrame(ttk.Frame):
    """Main chat UI: history + entry."""
    def __init__(self, master, msg_q, send_q):
        super().__init__(master, padding=10)
        self.q, self.send_q = msg_q, send_q

        self.output = ScrolledText(self, bootstyle="dark", height=20, state="disabled")
        self.output.pack(fill=BOTH, expand=YES, pady=(0,10))

        self.entry = ttk.Entry(self)
        self.entry.pack(fill=X, side=LEFT, expand=YES)
        self.entry.bind("<Return>", self._send)

        ttk.Button(self, text="Send", command=self._send).pack(side=RIGHT, padx=5)

        # poll queue every 100 ms
        self.after(100, self._poll_q)

    def _poll_q(self):
        try:
            while True:
                tag, text = self.q.get_nowait()
                self._append(text, tag)
        except queue.Empty:
            pass
        self.after(100, self._poll_q)

    def _append(self, text: str, tag: str = "chat"):
        txt = self.output.text            # the actual tk.Text widget
        txt.configure(state="normal")

        if tag == "info":
            txt.insert(tk.END, f"[{text}]\n")
        else:
            txt.insert(tk.END, f"{text}\n")

        txt.configure(state="disabled")
        txt.yview_moveto(1.0)

    def _send(self, event=None):
        line = self.entry.get().strip()
        if line:
            self.send_q.put(line)
            self.entry.delete(0, END)

class App(ttk.Window):
    def __init__(self):
        super().__init__(title="ChatFlow")
        self.geometry("500x450")
        self.style.theme_use("darkly")   # ttkbootstrap dark theme

        self.msg_q, self.send_q = queue.Queue(), queue.Queue()
        self._show_login()

    def _show_login(self):
        self.login = LoginFrame(self, self._start_chat)
        self.login.pack(fill=BOTH, expand=YES)

    def _start_chat(self, creds):
        # start networking thread
        ChatClient(creds, self.msg_q, self.send_q).start()
        # swap frames
        self.login.destroy()
        ChatFrame(self, self.msg_q, self.send_q).pack(fill=BOTH, expand=YES)

if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception as e:
        # graceful fallback to old CLI if Tk fails (e.g. missing DISPLAY)
        print("GUI failed, falling back to terminal:", e)
        import client  # your original terminal client
        client.main()
