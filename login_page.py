from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFrame
)
from PySide6.QtCore import Signal, Qt

class LoginPage(QWidget):
    # Signals emitted to the main application coordinator
    login_requested = Signal(str, int, str, str) # ip, port, username, password
    signup_requested = Signal(str, int, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignCenter)

        # Center card container
        card_frame = QFrame()
        card_frame.setObjectName("PanelFrame")
        card_frame.setFixedSize(450, 410)
        card_layout = QVBoxLayout(card_frame)
        card_layout.setContentsMargins(25, 25, 25, 25)
        card_layout.setSpacing(15)

        # WELCOME Header Tag
        header_label = QLabel("WELCOME")
        header_label.setStyleSheet("background-color: #000000; color: #ffffff; font-weight: bold; font-style: italic; padding: 4px;")
        header_label.setFixedWidth(110)
        card_layout.addWidget(header_label)

        # Title instruction
        title_lbl = QLabel("Please sign into the desired server")
        title_lbl.setStyleSheet("font-weight: bold; font-size: 14pt; border: none;")
        card_layout.addWidget(title_lbl)

        # Form Inputs
        form_layout = QVBoxLayout()
        form_layout.setSpacing(10)

        self.ip_input = QLineEdit("127.0.0.1")
        self.port_input = QLineEdit("8080")
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)

        form_layout.addWidget(QLabel("Backend IP"))
        form_layout.addWidget(self.ip_input)
        form_layout.addWidget(QLabel("Port"))
        form_layout.addWidget(self.port_input)
        form_layout.addWidget(QLabel("Username"))
        form_layout.addWidget(self.username_input)
        form_layout.addWidget(QLabel("Password"))
        form_layout.addWidget(self.password_input)

        card_layout.addLayout(form_layout)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.signup_btn = QPushButton("SIGN UP")
        self.login_btn = QPushButton("LOG IN")
        btn_layout.addWidget(self.signup_btn)
        btn_layout.addWidget(self.login_btn)

        card_layout.addLayout(btn_layout)
        main_layout.addWidget(card_frame)

        # Status text below container
        self.status_label = QLabel("Status Text (Successful / Unsuccessful / Not Found / Can't Connect)")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #666666; font-size: 10pt; border: none;")
        main_layout.addWidget(self.status_label)

        # Connect button clicks
        self.login_btn.clicked.connect(self.handle_login_click)
        self.signup_btn.clicked.connect(self.handle_signup_click)

    def handle_login_click(self):
        ip = self.ip_input.text().strip()
        try:
            port = int(self.port_input.text().strip())
        except ValueError:
            port = 8080
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        self.login_requested.emit(ip, port, username, password)

    def handle_signup_click(self):
        ip = self.ip_input.text().strip()
        try:
            port = int(self.port_input.text().strip())
        except ValueError:
            port = 8080
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        self.signup_requested.emit(ip, port, username, password)

    def set_status(self, text: str, success: bool = True):
        color = "#000000" if success else "#cc0000"
        self.status_label.setStyleSheet(f"color: {color}; font-size: 10pt; border: none; font-weight: bold;")
        self.status_label.setText(text)