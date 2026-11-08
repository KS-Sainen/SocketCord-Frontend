import socket, struct, threading, selectors, json, zlib
from PySide6.QtCore import QThread, Signal, Slot
from models import RequestCord

class SocketCordNetwork(QThread):
    connection_status = Signal(bool, str)
    reply_message = Signal(int, object)
    error = Signal(str)

    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.client_socket = None
        self.connected = False
        self.running = False
        self.recv_buffer = bytearray()
        self.selector = selectors.DefaultSelector()
        self._close_reason = 'Disconnected'
        self._send_lock = threading.Lock()
    def match_conf(self, host, port):
        return self.host == host and self.port == port
    def conf(self, host, port):
        if self.running or self.connected:
            self.error.emit("Can't reconfigure connection while it's running!")
            return False
        self.host = host
        self.port = port
        return True
    def _active(self):
        if self.isRunning():
            if self.running:
                return True
            self.wait()
        return False
    def _stop(self, reason):
        if self.running:
            self._close_reason = reason
            self.running = False
        if self.client_socket is not None:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    def disconnect(self):
        self._stop('Disconnected')
    def stop(self):
        self.disconnect()
    def on_closed(self):
        self._stop('Connection Closed')
    # Not named connect(): overriding QObject.connect breaks `signal.connect(slot)` on this
    # object in some PySide6 versions (6.8 calls the Python method).
    def open_connection(self):
        if self._active():
            self.error.emit("Already Connected or Connecting")
            return
        self.recv_buffer = bytearray()
        self._close_reason = "Disconnected"
        self.running = True
        self.start()
    def run(self):
        sel = None
        cur_socket = None
        try:
            try:
                cur_socket = socket.create_connection((self.host, self.port), timeout=4.0)
            except socket.timeout:
                self.connection_status.emit(False, "Connection Timed Out")
                return
            except ConnectionRefusedError:
                self.connection_status.emit(False, "Connection Refused")
                return
            except Exception as e:
                self.connection_status.emit(False, f"Connection Error: {str(e)}")
                return
            sel = selectors.DefaultSelector()
            sel.register(
                cur_socket, 
                selectors.EVENT_READ, 
                data=self.handle_read
            )
            self.client_socket = cur_socket
            self.connected = True
            self.connection_status.emit(True, "Connected!")
            while self.running:
                for key, mask in sel.select(timeout=1.0):
                    key.data(key.fileobj, mask)
        except Exception as e:
            self.error.emit(f"Socket Event Loop Error: {e}")
            self._close_reason = "Connection Closed due to Error in Socket Event"
        finally:
            self.running = False
            self.connected = False
            self.client_socket = None
            if sel is not None:
                try:
                    sel.close()
                except Exception:
                    pass
            if cur_socket is not None:
                try:
                    cur_socket.close()
                except Exception:
                    pass
            self.recv_buffer = bytearray()
            self.connection_status.emit(False, self._close_reason)
    def handle_read(self, sock: socket.socket, mask=None):
        try:
            data = sock.recv(65536)
        except BlockingIOError:
            return
        except OSError as e:
            self.error.emit(f"Packet Receiving Error: {str(e)}")
            self._stop('Connection Lost')
            return
        if not data:
            self.on_closed()
            return
        self.recv_buffer.extend(data)
        self.proc_buffer()
    def proc_buffer(self):
        HEADER_SZ = 8
        while len(self.recv_buffer) >= HEADER_SZ:
            status_code = self.recv_buffer[0]
            reply_sz = int.from_bytes(self.recv_buffer[1:4],byteorder='big')
            checksum = int.from_bytes(self.recv_buffer[4:8], 'big')
            packet_sz = HEADER_SZ + reply_sz
            if len(self.recv_buffer) < packet_sz:
                break
            raw_msg = bytes(self.recv_buffer[HEADER_SZ:packet_sz])
            del self.recv_buffer[:packet_sz]
            if zlib.crc32(raw_msg) != checksum:
                self.error.emit("Reply Checksum Mismatch")
                continue
            try:
                str_msg = raw_msg.decode('utf-8')
                obj = json.loads(str_msg)
            except Exception as e:
                self.error.emit(f'JSON Parsing Error: {str(e)}')
                continue
            self.reply_message.emit(status_code,obj)

    def send(self, req:RequestCord):
        if not self.connected or self.client_socket is None:
            self.error.emit("Not connected!")
            return False
        try:
            with self._send_lock:
                self.client_socket.sendall(req.pack())
            return True
        except ValueError as e:
            self.error.emit(f'Invalid Request: {e}')
            return False
        except Exception as e:
            self.error.emit(f'Sending Error: {e}')
            self._stop("Connection Lost")
            return False
