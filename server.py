# server.py  –  TLS-only, no Fernet
#!/usr/bin/env python3
"""ChatFlow LAN server – step 1 (transport security cleanup)"""

import ssl, socket, threading, logging, pathlib, os, re, datetime
import pandas as pd

# ---------- config ----------
HOST, PORT = "192.168.1.63", 1234
MAX_MSG_LEN, MAX_FIELD_LEN = 1024, 256
USER_CSV, CHAT_CSV = "userdata.csv", "chathistory.csv"
TLS_DIR   = pathlib.Path(__file__).parent / "tls"
CRT_FILE  = TLS_DIR / "server.crt"
KEY_FILE  = TLS_DIR / "server.key"
CA_FILE   = TLS_DIR / "ca.crt"
# ----------------------------

logging.basicConfig(filename="server.log",
                    level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")

# ---------- TLS helper ----------
def wrap_tls(sock: socket.socket) -> ssl.SSLSocket:
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(certfile=str(CRT_FILE), keyfile=str(KEY_FILE))
    ctx.load_verify_locations(cafile=str(CA_FILE))         # verify server cert for clients that want it
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.verify_mode = ssl.CERT_OPTIONAL                    # ⇠ _no_ mutual TLS
    return ctx.wrap_socket(sock, server_side=True)
def line_reader(sock: ssl.SSLSocket):
    """Return a file-like object with .readline()."""
    return sock.makefile("r", encoding="utf-8", newline="\n")

def send_line(sock: ssl.SSLSocket, msg: str):
    sock.sendall(f"{msg}\n".encode())

bcast_lock = threading.Lock() 
# ---------------------------------

def recv_line(sock: ssl.SSLSocket) -> str:
    data = sock.recv(MAX_MSG_LEN)
    if not data:
        return ""
    try:
        return data.decode("utf-8").strip()[:MAX_FIELD_LEN]
    except UnicodeDecodeError:
        return ""

def send_line(sock: ssl.SSLSocket, msg: str) -> None:
    sock.sendall(f"{msg}\n".encode())

# ---------- CSV bootstrap ----------
for fp, cols in ((USER_CSV, ["username", "password"]),
                 (CHAT_CSV, ["timestamp", "user", "message"])):
    if not os.path.exists(fp):
        pd.DataFrame(columns=cols).to_csv(fp, index=False)

users  = pd.read_csv(USER_CSV)
chlog  = pd.read_csv(CHAT_CSV)
def save_users(): users.to_csv(USER_CSV, index=False)
def append_log(ts,u,m):          # also flush to csv
    global chlog
    chlog = pd.concat([chlog, pd.DataFrame([[ts,u,m]], columns=["timestamp","user","message"])])
    chlog.to_csv(CHAT_CSV, index=False)
# ------------------------------------

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,20}$")
def valid_user(u): return USERNAME_RE.match(u)
def valid_pw(p):   return 8 <= len(p) <= MAX_FIELD_LEN

clients = {}           # live connections {sock:username}

def broadcast(txt:str, *, skip=None):
    for s in list(clients):
        if s is skip:  continue
        try:    send_line(s, txt)
        except OSError: s.close(); clients.pop(s, None)

def auth_handshake(s: ssl.SSLSocket) -> str:
    send_line(s, "Login or Reg"); mode = recv_line(s)
    send_line(s, "USER");         user = recv_line(s)
    send_line(s, "PW");           pw   = recv_line(s)

    global users
    if mode == "Register":
        if not (valid_user(user) and valid_pw(pw)):
            send_line(s, "Invalid registration data"); return
        if not users[users.username == user].empty:
            send_line(s, "User already exist"); return
        users = pd.concat([users, pd.DataFrame([[user, pw]], columns=["username","password"])],
                          ignore_index=True)
        save_users()
        send_line(s, "Registration Successful")

    row = users[users.username == user]
    if row.empty:
        send_line(s, "User does not exist"); return
    if row.iloc[0].password != pw:
        send_line(s, "Incorrect Password");  return

    send_line(s, "Authenticated")
    return user

def serve_client(conn: ssl.SSLSocket):
    me = clients[conn]
    try:
        while True:
            txt = recv_line(conn)
            if not txt: break
            t = datetime.datetime.now().strftime("%H:%M")
            append_log(t, me, txt)
            broadcast(f"{t} | {me}: {txt}")
    finally:
        conn.close(); clients.pop(conn, None)
        broadcast(f"{me} left the chat!")

def main():
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp.bind((HOST, PORT)); tcp.listen()
    print(f"🚀 TLS chat server listening on {HOST}:{PORT}")
    while True:
        raw, addr = tcp.accept()
        try:
            cli = wrap_tls(raw)
        except ssl.SSLError as e:
            logging.warning("TLS handshake failed: %s", e); raw.close(); continue
        user = auth_handshake(cli)
        if not user: cli.close(); continue

        clients[cli] = user
        for _, r in chlog.iterrows():
            send_line(cli, f"{pd.to_datetime(r.timestamp):%H:%M} | {r.user}: {r.message}")
        broadcast(f"{user} joined the chat!", skip=cli)
        threading.Thread(target=serve_client, args=(cli,), daemon=True).start()

if __name__ == "__main__":
    main()