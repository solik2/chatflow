````markdown
# ChatFlow

**ChatFlow** is a lightweight, LAN-only chat system written in pure Python.  
It provides real-time messaging with end-to-end payload encryption, basic
authentication, and a simple cross-platform GUI—all without relying on cloud
services or heavyweight frameworks.

---

## Table of Contents
1. [Key Features](#key-features)  
2. [How It Works](#how-it-works)  
3. [Requirements](#requirements)  
4. [Installation](#installation)  
5. [Quick Start](#quick-start)  
6. [Configuration](#configuration)  
7. [Project Layout](#project-layout)  
8. [Troubleshooting](#troubleshooting)  
9. [Roadmap](#roadmap)  
10. [Security Notes](#security-notes)  
11. [License](#license)  

---

## Key Features
| Feature | Details |
|---------|---------|
| **End-to-End Encryption** | All payloads are wrapped in a shared [Fernet](https://github.com/fernet/spec) key before they leave any host. |
| **CSV Persistence** | Users and chat history are written to plain-text CSV files for easy inspection and backups. |
| **Cross-Platform GUI** | Built with Tkinter + [`ttkbootstrap`](https://github.com/israel-dryer/ttkbootstrap); works on Windows, macOS and Linux. |
| **Minimal Footprint** | Two Python files (<300 LOC each) and a single runtime dependency. |
| **Hot-Reload Chat Log** | New clients receive the full chat history on join. |

---

## How It Works
1. **Shared Key** – On first server launch a 44-byte `fernet.key` is generated and
   must be copied to every client folder.
2. **Authentication** – Clients choose *Login* or *Register*.  
   Password rule: **≥ 6 characters**, ASCII only (stored in `userdata.csv`).
3. **Message Flow**  
   ```text
   Client GUI  →  send_q  →  ChatClient Thread  →  Fernet encrypt  →  TCP socket
   Server socket  →  Fernet decrypt  →  broadcast()  →  encrypt  →  all sockets
   ChatClient Thread  →  msg_q  →  GUI poll 100 ms  →  text area update
````

4. **Persistence** – Every accepted message is appended to `chathistory.csv`
   (timestamp, user, message).
   Chat history is replayed to newcomers in join order.

---

## Requirements

* Python **3.11** or newer
* LAN connectivity between server host and client hosts
* A terminal / console capable of running Python scripts

---

## Installation

```bash
# 1) Clone
git clone https://github.com/your-org/chatflow.git
cd chatflow

# 2) Create (optional) venv
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3) Install dependencies
pip install -r requirements.txt
```

---

## Quick Start

### 1️⃣  Start the Server

```bash
python server.py
# default bind address : 0.0.0.0:1234
```

The server will generate `fernet.key`, `userdata.csv`, and `chathistory.csv`
if they don’t exist.

### 2️⃣  Distribute the Key

Copy `fernet.key` to the **same directory** as `client.py` on each client PC
(using a safe channel such as a USB stick).

### 3️⃣  Launch a Client

```bash
python client.py
```

1. Choose **Register** and provide a username + password (first time).
2. On subsequent logins choose **Login**.
3. After the status line shows **Authenticated**, start chatting!

---

## Configuration

| Parameter       | File(s)                  | Default           | Description                           |
| --------------- | ------------------------ | ----------------- | ------------------------------------- |
| `HOST`, `PORT`  | `server.py`, `client.py` | `0.0.0.0`, `1234` | Server bind / client connect address  |
| `KEY_FILE`      | both                     | `fernet.key`      | Shared Fernet key path                |
| `MAX_MSG_LEN`   | `server.py`              | `1024`            | Socket read size (bytes)              |
| `MAX_FIELD_LEN` | `server.py`              | `256`             | Max length for any user-supplied text |

Change constants at the top of each script to suit your network.

---

## Project Layout

```text
chatflow/
├── server.py            # encrypted chat server
├── client.py            # Tkinter client
├── fernet.key           # generated on first server run
├── userdata.csv         # username,password
├── chathistory.csv      # timestamp,user,message
├── server.log           # runtime log (INFO level)
├── requirements.txt     # ttkbootstrap, pandas, cryptography
└── README.md            # this file
```

---

## Troubleshooting

| Symptom                              | Possible Cause & Fix                                                      |
| ------------------------------------ | ------------------------------------------------------------------------- |
| **Clients hang on "Connecting…"**    | Wrong `HOST` / `PORT` or firewall blocking port 1234.                     |
| **Decrypt failed** (console message) | Client and server use different `fernet.key` files—copy the key again.    |
| **Unicode errors in chat**           | Non-ASCII input > 256 chars is truncated; stick to ASCII for now.         |
| **CSV corrupted**                    | Delete the offending file; the server recreates a fresh CSV with headers. |

---

## Roadmap

* **Password hashing** – replace plaintext storage with `bcrypt` or `argon2`.
* **File transfer UI** – expose the existing backend hooks in the GUI.
* **User list** – real-time display of online participants.
* **Automated tests** – unit tests for handshake, broadcast and persistence.

---

## Security Notes

* Fernet provides confidentiality and integrity but **not origin authentication**;
  any LAN attacker with the shared key could inject messages.
* Passwords are stored in clear text in `userdata.csv`; **never** deploy this code
  unmodified to the internet.
* For small classrooms & demos the threat model is acceptable; for anything more,
  add **password hashing** and a proper **key-exchange** or per-user keys.

---
