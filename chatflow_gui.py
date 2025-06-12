#!/usr/bin/env python3
"""
Tkinter-based TLS chat client (GUI only, no Fernet).

Requires:
    pip install ttkbootstrap
"""

import ssl, socket, threading, queue, pathlib, ttkbootstrap as ttk, tkinter as tk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from ttkbootstrap.dialogs import Messagebox          # ← correct import

# ---------- configuration ----------
HOST, PORT = "192.168.1.63", 1234
BUF        = 1024
TLS_DIR    = pathlib.Path(__file__).parent / "tls"
# -----------------------------------

# ────────────────────────── networking ──────────────────────────
class ChatClient(threading.Thread):
    """Background thread managing the TLS socket."""
    def __init__(self, creds, msg_q, send_q):
        super().__init__(daemon=True)
        self.creds, self.q, self.send_q = creds, msg_q, send_q

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.load_verify_locations(cafile=str(TLS_DIR / "ca.crt"))
        raw  = socket.create_connection((HOST, PORT))
        self.sock = ctx.wrap_socket(raw, server_hostname=HOST)

    # helper: always newline-terminate outbound protocol messages
    def _writeline(self, txt: str):
        self.sock.sendall(f"{txt}\n".encode())

    # match server prompts during login/registration
    def _dispatch_prompt(self, line: str) -> bool:
        if   line == "Login or Reg":
            self._writeline(self.creds["mode"]);    return True
        elif line == "USER":
            self._writeline(self.creds["user"]);    return True
        elif line == "PW":
            self._writeline(self.creds["password"]);return True
        return False

    # main thread loop: read from GUI queue → socket
    def run(self):
        threading.Thread(target=self._recv_loop, daemon=True).start()
        try:
            while True:
                msg = self.send_q.get()
                if msg in {"exit", "quit"}:
                    break
                self._writeline(msg)
        finally:
            self.sock.close()
            self.q.put(("info", "Disconnected"))

    # secondary loop: socket → GUI queue
    def _recv_loop(self):
        buffer = ""
        while True:
            chunk = self.sock.recv(BUF)
            if not chunk:
                break
            buffer += chunk.decode()
            # process complete lines, keep remainder in buffer
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if self._dispatch_prompt(line):
                    continue
                if line == "Authenticated":
                    self.q.put(("auth_ok", None))
                elif line in {
                    "User does not exist", "Incorrect Password",
                    "Invalid registration data", "User already exist"
                }:
                    self.q.put(("auth_err", line))
                else:
                    self.q.put(("chat", line))

# ────────────────────────── GUI widgets ──────────────────────────
class LoginFrame(ttk.Frame):
    """Collects credentials and spawns ChatClient."""
    def __init__(self, master, start_chat_cb):
        super().__init__(master, padding=30)
        self.start_chat_cb = start_chat_cb
        ttk.Label(self, text="ChatFlow", font=("Helvetica", 20, "bold")).pack(pady=10)

        self.mode = ttk.StringVar(value="Login")
        ttk.Radiobutton(self, text="Login",    variable=self.mode, value="Login").pack(side=LEFT, padx=5)
        ttk.Radiobutton(self, text="Register", variable=self.mode, value="Register").pack(side=LEFT)

        self.user_entry = ttk.Entry(self, width=25)
        self.pass_entry = ttk.Entry(self, width=25, show="*")
        for lbl, widget in (("Username", self.user_entry), ("Password", self.pass_entry)):
            ttk.Label(self, text=lbl).pack(anchor=W, pady=(15, 0))
            widget.pack(fill=X)

        ttk.Button(self, text="Connect", command=self._submit).pack(pady=20)

    def _submit(self):
        creds = dict(mode=self.mode.get(),
                     user=self.user_entry.get().strip(),
                     password=self.pass_entry.get().strip())
        if not creds["user"] or not creds["password"]:
            Messagebox.show_error("Please fill in both fields", title="Missing data")
            return
        self.start_chat_cb(creds)

class ChatFrame(ttk.Frame):
    """Scrollable chat log + message entry."""
    def __init__(self, master, msg_q, send_q):
        super().__init__(master, padding=10)
        self.q, self.send_q = msg_q, send_q

        self.output = ScrolledText(self, bootstyle="dark", height=20, state="disabled")
        self.output.pack(fill=BOTH, expand=YES, pady=(0, 10))

        self.entry = ttk.Entry(self)
        self.entry.pack(fill=X, side=LEFT, expand=YES)
        self.entry.bind("<Return>", self._send)

        ttk.Button(self, text="Send", command=self._send).pack(side=RIGHT, padx=5)

        self.after(100, self._poll_q)  # poll queue every 100 ms

    def _poll_q(self):
        try:
            while True:
                tag, text = self.q.get_nowait()
                self._append(text, tag)
        except queue.Empty:
            pass
        self.after(100, self._poll_q)

    def _append(self, text: str, tag: str = "chat"):
        txt = self.output.text  # underlying tk.Text widget
        txt.configure(state="normal")
        if tag == "info":
            txt.insert(tk.END, f"[{text}]\n")
        else:
            txt.insert(tk.END, f"{text}\n")
        txt.configure(state="disabled")
        txt.yview_moveto(1.0)

    def _send(self, _=None):
        line = self.entry.get().strip()
        if line:
            self.send_q.put(line)
            self.entry.delete(0, END)

# ────────────────────────── main window ──────────────────────────
class App(ttk.Window):
    def __init__(self):
        super().__init__(title="ChatFlow")
        self.geometry("500x450")
        self.style.theme_use("darkly")
        self.msg_q, self.send_q = queue.Queue(), queue.Queue()
        self._show_login()
        self.after(100, self._pump)

    def _show_login(self):
        self.login = LoginFrame(self, self._connect)
        self.login.pack(fill=BOTH, expand=YES)

    def _connect(self, creds):
        for w in self.login.winfo_children():
            w.configure(state="disabled")
        ChatClient(creds, self.msg_q, self.send_q).start()

    def _pump(self):
        try:
            while True:
                typ, payload = self.msg_q.get_nowait()
                if typ == "auth_ok":
                    self.login.destroy()
                    ChatFrame(self, self.msg_q, self.send_q).pack(fill=BOTH, expand=YES)
                elif typ == "auth_err":
                    Messagebox.show_error(payload, title="Auth failed")
                    self.login.destroy()
                    self._show_login()
        except queue.Empty:
            pass
        finally:
            self.after(100, self._pump)

# ────────────────────────── entry point ──────────────────────────
if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception as e:
        print("GUI failed, falling back to terminal:", e)
        
