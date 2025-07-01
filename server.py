#!/usr/bin/env python3
"""
ChatFlow LAN Server
===================

Key Points
----------
* Supports login or registration with a simple password rule (≥ 6 chars).
* Persists users and chat history to CSV files for easy inspection.
* Encrypts every payload using a shared Fernet key.
* Uses one background thread per connected client.
* All console debugging prints have been removed; internal events are
  recorded via the ``logging`` module.
"""

from __future__ import annotations
import socket
import threading
import logging
import datetime as _dt
import os
import re
from typing import Optional, Dict

import pandas as pd
from cryptography.fernet import Fernet, InvalidToken

# ────────────────────────────── Configuration ──────────────────────────────
HOST, PORT        = "0.0.0.0", 1234
MAX_MSG_LEN       = 1024                       # maximum bytes per TCP read
MAX_FIELD_LEN     = 256                        # truncate oversized user input
USER_CSV          = "userdata.csv"             # credential store
CHAT_CSV          = "chathistory.csv"          # chat log
KEY_FILE          = "fernet.key"               # shared encryption key
LOG_FILE          = "server.log"               # server runtime log
# ────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ─────────────────────────────── Fernet Key ────────────────────────────────
def _load_or_create_key() -> bytes:
    """
    Load an existing 44-byte Fernet key or create a new one on first run.
    """
    if os.path.exists(KEY_FILE):
        key = open(KEY_FILE, "rb").read()
        if len(key) == 44:
            logging.info("Fernet key loaded")
            return key
        logging.warning("Invalid key length – regenerating")
    key = Fernet.generate_key()
    open(KEY_FILE, "wb").write(key)
    logging.info("New Fernet key generated")
    return key


fernet = Fernet(_load_or_create_key())

# ────────────────────────────── CSV Utilities ──────────────────────────────
def _safe_csv(path: str, cols: list[str]) -> pd.DataFrame:
    """
    Ensure a CSV file exists with the expected columns; create a blank one
    when missing or corrupted.
    """
    if os.path.exists(path):
        df = pd.read_csv(path)
        if list(df.columns) == cols:
            return df
        logging.warning("Corrupted %s – recreating", path)
    df = pd.DataFrame(columns=cols)
    df.to_csv(path, index=False)
    return df


users_df  = _safe_csv(USER_CSV,  ["username", "password"])
chat_df   = _safe_csv(CHAT_CSV,  ["timestamp", "user", "message"])

def _save_users() -> None:
    """Persist the in-memory user table to disk."""
    users_df.to_csv(USER_CSV, index=False)


def _append_history(ts: _dt.datetime, user: str, msg: str) -> None:
    """Add a line to the in-memory chat log and flush to disk."""
    global chat_df
    chat_df = pd.concat(
        [chat_df,
         pd.DataFrame([[ts, user, msg[:MAX_FIELD_LEN]]],
                      columns=chat_df.columns)],
        ignore_index=True)
    chat_df.to_csv(CHAT_CSV, index=False)

# ─────────────────────────────– Helper Functions ───────────────────────────
_sanitize = lambda t: re.sub(r"[^\w@\.\- ]", "", t)[:MAX_FIELD_LEN]
_valid_user = lambda u: 0 < len(u) <= MAX_FIELD_LEN and u.isalnum()
_valid_pw   = lambda p: 6 <= len(p) <= MAX_FIELD_LEN        # relaxed rule


def _decrypt_safe(blob: bytes) -> bytes:
    """Try Fernet decryption; return b'' on failure."""
    try:
        return fernet.decrypt(blob)
    except (InvalidToken, ValueError):
        return b""


def _recv_line(sock: socket.socket) -> str:
    """Read and decode a single encrypted line from client."""
    raw = sock.recv(MAX_MSG_LEN)
    if not raw:
        return ""
    text = (_decrypt_safe(raw) or raw).decode(errors="ignore")
    return text.strip()[:MAX_FIELD_LEN]


def _send_line(sock: socket.socket, text: str) -> None:
    """Encrypt and send a single line to client."""
    sock.sendall(fernet.encrypt(f"{text}\n".encode()))


def _broadcast(text: str, sender: Optional[str] = None) -> None:
    """
    Send a message to every connected client.
    If *sender* supplied, the string "sender: text" is broadcast.
    """
    if sender:
        text = f"{sender}: {text}"
    tagged = f"{_dt.datetime.now():%H:%M} | {text}"
    for cli in list(clients):
        try:
            _send_line(cli, tagged)
        except OSError as exc:
            logging.error("Broadcast failure: %s", exc)
            cli.close()
            clients.pop(cli, None)

# ───────────────────────────── Authentication ──────────────────────────────
def _login(user: str, pw: str, sock: socket.socket) -> bool:
    row = users_df[users_df.username == user]
    if row.empty:
        _send_line(sock, "User does not exist")
        return False
    if row.iloc[0].password != pw:
        _send_line(sock, "Incorrect password")
        return False
    return True


def _register(user: str, pw: str, sock: socket.socket) -> bool:
    global users_df
    if not (_valid_user(user) and _valid_pw(pw)):
        _send_line(sock, "Bad registration data")
        return False
    if not users_df[users_df.username == user].empty:
        _send_line(sock, "User already exists")
        return False
    users_df = pd.concat([users_df,
                          pd.DataFrame([[user, pw]],
                                       columns=["username", "password"])],
                         ignore_index=True)
    _save_users()
    _send_line(sock, "Registration successful")
    return True


def _authenticate(sock: socket.socket) -> tuple[bool, Optional[str]]:
    """
    Interactively authenticate a client.
    Returns (success_flag, username_or_None).
    """
    while True:
        _send_line(sock, "Login or Reg")
        mode = _recv_line(sock)
        if not mode:
            return False, None

        _send_line(sock, "USER")
        user = _sanitize(_recv_line(sock))

        _send_line(sock, "PW")
        pw = _recv_line(sock)

        if mode == "Login" and _login(user, pw, sock):
            return True, user
        if mode == "Register" and _register(user, pw, sock):
            return True, user

        _send_line(sock, "Authentication failed")

# ────────────────────────────── Client Thread ──────────────────────────────
def _handle_client(sock: socket.socket) -> None:
    """Serve a single authenticated client until disconnection."""
    username = clients.get(sock, "?")
    try:
        while True:
            msg = _recv_line(sock)
            if not msg:
                break
            _append_history(_dt.datetime.now(), username, msg)
            _broadcast(msg, sender=username)
    except Exception as exc:                     # noqa: BLE001
        logging.error("Handler error for %s: %s", username, exc)
    finally:
        sock.close()
        clients.pop(sock, None)
        _broadcast(f"{username} left the chat!")

# ─────────────────────────────── Main Server ───────────────────────────────
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen()
logging.info("Server listening on %s:%d", HOST, PORT)

clients: Dict[socket.socket, str] = {}

while True:
    client_sock, addr = server.accept()
    logging.info("Connection from %s:%d", *addr)

    authenticated, user = _authenticate(client_sock)
    if not authenticated:
        client_sock.close()
        continue

    _send_line(client_sock, "Authenticated")
    clients[client_sock] = user

    # send existing history to the newcomer
    for _, row in chat_df.iterrows():
        _send_line(client_sock,
                   f"{pd.to_datetime(row.timestamp):%H:%M} | {row.user}: {row.message}")

    _broadcast(f"{user} joined the chat!")
    threading.Thread(target=_handle_client, args=(client_sock,), daemon=True).start()
