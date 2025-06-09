# chatflow_pyqt_client.py

import sys
import socket
import threading
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QMessageBox, QStackedWidget
)
from PyQt5.QtCore import Qt

HOST = '127.0.0.1'
PORT = 1234
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((HOST, PORT))

class ChatFlowClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChatFlow Login")
        self.setFixedSize(500, 400)

        self.username = ''
        self.password = ''
        self.email = ''
        self.auth_mode = 'Login'

        self.stack = QStackedWidget(self)
        self.setCentralWidget(self.stack)

        self.loginWidget = self.build_login_ui()
        self.signupWidget = self.build_signup_ui()

        self.stack.addWidget(self.loginWidget)
        self.stack.addWidget(self.signupWidget)

    def build_login_ui(self):
        widget = QWidget()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Login to ChatFlow", alignment=Qt.AlignCenter))
        self.loginUserField = QLineEdit()
        self.loginUserField.setPlaceholderText("Username")
        layout.addWidget(self.loginUserField)

        self.loginPassField = QLineEdit()
        self.loginPassField.setPlaceholderText("Password")
        self.loginPassField.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.loginPassField)

        loginBtn = QPushButton("Login")
        loginBtn.clicked.connect(self.login)
        layout.addWidget(loginBtn)

        signupLink = QPushButton("Sign Up")
        signupLink.clicked.connect(lambda: self.stack.setCurrentWidget(self.signupWidget))
        layout.addWidget(signupLink)

        widget.setLayout(layout)
        return widget

    def build_signup_ui(self):
        widget = QWidget()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Sign Up to ChatFlow", alignment=Qt.AlignCenter))
        self.signupUserField = QLineEdit()
        self.signupUserField.setPlaceholderText("Username")
        layout.addWidget(self.signupUserField)

        self.signupEmailField = QLineEdit()
        self.signupEmailField.setPlaceholderText("Email")
        layout.addWidget(self.signupEmailField)

        self.signupPassField = QLineEdit()
        self.signupPassField.setPlaceholderText("Password")
        self.signupPassField.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.signupPassField)

        confirmBtn = QPushButton("Sign Up")
        confirmBtn.clicked.connect(self.signup)
        layout.addWidget(confirmBtn)

        cancelBtn = QPushButton("Cancel")
        cancelBtn.clicked.connect(lambda: self.stack.setCurrentWidget(self.loginWidget))
        layout.addWidget(cancelBtn)

        widget.setLayout(layout)
        return widget

    def login(self):
        self.auth_mode = 'Login'
        self.username = self.loginUserField.text()
        self.password = self.loginPassField.text()
        threading.Thread(target=self.receive).start()

    def signup(self):
        self.auth_mode = 'Register'
        self.username = self.signupUserField.text()
        self.email = self.signupEmailField.text()
        self.password = self.signupPassField.text()
        threading.Thread(target=self.receive).start()

    def receive(self):
        try:
            while True:
                message = client.recv(1024).decode()
                if message == 'Login or Reg':
                    client.send(self.auth_mode.encode())
                elif message == 'USER':
                    client.send(self.username.encode())
                elif message == 'PW':
                    client.send(self.password.encode())
                elif message == 'EMAIL':
                    client.send(self.email.encode())
                elif message == 'Authenticated':
                    self.show_message("Success", "Login successful!")
                    break
                elif message == 'Authentication Failed':
                    self.show_message("Failed", "Login failed.")
                    break
                else:
                    print(message)
        except Exception as e:
            print(f"Error: {e}")

    def show_message(self, title, text):
        QMessageBox.information(self, title, text)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ChatFlowClient()
    window.show()
    sys.exit(app.exec_())
