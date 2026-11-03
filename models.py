import struct
import zlib
import uuid
from dataclasses import dataclass, field

@dataclass
class RequestCord:
    """Class for the request as defined in protocol in README.md"""
    method: int = 0 # 32b
    user_id: uuid.UUID = uuid.UUID(int=0)# UUID, must always be 128 bits -> 16 bytes long
    ses_token: uuid.UUID = uuid.UUID(int=0)# UUID
    url: str = '' # string -> len = url_sz
    msg: str = '' # string -> msg = msg_sz

    # derived header fields (read-only)
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

    # post-init
    def __post_init__(self):
        # set uuid
        if isinstance(self.user_id, str):
            self.user_id = uuid.UUID(self.user_id)
        if isinstance(self.ses_token, str):
            self.ses_token = uuid.UUID(self.ses_token)

        # gen message size + cs
        url_bytes = self.url.encode('utf-8')
        msg_bytes = self.msg.encode('utf-8')
    # UUID
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
    # encoded?
    def _encoded(self):
        if not isinstance(self.url, str) or not isinstance(self.msg, str):
            raise ValueError("url and msg must be str")
        return self.url.encode('utf-8'), self.msg.encode('utf-8')
    # validate and return all fields
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
    # turns into a sendable packet
    def pack(self):
        user_id, ses_token, url_b, msg_b = self.validate()
        header = struct.pack("!I16s16sHHII",self.method,user_id,ses_token,len(url_b), len(msg_b), zlib.crc32(url_b), zlib.crc32(msg_b))
        return header + url_b + msg_b