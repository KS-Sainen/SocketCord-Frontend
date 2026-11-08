import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import QThread, Signal, Slot

from styles import APP_STYLESHEET
from network import SocketCordNetwork, POST_MTDC, GET_MTDC, PATCH_MTDC
from models import RequestCord
from login_page import LoginPage
from chat_page import ChatPage

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
    # comes in as a string, comes out as a string always

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
        self.pending = None # pending req due to turned off socket

        # Screen management stack (Index 0: Login, Index 1: Chat)
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        self.login_page = LoginPage()
        self.chat_page = ChatPage()

        self.stacked_widget.addWidget(self.login_page)
        self.stacked_widget.addWidget(self.chat_page)

        # Connect signals
        self.login_page.login_requested.connect(self.do_signin)
        self.login_page.signup_requested.connect(self.do_signup)
        self.network.reply_message.connect(self.handle_reply)
        self.network.error.connect(self.handle_connection_error)
        self.network.connection_status.connect(self.handle_connection_result)
        self.chat_page.request.connect(self.handle_request)
        self.chat_page.session_ended.connect(self.handle_session_ended)
        self.chat_page.logout_requested.connect(self.do_logout)

        self.worker = None

    # session storage
    @property
    def cur_user(self):
        return RequestCord.auth_user()
    @cur_user.setter
    def cur_user(self, value):
        RequestCord.set_auth(value, RequestCord.auth_session())
    @property
    def cur_session(self):
        return RequestCord.auth_session()
    @cur_session.setter
    def cur_session(self, value):
        RequestCord.set_auth(RequestCord.auth_user(), value)
    def set_session(self, user_id, session_token):
        """Store both at once (the login flow calls this with the login reply's user_id / session_token)."""
        RequestCord.set_auth(str(user_id), str(session_token))
    def clear_session(self):
        RequestCord.clear_auth()
    def make_request(self, method, url, data=None):
        """Request factory: a RequestCord carrying the stored session."""
        return RequestCord.from_dict(method, url, data)

    # screen swapping
    def show_chat_page(self, username):
        self.chat_page.set_profile(username)
        self.stacked_widget.setCurrentWidget(self.chat_page)
        self.chat_page.load_initial()
    def show_login_page(self, message=None, success=False):
        """Back to the login page; the socket is left as it is."""
        self.pending = None
        self.clear_session()
        self.chat_page.reset()
        self.login_page.reset_form()
        self.stacked_widget.setCurrentWidget(self.login_page)
        if message:
            self.login_page.set_status(message, success)
    @Slot(str)
    def handle_session_ended(self, message):
        """The chat page says the server ended this session (251 / event/session_revoked)."""
        self.show_login_page(message, False)

    # the great ROUTER
    @Slot(int, object)
    def handle_reply(self, status_code, data_obj):
        if not isinstance(data_obj, dict):
            return
        path = str(data_obj.get('path', '')).strip('/')
        # A successful login is returned as "login/success". Failed login and
        # registration requests echo their original URL instead.
        is_auth_reply = (
            path in ('login/success', 'login/created', 'login/logout')
            or (data_obj.get('method') == 'POST' and path in ('users', 'users/login'))
        )
        if is_auth_reply:
            self.login_page.router(status_code, path, data_obj)
            if path == 'login/success' and status_code == 200:
                self.set_session(data_obj['user_id'], data_obj['session_token'])
                self.show_chat_page(data_obj.get('username', ''))
            elif path == 'login/logout' and status_code == 200:
                self.clear_session()
            return
        # Do not strip the first URL component. The chat page also accepts
        # the server's semantic reply paths and asynchronous push paths.
        self.chat_page.router(status_code, path, data_obj)
    # the great EMITTER
    @Slot(RequestCord)
    def handle_request(self, request):
        net = self.network
        if not isinstance(request, RequestCord):
            return
        if not request.has_credentials():
            request.stamp_auth()
        if not request.has_credentials():
            self.show_login_page("You are not logged in.", False)
            return
        if not (net.connected and net.running):
            self.show_login_page("Connection lost. Please log in again.", False)
            return
        if not net.send(request):
            # send() already said why through the error signal. If the socket is still up the
            # request itself was bad: tell the chat page so nothing waits for a reply forever.
            if net.connected and net.running:
                self.chat_page.request_rejected(request, "The request could not be sent.")
    # request factory
    @Slot(str, int, str, str)
    def do_signin(self, ip, port, username, password):
        self._login_page_send('login', ip, port, username, password)
    @Slot(str, int, str, str)
    def do_signup(self, ip, port, username, password):
        # Placeholder sign up routing to same connection skeleton
        self._login_page_send('signup', ip, port, username, password)
    @Slot()
    def do_logout(self):
        # banish back to login page
        net = self.network
        if RequestCord.has_auth() and net.connected and net.running:
            net.send(self.make_request(POST_MTDC, 'users/logout'))
        net.disconnect()
        net.wait()
        self.show_login_page()

    # sending without knowing there might be a connection
    def _login_page_send(self, cmd, ip, port, username, password):
        net = self.network
        self.pending = (cmd, username, password)
        if net.connected and net.running and net.match_conf(ip, port):
            self._flush_pending()
            return
        self.login_page.set_status(f"Connecting to {ip}:{port}...", True)
        if net._active():
            if net.match_conf(ip, port):
                return
            net.disconnect()
            net.wait()
        # conf failed
        if not net.conf(ip, port):
            return
        net.connect()
    def _flush_pending(self):
        if self.pending is None:
            return
        kind, username, password = self.pending
        self.pending = None
        url = 'users/login' if kind == 'login' else 'users'
        req = RequestCord.from_dict(POST_MTDC, url, {"username": username, "password": password})
        self.network.send(req)

    # connection handlers
    @Slot(str)
    def handle_connection_error(self, details):
        self.pending = None
        self.login_page.reset_buttons()
        self.login_page.set_status(details, False)
    @Slot(bool, str)
    def handle_connection_result(self, success, message):
        if success:
            if self.network.connected:
                self.login_page.set_status("", True)
                self._flush_pending()
            return
        if message == "Disconnected":
            return
        if self.stacked_widget.currentWidget() is self.chat_page:
            # the socket died while chatting: nothing can be sent any more
            self.show_login_page(f"Connection lost ({message}). Please log in again.", False)
            return
        if self.pending is not None:
            text = f"Can't connect to {self.network.host}:{self.network.port} ({message})"
        else:
            text = message
        self.pending = None
        self.login_page.reset_buttons()
        self.login_page.set_status(text, False)

    def closeEvent(self, event):
        self.network.disconnect()
        self.network.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())