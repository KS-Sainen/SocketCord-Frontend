import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget
from PySide6.QtCore import QThread, Signal, Slot

from styles import APP_STYLESHEET
from network import SocketCordNetwork
from models import RequestCord
from login_page import LoginPage
# from chat_page import ChatPage

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SocketCord")
        self.resize(900, 640)

        # Apply global QSS stylesheet
        self.setStyleSheet(APP_STYLESHEET)

        # Networking Manager
        self.network = SocketCordNetwork()

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
        if self.network._active():
            req = RequestCord.from_dict(67,'users/login',{"username":username,"password":password})
            self.network.send(req)
    @Slot(str, int, str, str)
    def do_signup(self, ip, port, username, password):
        # Placeholder sign up routing to same connection skeleton
        if not self.network.match_conf(ip, port):
            self.network.disconnect()
            self.network.conf(ip, port)
            self.network.connect()
        if self.network._active():
            req = RequestCord.from_dict(67,'users',{"username":username,"password":password})
            self.network.send(req)
    @Slot(str)
    def handle_connection_error(self, details):
        pass
    @Slot(bool, str)
    def handle_connection_result(self, success, message):
        pass

    def closeEvent(self, event):
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())