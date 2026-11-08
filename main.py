import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import QTimer, Slot

from styles import APP_STYLESHEET
from network import SocketCordNetwork
from models import RequestCord
from login_page import LoginPage
from chat_page import ChatPage
from api import Api, SideChannel, POST

# why the server ended the session ("reason" of login/revoked) -> shown on the login page
REVOKED_TEXT = {
    "logged_in_elsewhere": "You were logged out: this account logged in somewhere else.",
    "password_changed": "You were logged out: the password of this account was changed.",
    "logged_out": "You were logged out.",
    "expired": "Your session expired. Please log in again.",
    "too_many_connections": "You were logged out: too many connections for this account.",
}


# session storage
class Session:
    """The logged-in account: the two ids that go into every RequestCord header."""

    def __init__(self, user_id, token):
        self.user_id = str(user_id)
        self.token = str(token)


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
        print(f"[FontEngine] Successfully registered '{families[0]}'")


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
        self.network = SocketCordNetwork('127.0.0.1', 8080)
        self.api = Api(self.network)            # rid -> callback matching, server pushes
        self.side = SideChannel(self.network)   # second connection for the slow AI summary
        self.pending = None # pending req due to turned off socket
        self.session = None
        self._attempt = 0                       # bumps on every login / sign-up / logout: late replies are ignored
        self._auth_busy = False                 # a sign-up / login is on its way

        # Screen management stack (Index 0: Login, Index 1: Chat)
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        self.login_page = LoginPage()
        self.chat_page = ChatPage()
        self.chat_page.attach(self.api, self.side)

        self.stacked_widget.addWidget(self.login_page)
        self.stacked_widget.addWidget(self.chat_page)

        # Connect signals
        self.login_page.login_requested.connect(self.do_signin)
        self.login_page.signup_requested.connect(self.do_signup)
        self.chat_page.logout_requested.connect(self.do_logout)
        self.network.reply_message.connect(self.handle_reply)
        self.network.error.connect(self.handle_connection_error)
        self.network.connection_status.connect(self.handle_connection_result)
        self.api.session_invalid.connect(self._on_session_invalid)
        self.api.on("login/revoked", self._on_session_revoked)

        self.worker = None

    # screen swapping
    def show_chat_page(self, user):
        self.chat_page.start_session(user, self.session)
        self.stacked_widget.setCurrentWidget(self.chat_page)

    # every reply and push goes through the dispatcher (api.py), which hands it to the callback
    # of the request with the same "rid", or to the push handlers
    # the great ROUTER
    @Slot(int, object)
    def handle_reply(self, status_code, data_obj):
        self.api.handle_reply(status_code, data_obj)

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
        """Log out button: POST users/logout, then disconnect and show the login page."""
        # banish back to login page
        if self.session is None:
            self._end_session()
            return
        attempt = self._attempt

        def finish(*_):
            if attempt == self._attempt:        # once, and not after a newer login
                self._end_session()

        self.api.request(POST, 'users/logout', ok=finish, error=finish)
        QTimer.singleShot(2000, finish)         # the server did not answer: leave anyway

    def _end_session(self, message=""):
        """Back to the login page. Forgets the session and disconnects."""
        self.pending = None
        self._attempt += 1
        self._auth_busy = False
        self.session = None
        RequestCord.clear_auth()
        self.chat_page.reset()                  # first: late replies for the old page are ignored
        self.side.close()
        self.network.disconnect()
        self.network.wait()
        self.api.fail_all("Logged out")
        self.login_page.reset_form()
        if message:
            self.login_page.set_status(message, False)
        self.stacked_widget.setCurrentWidget(self.login_page)

    # sending without knowing there might be a connection
    def _login_page_send(self, cmd, ip, port, username, password):
        """LOG IN / SIGN UP, whether or not the socket is open yet."""
        net = self.network
        if net.connected and net.running and net.match_conf(ip, port):
            if self._auth_busy:
                return                          # a request is on its way (double click): it answers for both
            self.pending = (cmd, username, password)
            self._flush_pending()
            return
        self.pending = (cmd, username, password)
        self.login_page.set_status(f"Connecting to {ip}:{port}...", True)
        if net._active():
            if net.match_conf(ip, port):
                return
            net.disconnect()
            net.wait()
        # conf failed
        if not net.conf(ip, port):
            return
        net.open_connection()

    def _flush_pending(self):
        """Sends the one sign-up / login request. The password goes in the body and is dropped
        here, so nothing in the client holds it once the request is out."""
        if self.pending is None:
            return
        kind, username, password = self.pending
        self.pending = None
        self._attempt += 1
        attempt = self._attempt
        self._auth_busy = True                  # before the send: a send error clears it at once
        body = {"username": username, "password": password}
        del password
        if kind == 'login':
            self.login_page.set_status("Logging in...", True)
            self.api.request(POST, 'users/login', body, auth=False,
                             ok=lambda d: self._login_done(attempt, d),
                             error=lambda e: self._auth_failed(attempt, e))
        else:
            self.login_page.set_status("Signing up...", True)
            self.api.request(POST, 'users', body, auth=False,
                             ok=lambda d: self._signup_done(attempt, d),
                             error=lambda e: self._auth_failed(attempt, e))
        body.clear()

    def _login_done(self, attempt, data):
        if attempt != self._attempt:
            return
        self._auth_busy = False
        self.session = Session(data["user_id"], data["session_token"])
        RequestCord.set_auth(data["user_id"], data["session_token"])
        self.login_page.reset_buttons()
        self.login_page.set_status("", True)
        self.login_page.password_input.clear()
        self.show_chat_page(data)               # the reply carries username and colours

    def _signup_done(self, attempt, data):
        if attempt != self._attempt:
            return
        self._auth_busy = False
        self.login_page.router(200, 'login/created', data)

    def _auth_failed(self, attempt, err):
        if attempt != self._attempt:
            return
        self._auth_busy = False
        self.login_page.reset_buttons()
        self.login_page.set_status(err.message, False)

    def _on_session_revoked(self, data):
        if self.session is not None:
            self._end_session(REVOKED_TEXT.get(data.get("reason"), "You were logged out."))

    @Slot(str)
    def _on_session_invalid(self, message):
        if self.session is not None:
            self._end_session(f"{message}")

    # connection handlers
    @Slot(str)
    def handle_connection_error(self, details):
        if self.session is not None:
            self.chat_page.show_notice(details)
            return
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
        self.api.fail_all(message)              # nothing will answer the calls still waiting
        if message == "Disconnected":
            return
        if self.session is not None:
            self._end_session(f"Lost the connection to the server ({message}).")
            return
        if self.pending is not None:
            text = f"Can't connect to {self.network.host}:{self.network.port} ({message})"
        else:
            text = message
        self.pending = None
        self.login_page.reset_buttons()
        self.login_page.set_status(text, False)

    def closeEvent(self, event):
        self.side.close()
        self.network.disconnect()
        self.network.wait()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
