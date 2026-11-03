# SocketCord Frontend Client

This is the frontend repository of the Network Term Project: SocketCord, a chatting application that utilizes socket programming instead of HTTP requests.

## Dependencies

- `PySide6`
- Source Sans Pro font (You may change the default font family in `styles.py`, the wireframe style should mesh well with vscode/IDE monospace fonts)

## RequestCord Protocol

All requests to the backend follows the **RequestCord** protocol which is loosely based off the famalier HTTP protocol but more focused on the functionality of SocketCord. The famalier HTTP Methods are now replaced with Method Code, providing a possible security via obscurity (since making the backend dynamically assign method codes except for signing in is possible, but is out of scope). And the headers are trimmed down to only the necessary components: **User ID, Session ID, URL Size, Message Size**. The following is a detailed breakdown of the RequestCord packet:


| Size (Bytes) | Field            |
| ------------ | ---------------- |
| 4            | Method Code      |
| 16           | User ID          |
| 16           | Session Token    |
| 2            | URL Size         |
| 2            | Message Size     |
| 4            | URL Checksum     |
| 4            | Message Checksum |
| (vairable)   | URL              |
| (vairable)   | Message          |

For reply packets, this is even simpler. Just Status Code and the Message that the client can use Strategy Pattern on. The following is a detailed breakdown of the RequestCord reply packet:


| Size (Bytes) | Field                  |
| ------------ | ---------------------- |
| 1            | Status Code            |
| 3            | Reply Message Size     |
| 4            | Reply Message Checksum |
| (variable)   | Reply Message          |

## RequestCord Calls

The following is every calls to the backend the client would make. Except for the first 2 calls, every other calls MUST include a `User ID` and `Session Token`, otherwise the backend will **always** return `404 Not Found`.

NOTE: NEVER SEND PLAINTEXT PASSWORD OVER, THIS IS NOT HTTPS PROTOCOL


| Method | URL                       | Description                                                                                           |
| ------ | ------------------------- | ----------------------------------------------------------------------------------------------------- |
| POST   | `users`                   | Registers the new user with a given`username` and `password`                                         |
| POST   | `users/login`             | Logs into the server. The backend will return both`User ID` and newly generated `Session Token`     |
| PATCH  | `users/profile`           | Updates current`user` profile attributes                                                              |
| GET    | `users/info`              | Gets the currnet`user` information                                                                   |
| GET    | `chats`                   | Gets every chat`user` is in                                                                          |
| GET    | `chat/{chat_id}/info`     | Fetch current`chat` information. This includes the user list (with status) and description.           |
| GET    | `chat/{chat_id}/messages` | Fetch recent messages for a specific`chat`. You can use `time`, `content`, and `count` as a filter. |
| POST   | `chat/{chat_id}/message`  | Sends the message                                                                                     |
| POST   | `users/{user_id}/dm`      | Sends a DM request to the specified`user_id` with a `message`.                                       |
| POST   | `chat/{chat_id}/invite`   | Invites the specified`user_id` to a chat.                                                            |
| PATCH  | `users/profile/password`  | Updates current`user` password                                                                        |
|        |                           |                                                                                                       |
|        |                           |                                                                                                       |
|        |                           |                                                                                                       |
|        |                           |                                                                                                       |
|        |                           |                                                                                                       |

Status Codes


| Code | Description                                                                                    |
| ---- | ---------------------------------------------------------------------------------------------- |
| 200  | OK                                                                                             |
| 250  | Bad Request, this happens to requests with malformed payloads (missing fields)                 |
| 251  | Unauthorized, this happens to requests with invalid`User ID` or `Session Token`              |
| 252  | Forbidden                                                                                      |
| 253  | Not Found, this can include requests with invalid`Method Code`, `User ID`, and `Session Token` |
| 254  | Internal Server Error                                                                          |
