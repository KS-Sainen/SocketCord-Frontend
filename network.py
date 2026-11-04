import socket, struct, threading, selectors, json, zlib
from PySide6.QtCore import QThread, Signal, Slot
from models import RequestCord

# A Class that manages a SocketCord Socket
class SocketCordNetwork(QThread):
    connection_status = Signal(bool, str)
    reply_message = Signal(int, object)
    # recv_buffer = bytearray()
    error = Signal(str)
    # connected = False
    # running = True

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
    # Configure host and port
    def match_conf(self, host, port):
        return self.host == host and self.port == port
    def conf(self, host, port):
        if self.running or self.connected:
            self.error.emit("Can't reconfigure connection while it's running!")
            return False
        self.host = host
        self.port = port
        return True
    # Active Check
    def _active(self):
        if self.isRunning():
            if self.running:
                return True
            self.wait()
        return False
    # Stops the connection with a given reason
    def _stop(self, reason):
        if self.running:
            self._close_reason = reason
            self.running = False
        if self.client_socket is not None:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    # THE Disconnect
    def disconnect(self):
        self._stop('Disconnected')
    def stop(self):
        self.disconnect()
    def on_closed(self):
        self._stop('Connection Closed')
    # Connects to that socket (THE Connect)
    def connect(self):
        if self._active():
            self.error.emit("Already Connected or Connecting")
            return
        self.recv_buffer = bytearray()
        self._close_reason = "Disconnected"
        self.running = True
        self.start()
    # QThread Running Loop
    def run(self):
        # actually connect here lol
        sel = None
        cur_socket = None
        try:
            try:
                # socket connection
                cur_socket = socket.create_connection((self.host, self.port), timeout=4.0)
                # self.client_socket.setblocking(False)
            except socket.timeout:
                self.connection_status.emit(False, "Connection Timed Out")
                return
            except ConnectionRefusedError:
                self.connection_status.emit(False, "Connection Refused")
                return
            except Exception as e:
                self.connection_status.emit(False, f"Connection Error: {str(e)}")
                return
            # successful connection
            sel = selectors.DefaultSelector()
            sel.register(
                cur_socket, 
                selectors.EVENT_READ, 
                data=self.handle_read
            )
            self.client_socket = cur_socket
            self.connected = True
            self.connection_status.emit(True, "Connected!")
            # event loop
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
    # Handles incoming packets into a receiving buffer
    def handle_read(self, socket: socket.socket, mask=None):
        try:
            data = socket.recv(65536)
        except BlockingIOError:
            pass
        except OSError as e:
            self.error.emit(f"Packet Receiving Error: {str(e)}")
            self._stop('Connection Lost')
        if not data:
            self.on_closed()
            return
        self.recv_buffer.extend(data)
        self.proc_buffer()
    # Process whatever is in the buffer
    def proc_buffer(self):
        HEADER_SZ = 8
        while len(self.recv_buffer) >= HEADER_SZ:
            status_code = self.recv_buffer[0]
            reply_sz = int.from_bytes(self.recv_buffer[1:4],byteorder='big')
            checksum = int.from_bytes(self.recv_buffer[4:8], 'big')
            # complete packet?
            packet_sz = HEADER_SZ + reply_sz
            if len(self.recv_buffer) < packet_sz:
                break
            # complete packet, pack up into json and emit
            raw_msg = bytes(self.recv_buffer[HEADER_SZ:packet_sz])
            del self.recv_buffer[:packet_sz]
            # checksum
            if zlib.crc32(raw_msg) != checksum:
                self.error.emit("Reply Checksum Mismatch")
                continue
            # unpack
            try:
                str_msg = raw_msg.decode('utf-8')
                obj = json.loads(str_msg)
            except Exception as e:
                self.error.emit(f'JSON Parsing Error: {str(e)}')
                continue
            self.reply_message.emit(status_code,obj)

    # Sends a request packet, literally
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
