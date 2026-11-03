import socket, struct, asyncio, selectors
from dataclasses import dataclass

@dataclass
class RequestCord:
    """Class for the request as defined in protocol in README.md"""
    method: int
    user_id: str
    ses_token: str
    url_sz: int
    msg_sz: int
    url_cs: int
    msg_cs: int
    url: str
    msg: str
