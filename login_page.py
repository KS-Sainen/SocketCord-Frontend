from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFrame, QGridLayout
)
from PySide6.QtCore import Signal, Qt

# const
CARD_WIDTH = 480

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
        column = QWidget()
        column.setFixedWidth(CARD_WIDTH)
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(0)

        # WELCOME Header Tag
        header_label = QLabel("WELCOME")
        header_label.setObjectName("WelcomeTag")
        header_label.setFixedSize(170, 38)
        column_layout.addWidget(header_label, alignment=Qt.AlignLeft)

        # card
        card_frame = QFrame()
        card_frame.setObjectName("PanelFrame")
        card_layout = QVBoxLayout(card_frame)
        card_layout.setContentsMargins(12, 12, 12, 14)
        card_layout.setSpacing(12)

        # Title instruction
        title_lbl = QLabel("Please sign into the desired server")
        title_lbl.setObjectName("LoginTitle")
        card_layout.addWidget(title_lbl)

        # Form Inputs
        self.ip_input = QLineEdit("127.0.0.1")
        self.port_input = QLineEdit("8080")
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)

        form_layout = QGridLayout()
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(10)
        form_layout.setColumnMinimumWidth(0, 120)
        form_layout.setColumnStretch(1, 1)
        self.form_rows = (
            ("Backend IP", self.ip_input),
            ("Port", self.port_input),
            ("Username", self.username_input),
            ("Password", self.password_input),
        )
        for row, (text, field) in enumerate(self.form_rows):
            field.setProperty('status','ok')
            form_layout.addWidget(QLabel(text), row, 0)
            form_layout.addWidget(field, row, 1)
        card_layout.addLayout(form_layout)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(14, 4, 14, 0)
        self.signup_btn = QPushButton("SIGN UP")
        self.login_btn = QPushButton("LOG IN")
        for btn in (self.signup_btn, self.login_btn): # all button setting
            btn.setProperty('status','pending')
            btn.setFixedSize(160, 56)
        btn_layout.addWidget(self.signup_btn)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.login_btn)

        column_layout.addLayout(btn_layout)

        # Status text below container
        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setProperty("state", "ok")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.status_label.setContentsMargins(0, 6, 0, 0)
        self.status_label.setMinimumHeight(66)
        column_layout.addWidget(self.status_label)

        main_layout.addWidget(column)

        # Connect button clicks
        self.login_btn.clicked.connect(self.handle_login_click)
        self.signup_btn.clicked.connect(self.handle_signup_click)

    # form validation
    def _read_form(self):
        errs = [] # error array
        # reset status
        for row, (text, field) in enumerate(self.form_rows):
            field.setProperty('status','ok')
        # validate things
        ip = self.ip_input.text().strip()
        if not ip:
            self.ip_input.setProperty('status','error')
            errs.append('Backend IP')
        try:
            port = int(self.port_input.text().strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.port_input.setProperty('status','error')
            errs.append('Valid Port (1-65535)')
        username = self.username_input.text().strip()
        if not username:
            self.username_input.setProperty('status','error')
            errs.append('Username')
        # raw text
        password = self.password_input.text()
        if not password:
            self.password_input.setProperty('status','error')
            errs.append('Password')
        # error array must be empty
        if len(errs) == 0:
            return ip, port, username, password
        else:
            self.set_status(f"Please enter the following: {errs.join(', ')}", False)
            return None

    # handler
    def handle_login_click(self):
        form = self._read_form()
        if form:
            self.login_btn.setProperty('status','processing')
            self.login_requested.emit(*form)
 
    def handle_signup_click(self):
        form = self._read_form()
        if form:
            self.signup_btn.setProperty('status','processing')
            self.signup_requested.emit(*form)

    # router functions
    def router(self, status_code, path, data_obj):
        # path_spl = path.split('/')
        # honestly, only the created user reply reaches here, so only handle by the connection
        if status_code == 200:
            self.set_status("User successfully created!", True)
    def set_status(self, text: str, success: bool = True):
        # colour comes from the stylesheet ([state="ok"] -> blue, otherwise red)
        self.status_label.setProperty("state", "ok" if success else "error")
        style = self.status_label.style()
        style.unpolish(self.status_label)
        style.polish(self.status_label)
        self.status_label.setText(text)