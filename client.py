#!/usr/bin/env python3
"""
Terminal-only ChatFlow client.
Re-implements the old GUI logic using stdin/stdout and keeps the
handshake that the server already understands:

  • Server → "Login or Reg"         → client sends "Login"/"Register"
  • Server → "USER" / "PW" / "EMAIL"→ client replies with credentials
  • Server → auth result strings    → client prints status

After authentication every line you enter is sent as a chat message.
Type  `exit`  or  `quit`  to close the connection.
"""

import argparse
import getpass
import socket
import threading
import sys

BUF_SIZE = 1024
HOST, PORT = "192.168.1.63", 1234

def recv_loop(sock, creds):
    """Handle all server traffic in a background thread."""
    while True:
        try:
            data = sock.recv(BUF_SIZE)
            if not data:
                print("[INFO] Disconnected by server.")
                break

            msg = data.decode().strip()
            if msg == "Login or Reg":
                sock.sendall(creds["mode"].encode())
            elif msg == "USER":
                sock.sendall(creds["user"].encode())
            elif msg == "PW":
                sock.sendall(creds["password"].encode())
            elif msg in ("Authenticated", "Registration Successful"):
                print(f"[SUCCESS] {msg}")
            elif msg == "Authentication Failed":
                print("[ERROR] Authentication failed; closing client.")
                sock.close()
                sys.exit(1)
            elif msg == "User does not exist":
                print("[ERROR] The username you entered does not exist.")
            elif msg == "Incorrect Password":
                print("[ERROR] The password you entered is incorrect. Please try again.")
                creds["password"] = getpass.getpass("Password: ").strip()
                sock.sendall(creds["password"].encode())
            elif msg == "Invalid registration data":
                print("[ERROR] Registration failed due to invalid data. Please check your inputs.")
            elif msg == "User already exist":
                print("[ERROR] The username is already taken. Please choose a different one.")
            elif msg == "Bad mode":
                print("[ERROR] Invalid mode selected. Please restart the client and choose 'Login' or 'Register'.")
            else:
                # Display chat history or new chat messages
                print(msg)
        except Exception as exc:
            print(f"[ERROR] {exc}")
            break


def main():
    ap = argparse.ArgumentParser(description="Terminal ChatFlow client")
    ap.add_argument("--host", default="127.0.0.1", help="Server IP")
    ap.add_argument("--port", type=int, default=1234, help="Server TCP port")
    args = ap.parse_args()

    # Interactive credential gathering
    mode = input("Type Login or Register: ").strip().title()
    while mode not in {"Login", "Register"}:
        mode = input("Please enter exactly 'Login' or 'Register': ").strip().title()

    user = input("Username: ").strip()
    password = getpass.getpass("Password: ").strip()

    creds = {"mode": mode, "user": user, "password": password}

    # Connect to server
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    print(f"[INFO] Connected to {HOST}:{PORT}")

    # Start receiver thread
    threading.Thread(target=recv_loop, args=(sock, creds), daemon=True).start()

    # Sender loop
    try:
        while True:
            line = input()
            if line.lower() in {"exit", "quit"}:
                break
            sock.sendall(line.encode())
    finally:
        sock.close()
        print("[INFO] Connection closed.")


if __name__ == "__main__":
    main()
