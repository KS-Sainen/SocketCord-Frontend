import sys
import socket
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget
from PySide6.QtCore import QThread, Signal, Slot

from styles import APP_STYLESHEET
from login_page import LoginPage
# from chat_page import ChatPage

class SocketWorker(QThread):
    """
    Networking skeleton running on a background thread to prevent UI freezing 
    during socket connection handshakes.
    """
    connection_status = Signal(bool, str) # success, message

    def __init__(self, host, port, username, password):
        super().__init__()
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client_socket = None

    def run(self):
        try:
            # SKELETON: Establish TCP socket connection
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(4.0) # 4-second timeout
            self.client_socket.connect((self.host, self.port))
            
            # SKELETON: Placeholder for authentication packet transmission
            # auth_packet = f"AUTH:{self.username}:{self.password}\n"
            # self.client_socket.sendall(auth_packet.encode('utf-8'))
            
            self.connection_status.emit(True, "Connected Successfully!")
        except socket.timeout:
            self.connection_status.emit(False, "Can't Connect: Connection Timed Out")
        except ConnectionRefusedError:
            self.connection_status.emit(False, "Can't Connect: Server Refused Connection")
        except Exception as e:
            self.connection_status.emit(False, f"Not Found / Error: {str(e)}")

    def stop(self):
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
        self.quit()
        self.wait()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SocketCord")
        self.resize(900, 640)

        # Apply global QSS stylesheet
        self.setStyleSheet(APP_STYLESHEET)

        # Screen management stack (Index 0: Login, Index 1: Chat)
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        self.login_page = LoginPage()
        # self.chat_page = ChatPage()

        self.stacked_widget.addWidget(self.login_page)
        # self.stacked_widget.addWidget(self.chat_page)

        # Connect signals
        self.login_page.login_requested.connect(self.initiate_backend_connection)
        self.login_page.signup_requested.connect(self.initiate_signup)

        self.worker = None

    @Slot(str, int, str, str)
    def initiate_backend_connection(self, ip, port, username, password):
        if not username:
            self.login_page.set_status("Unsuccessful: Username is required", success=False)
            return

        self.login_page.set_status("Connecting to backend...", success=True)
        
        if self.worker and self.worker.isRunning():
            self.worker.stop()

        # Kick off background socket worker
        self.worker = SocketWorker(ip, port, username, password)
        self.worker.connection_status.connect(self.handle_connection_result)
        self.worker.start()

    @Slot(str, int, str, str)
    def initiate_signup(self, ip, port, username, password):
        # Placeholder sign up routing to same connection skeleton
        self.initiate_backend_connection(ip, port, username, password)

    @Slot(bool, str)
    def handle_connection_result(self, success, message):
        self.login_page.set_status(message, success=success)
        if success:
            # Transition to Chat Page
            self.stacked_widget.setCurrentIndex(1)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())