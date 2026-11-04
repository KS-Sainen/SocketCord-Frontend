import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import QThread, Signal, Slot

from styles import APP_STYLESHEET
from network import SocketCordNetwork
from models import RequestCord
from login_page import LoginPage
# from chat_page import ChatPage

# method codes
POST_MTDC = 112233445
GET_MTDC = 354984100
PATCH_MTDC = 943742156

# font loader
def load_fonts():
    # pathing
    base_dir = Path(__file__).resolve().parent
    font_path_main = base_dir / "fonts" / "SourceSans3-VariableFont_wght.ttf"
    font_path_italic = base_dir / "fonts" / "SourceSans3-Italic-VariableFont_wght.ttf"
    # register it all
    if not font_path_main.exists():
        print(f"Default font file missing at {font_path_main}. This is very sad.")
    if not font_path_italic.exists():
            print(f"Italic font file missing at {font_path_italic}. This is very sad.")

    font_id = QFontDatabase.addApplicationFont(str(font_path_main))
    # print(font_id)
    if font_id == -1:
        print(f"Failed to load font binary from {font_path_main}. This is very sad.")
    else:
        QFontDatabase.addApplicationFont(str(font_path_italic))

    families = QFontDatabase.applicationFontFamilies(font_id)
    if families:
        loaded_family = families[0]
        print(f"[FontEngine] Successfully registered '{loaded_family}'")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SocketCord")
        self.resize(900, 640)

        # load fonts
        load_fonts()

        # Apply global QSS stylesheet
        self.setStyleSheet(APP_STYLESHEET)

        # Networking Manager
        self.network = SocketCordNetwork('127.0.0.1',8080)
        self.req_pending = {} # pending req due to turned off socket
        self.cur_username = ''
        self.cur_password = ''

        # Screen management stack (Index 0: Login, Index 1: Chat)
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        self.login_page = LoginPage()
        # self.chat_page = ChatPage()

        self.stacked_widget.addWidget(self.login_page)
        # self.stacked_widget.addWidget(self.chat_page)

        # Connect signals
        self.login_page.login_requested.connect(self.do_signin)
        self.login_page.signup_requested.connect(self.do_signup)
        self.network.reply_message.connect(self.handle_reply)
        self.network.error.connect(self.handle_connection_error)
        self.network.connection_status.connect(self.handle_connection_result)

        self.worker = None

    # the great ROUTER
    @Slot(int, object)
    def handle_reply(self, status_code, data_obj):
        path = ''
        if 'path' in data_obj:
            path = data_obj['path']
            del data_obj['path']
        # if path explicitly specifies a module, then route to that module
        path_spl = path.split('/')
        if path_spl[0].to_lower() == 'login':
            self.login_page.router(status_code,'/'.join(path_spl[1:]),data_obj)
    @Slot(str, int, str, str)
    def do_signin(self, ip, port, username, password):
        if not self.network.match_conf(ip, port):
            self.network.disconnect()
            self.network.conf(ip, port)
            self.network.connect()
            self.req_pending.insert('login')
            self.cur_password = password
            self.cur_username = username
            return
        if self.network._active():
            req = RequestCord.from_dict(POST_MTDC,'users/login',{"username":username,"password":password})
            self.network.send(req)
    @Slot(str, int, str, str)
    def do_signup(self, ip, port, username, password):
        # Placeholder sign up routing to same connection skeleton
        if not self.network.match_conf(ip, port):
            self.network.disconnect()
            self.network.conf(ip, port)
            self.network.connect()
            self.req_pending.insert('register')
            self.cur_password = password
            self.cur_username = username
            return
        if self.network._active():
            req = RequestCord.from_dict(POST_MTDC,'users',{"username":username,"password":password})
            self.network.send(req)
    @Slot(str)
    def handle_connection_error(self, details):
        self.login_page.set_status(details, False)
    @Slot(bool, str)
    def handle_connection_result(self, success, message):
        if success:
            # clear any queue
            if 'login' in self.req_pending:
                req = RequestCord.from_dict(POST_MTDC,'users/login',{"username":self.cur_username,"password":self.cur_password})
                self.network.send(req)
            if 'register' in self.req_pending:
                req = RequestCord.from_dict(POST_MTDC,'users',{"username":self.cur_username,"password":self.cur_password})
                self.network.send(req)
            self.cur_username = ''
            self.cur_password = ''
            self.req_pending.clear()
        pass

    def closeEvent(self, event):
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())