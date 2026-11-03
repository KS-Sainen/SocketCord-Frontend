import struct
import zlib
import uuid
from dataclasses import dataclass, field

@dataclass
class RequestCord:
    """Class for the request as defined in protocol in README.md"""
    method: int = 0 # 32b
    user_id: uuid.UUID # UUID, must always be 128 bits -> 16 bytes long
    ses_token: uuid.UUID # UUID
    url_sz: int = field(init=False, default=0) # 16b
    msg_sz: int = field(init=False, default=0) # 16b
    url_cs: int = field(init=False, default=0) # 32b
    msg_cs: int = field(init=False, default=0) # 32b
    url: str = '' # string -> len = url_sz
    msg: str = '' # string -> msg = msg_sz

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

        self.url_sz = len(url_bytes)
        self.msg_sz = len(msg_bytes)

        self.url_cs = zlib.crc32(url_bytes) & 0xFFFF
        self.msg_cs = zlib.crc32(msg_bytes) & 0xFFFF
    # validate and correct integer
    def vac_int(self, val, mi, mx, signed=False):
        if not signed:
            v2 = struct.unpack("I",val)
            return max(mi, min(v2, mx))
        else:
            return max(mi, min(val, mx))
    # validate and correct all fields
    def vac(self):
        # max value const
        UINT32_MAX = (1 << 32) - 1
        UUID_LEN = 16  # in bytes
        self.method = self.vac_int(self.method, 0, UINT32_MAX)
        self.user_id = self.user_id[:UUID_LEN]
        self.ses_token = self.ses_token[:UUID_LEN]
    # turns into a sendable packet
    # also comes with a pre-packaged header + dynamic size
    def pack(self):
        url_bytes = self.url.encode('utf-8')
        msg_bytes = self.msg.encode('utf-8')
        header = struct.pack("!I16s16sHHII",self.method,self.user_id.bytes,self.ses_token.bytes,self.url_sz,self.msg_sz,self.url_cs,self.msg_cs)
        return header + url_bytes + msg_bytes, len(header), len(url_bytes) + len(msg_bytes)