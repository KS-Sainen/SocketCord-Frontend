import struct
import zlib
import uuid
import json
from typing import ClassVar
from dataclasses import dataclass, field

NIL_UUID = uuid.UUID(int=0)
 
def _json_default(obj):
    # Lets a UUID sit in the dict (e.g. a chat_id / user_id) without the caller str()-ing it.
    if isinstance(obj, uuid.UUID):
        return str(obj)
    raise TypeError(f"{type(obj).__name__} is not JSON serializable!")

@dataclass
class RequestCord:
    """Class for the request as defined in protocol in README.md"""
    method: int = 0 # 32b
    user_id: uuid.UUID = field(default_factory=lambda: RequestCord._auth[0])   # 128b
    ses_token: uuid.UUID = field(default_factory=lambda: RequestCord._auth[1]) # 128b
    url: str = ''
    msg: str = ''
    _auth: ClassVar[tuple] = (NIL_UUID, NIL_UUID)
    @property
    def url_sz(self):   # 16b
        return len(self._encoded()[0])
 
    @property
    def msg_sz(self):   # 16b
        return len(self._encoded()[1])
 
    @property
    def url_cs(self):   # 32b
        return zlib.crc32(self._encoded()[0])
 
    @property
    def msg_cs(self):   # 32b
        return zlib.crc32(self._encoded()[1])

    @classmethod
    def from_dict(cls, method, url, data=None, user_id=None, ses_token=None):
        if (user_id is None) != (ses_token is None):
            raise ValueError("pass both user_id and ses_token, or neither")
        if user_id is None:
            req = cls(method=method, url=url)
        else:
            req = cls(method=method, user_id=user_id, ses_token=ses_token, url=url)
        req.set_dict(data)
        return req

    def __post_init__(self):
        if isinstance(self.user_id, str):
            self.user_id = uuid.UUID(self.user_id)
        if isinstance(self.ses_token, str):
            self.ses_token = uuid.UUID(self.ses_token)
    def set_dict(self, data):
        if data is None:
            self.msg = ''
            return
        if not isinstance(data, dict):
            raise ValueError(f'Trying to convert non-dict {type(data).__name__} into request!')
        try:
            self.msg = json.dumps(data, ensure_ascii=False, separators=(',', ':'),default=_json_default)
        except (TypeError, ValueError) as e:
            raise ValueError(f"message data is not JSON serializable: {e}") from None
    @classmethod
    def set_auth(cls, user_id, ses_token):
        uid = cls._as_uuid(user_id, "user_id")
        tok = cls._as_uuid(ses_token, "ses_token")
        cls._auth = (uid, tok)
    @classmethod
    def clear_auth(cls):
        cls._auth = (NIL_UUID, NIL_UUID)
    @staticmethod
    def _as_uuid(value, name):
        if isinstance(value, uuid.UUID):
            return value
        if isinstance(value, str):
            try:
                return uuid.UUID(value)
            except ValueError:
                raise ValueError(f"{name} is not a valid UUID string: {value!r}") from None
        raise ValueError(f"{name} must be a UUID or UUID string, got {type(value).__name__}")
    def _encoded(self):
        if not isinstance(self.url, str) or not isinstance(self.msg, str):
            raise ValueError("url and msg must be str")
        return self.url.encode('utf-8'), self.msg.encode('utf-8')
    def validate(self):
        UINT32_MAX = (1 << 32) - 1
        UINT16_MAX = (1 << 16) - 1
        if isinstance(self.method, bool) or not isinstance(self.method, int) \
                or not 0 <= self.method <= UINT32_MAX:
            raise ValueError(f"method must be an int in 0..{UINT32_MAX}, got {self.method!r}")
        user_id = self._as_uuid(self.user_id, "user_id")
        ses_token = self._as_uuid(self.ses_token, "ses_token")
        url_b, msg_b = self._encoded()
        if len(url_b) > UINT16_MAX:
            raise ValueError(f"url is {len(url_b)} bytes, the 16-bit size field allows {UINT16_MAX}")
        if len(msg_b) > UINT16_MAX:
            raise ValueError(f"msg is {len(msg_b)} bytes, the 16-bit size field allows {UINT16_MAX}")
        return user_id, ses_token, url_b, msg_b
    def pack(self):
        user_id, ses_token, url_b, msg_b = self.validate()
        header = struct.pack("!I16s16sHHII",self.method,user_id.bytes,ses_token.bytes,len(url_b), len(msg_b), zlib.crc32(url_b), zlib.crc32(msg_b))
        return header + url_b + msg_b