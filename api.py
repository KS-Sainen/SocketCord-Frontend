"""Matches backend replies to the requests that asked for them. Lives in the GUI thread.

Every request carries an integer "rid" in its JSON and the backend echoes it in the reply,
so each call gets its own ok / error callback. A packet that carries no "rid" is a server
push ("chat/new_message", "users/status", ...) and goes to the handlers registered with on(),
keyed by the push's "path".
network.py emits reply_message from its QThread; Qt queues it to the GUI thread, so every
callback here runs in the GUI thread and may touch widgets.
"""
import itertools
import traceback

from PySide6.QtCore import QObject, Signal, Slot

from models import NIL_UUID, RequestCord
from network import SocketCordNetwork

POST = 112233445
GET = 354984100
PATCH = 943742156

STATUS_NAMES = {250: "Bad request", 251: "Unauthorized", 252: "Forbidden", 253: "Not found",
                254: "Server error"}


class ApiError(Exception):
    """A failed call. status 0 = the client side failed (no connection, user not found, ...)."""

    def __init__(self, status, code, detail="", data=None):
        self.status = int(status)
        self.code = str(code or "")
        self.detail = str(detail or "")
        self.data = dict(data or {})
        self.field = self.data.get("field")
        super().__init__(self.message)

    @property
    def message(self):
        text = self.detail or self.code or STATUS_NAMES.get(self.status, "request failed")
        return text[:1].upper() + text[1:]


def _safe_call(callback, arg):
    if callback is None:
        return
    try:
        callback(arg)
    except Exception:                       # one broken callback must not stop the dispatcher
        traceback.print_exc()


class Api(QObject):
    session_invalid = Signal(str)           # an authenticated call answered 251: log in again

    def __init__(self, network):
        super().__init__()
        self.network = network
        self._rids = itertools.count(1)
        self._pending = {}                  # rid -> (ok, error, auth)
        self._handlers = {}                 # push path -> [callback(data)]

    def request(self, method, url, data=None, ok=None, error=None, auth=True):
        """Sends one RequestCord. ok(reply dict) on status 200, otherwise error(ApiError)."""
        rid = next(self._rids)
        msg = dict(data or {})
        msg["rid"] = rid
        if auth:
            req = RequestCord.from_dict(method, url, msg)
        else:
            req = RequestCord.from_dict(method, url, msg, user_id=NIL_UUID, ses_token=NIL_UUID)
        self._pending[rid] = (ok, error, auth)
        if not self.network.send(req):
            self._pending.pop(rid, None)
            _safe_call(error, ApiError(0, "NOT_CONNECTED", "not connected to the server"))
        return rid

    def fail_all(self, reason):
        """The connection is gone: every call still waiting fails."""
        pending, self._pending = self._pending, {}
        for ok, error, auth in pending.values():
            _safe_call(error, ApiError(0, "CONNECTION_LOST", reason))

    def on(self, path, callback):
        """callback(data) for every push whose "path" is `path`."""
        self._handlers.setdefault(path, []).append(callback)

    @Slot(int, object)
    def handle_reply(self, status, data):
        if not isinstance(data, dict):
            return
        path = str(data.get("path", ""))
        rid = data.get("rid")
        # No rid: a push. An error without one means the backend could not read the rid out of the
        # request at all, so no callback is waiting for it and it would otherwise vanish.
        if rid is None:
            handlers = self._handlers.get(path)
            if handlers:
                for callback in list(handlers):
                    _safe_call(callback, data)
            elif status != 200:
                print(f"[api] error reply without a rid {status}: {data.get('error')} {data.get('detail')}")
            return
        entry = self._pending.pop(rid, None)
        if entry is None:
            if status != 200:
                print(f"[api] unmatched error reply {status}: {data.get('error')} {data.get('detail')}")
            return
        ok, error, auth = entry
        if status == 200:
            _safe_call(ok, data)
            return
        err = ApiError(status, data.get("error"), data.get("detail"), data)
        _safe_call(error, err)
        if status == 251 and auth:
            self.session_invalid.emit(err.message)


class SideChannel(QObject):
    """A second connection for slow calls (the AI summary). The server answers the requests of
    one connection one at a time, in order, so a summary on the main connection would hold back
    every other call until the AI answers (backend docs/API.md 5.2, client duty 6).

    It opens on first use, to the server the main connection talks to, and sends the same User ID
    and Session Token (RequestCord's). It never logs in, which would end the main session. Pushes
    reach it too and are ignored; the main connection handles them. main.py closes it whenever the
    session ends."""

    def __init__(self, main_network):
        super().__init__()
        self.main = main_network
        self.network = SocketCordNetwork(main_network.host, main_network.port)
        self.api = Api(self.network)            # no push handlers: pushes are dropped here
        self._queue = []                        # calls waiting for the connection to open
        self.network.reply_message.connect(self._on_reply)
        self.network.connection_status.connect(self._on_status)

    def request(self, method, url, data=None, ok=None, error=None):
        net, host, port = self.network, self.main.host, self.main.port
        if net.connected and net.running and net.match_conf(host, port):
            return self.api.request(method, url, data, ok, error)
        self._queue.append((method, url, data, ok, error))
        if net._active():
            if net.match_conf(host, port):
                return None                     # still connecting: sent once it is open
            net.disconnect()
            net.wait()
        if net.conf(host, port):
            net.open_connection()
        return None

    def close(self):
        """The session ended: drop the connection; every call still waiting fails."""
        queue, self._queue = self._queue, []
        self.network.disconnect()
        self.network.wait()
        self.api.fail_all("Logged out")
        for _method, _url, _data, _ok, error in queue:
            _safe_call(error, ApiError(0, "CONNECTION_LOST", "Logged out"))

    @Slot(int, object)
    def _on_reply(self, status, data):
        self.api.handle_reply(status, data)

    @Slot(bool, str)
    def _on_status(self, success, message):
        net = self.network
        if success:
            if net.connected:                   # (not a late signal of a connection closed since)
                queue, self._queue = self._queue, []
                for args in queue:
                    self.api.request(*args)
            return
        if net.running:
            return                              # a late signal of an older connection; a new one is on its way
        self.api.fail_all(message)
        queue, self._queue = self._queue, []
        for _method, _url, _data, _ok, error in queue:
            _safe_call(error, ApiError(0, "NOT_CONNECTED", f"no second connection to the server ({message})"))
