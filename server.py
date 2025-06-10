# chatflow_csv_server.py
import socket
import threading
import pandas as pd
import datetime
import os
import re
import logging
from cryptography.fernet import Fernet, InvalidToken

# ------------------- configuration -------------------
HOST = '192.168.0.106'
PORT = 1234
MAX_MSG_LEN = 1024       # hard socket read cap
MAX_FIELD_LEN = 256      # individual field length cap
USER_CSV = 'userdata.csv'
CHAT_CSV = 'chathistory.csv'
KEY_FILE = 'fernet.key'
LOG_FILE = 'server.log'
# -----------------------------------------------------

# --------------------- logging -----------------------
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
# -----------------------------------------------------

# ---------------- encryption key ---------------------
def load_or_create_key() -> bytes:
    try:
        print("[DEBUG] Loading or creating encryption key")
        if os.path.exists(KEY_FILE):
            with open(KEY_FILE, 'rb') as kf:
                key = kf.read()
            # 44-byte urlsafe base64 key check
            if len(key) == 44:
                print("[DEBUG] Key loaded successfully")
                return key
            logging.warning("Invalid key length; regenerating.")
        key = Fernet.generate_key()
        with open(KEY_FILE, 'wb') as kf:
            kf.write(key)
        print("[DEBUG] New key generated and saved")
        return key
    except Exception as e:
        logging.error(f"Key load/create error: {e}")
        raise

fernet = Fernet(load_or_create_key())
# -----------------------------------------------------

# ----------------- helpers: validation ---------------
SPECIAL_RE = re.compile(r"[^\w]")

def is_valid_username(name: str) -> bool:
    return 0 < len(name) <= MAX_FIELD_LEN and name.isalnum()

def is_valid_password(pw: str) -> bool:
    return (
        len(pw) >= 8 and len(pw) <= MAX_FIELD_LEN and
        SPECIAL_RE.search(pw) is not None
    )

def sanitize(text: str) -> str:
    return re.sub(r"[^\w@\.\- ]", "", text)[:MAX_FIELD_LEN]
# -----------------------------------------------------

# ------------- helpers: file & dataframe -------------
def safe_csv_load(path: str, columns: list[str]) -> pd.DataFrame:
    try:
        if os.path.exists(path):
            df = pd.read_csv(path)
            if list(df.columns) == columns:
                return df
            logging.warning(f"{path} corrupted; recreating.")
        raise ValueError
    except Exception:
        df = pd.DataFrame(columns=columns)
        df.to_csv(path, index=False)
        return df

userdata_df = safe_csv_load(USER_CSV, ['username', 'password'])
chathistory_df = safe_csv_load(CHAT_CSV, ['timestamp', 'user', 'message'])
# -----------------------------------------------------

# ---------------- encryption wrappers ----------------
def decrypt_try(blob: bytes) -> bytes:
    try:
        return fernet.decrypt(blob)
    except (InvalidToken, ValueError):
        return b''

def recv_decoded(sock) -> str:
    print("[DEBUG] Receiving data from socket")
    raw = sock.recv(MAX_MSG_LEN)
    if not raw:
        print("[DEBUG] No data received")
        return ''
    plain = decrypt_try(raw) or raw  # fallback to plaintext
    print(f"[DEBUG] Data received: {plain[:50]}...")
    return plain.decode(errors='ignore')[:MAX_FIELD_LEN]

# ---------- server.py ----------
def send_plain(sock: socket.socket, msg: str) -> None:
    """Send ONE logical message framed with '\n'."""
    sock.sendall(f"{msg}".encode("utf-8"))

# -----------------------------------------------------

# ------------------ core functions -------------------
def save_user_data():
    userdata_df.to_csv(USER_CSV, index=False)

def append_chat_history(timestamp, user, message):
    global chathistory_df
    if len(message) > MAX_FIELD_LEN:
        message = message[:MAX_FIELD_LEN]
    new_row = pd.DataFrame([[timestamp, user, message]],
                           columns=['timestamp', 'user', 'message'])
    chathistory_df = pd.concat([chathistory_df, new_row], ignore_index=True)
    chathistory_df.to_csv(CHAT_CSV, index=False)

def broadcast(msg: str, username: str = None):
    if username:
        msg = f"{username}: {msg}"
    tagged = f"\n{datetime.datetime.now():%H:%M} | {msg}".encode()
    for cli in list(clients.keys()):
        try:
            cli.send(tagged)
        except Exception as e:
            logging.error(f"Broadcast to {clients.get(cli)} failed: {e}")
# -----------------------------------------------------

# --------------- networking / threading --------------
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen()
clients: dict[socket.socket, str] = {}

def handle_client(cli: socket.socket):
    print("[DEBUG] Handling new client")
    try:
        username = clients.get(cli, 'Unknown')
        while True:
            decoded = recv_decoded(cli)
            if not decoded:
                print("[DEBUG] Client disconnected")
                break

            print(f"[DEBUG] Message from client: {decoded}")
            if decoded == 'File Transfer':
                send_plain(cli, 'Send File Name')
                filename = sanitize(recv_decoded(cli))
                if not filename:
                    send_plain(cli, 'Invalid filename')
                    continue
                send_plain(cli, 'Send File')

                with open(filename, 'wb') as f:
                    while True:
                        chunk = cli.recv(MAX_MSG_LEN)
                        if decrypt_try(chunk) == b'Completed':
                            break
                        f.write(decrypt_try(chunk) or chunk)
                print(f"[DEBUG] File {filename} received")
                continue

            if ':' in decoded:
                user, msg = map(str.strip, decoded.split(':', 1))
                append_chat_history(datetime.datetime.now(), user, msg)
            broadcast(decoded, username=username)
    except Exception as e:
        logging.error(f"Client handler error: {e}")
    finally:
        username = clients.pop(cli, 'Unknown')
        broadcast(f"{username} left the chat!")
        cli.close()
        print("[DEBUG] Client handler closed")

def login(username, password, cli) -> bool:
    row = userdata_df[userdata_df['username'] == username]
    if row.empty:
        send_plain(cli, 'User does not exist')
        return False
    if row.iloc[0]['password'] != password:
        send_plain(cli, 'Incorrect Password')  # Send specific error message
        return False
    return True

def register(username, password, cli) -> bool:
    global userdata_df
    if not (is_valid_username(username) and is_valid_password(password)):
        send_plain(cli, 'Invalid registration data')
        return False
    if not userdata_df[userdata_df['username'] == username].empty:
        send_plain(cli, 'User already exist')
        return False
    new_row = pd.DataFrame([[username, password]],
                           columns=['username', 'password'])
    userdata_df = pd.concat([userdata_df, new_row], ignore_index=True)
    save_user_data()
    send_plain(cli, 'Registration Successful')  # Added success message
    return True
# -----------------------------------------------------

# ---------------------- main loop --------------------
def handle_disconnection(client, addr):
    logging.info(f"Client {addr} disconnected.")
    client.close()

def authenticate_client(client):
    send_plain(client, 'Login or Reg')
    while True:
        mode = recv_decoded(client)
        if mode.lower() in {'quit', 'exit'}:
            return

        send_plain(client, 'USER')
        username = sanitize(recv_decoded(client))
        if username.lower() in {'quit', 'exit'}:
            return

        send_plain(client, 'PW')
        password = recv_decoded(client)
        if password.lower() in {'quit', 'exit'}:
            return

        if mode == 'Login':
            if login(username, password, client):
                return True, username
        elif mode == 'Register':
            if register(username, password, client):
                return True, username
        else:
            send_plain(client, 'Bad mode')

        send_plain(client, 'Authentication Failed')

while True:
    client, addr = server.accept()
    logging.info(f"Connected: {addr}")

    authenticated, username = authenticate_client(client)
    if not authenticated:
        handle_disconnection(client, addr)
        continue

    send_plain(client, 'Authenticated')
    clients[client] = username

    # Send chat history to the new client
    for _, r in chathistory_df.iterrows():
        send_plain(client, f"\n{pd.to_datetime(r.timestamp):%H:%M} | {r.user} : {r.message}")

    broadcast(f"{username} joined the Chat!")
    threading.Thread(target=handle_client, args=(client,), daemon=True).start()
