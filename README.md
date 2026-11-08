# SocketCord Frontend Client

This is the frontend repository of the Network Term Project: SocketCord, a chatting application that utilizes socket programming instead of HTTP requests.

## Group directory workflow

The left-hand **DIRECTORY** has two tabs:

- **My Group** shows groups you have joined (and your existing direct-message chats / pending invitations).
- **All Group** lists discoverable groups across the server. Select one, then click **Join Group** to become a member. Once joined, you can read and post messages from **My Group**. For groups you already belong to, click **Open Chat**.

New groups appear in **All Group** for everyone. Their creator is automatically a member and can also access them under **My Group**. No manual invitation is required, and the frontend cannot show a non-member the group's messages. The backend already provides `GET chats/groups` and `POST chat/{chat_id}/join`; no server changes are necessary.

## Dependencies

- `PySide6`

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

### Some notes on the calls

- All Requests are handled undetr `RequestCord` class, you only have to supply the corresponding Method Code, URL, and a Dictionary (JSON-like) for the message. `RequestCord` will handle packing them into a bytestream for `.send()`.
- **Every** reply from the backend will contain a `path` field, which the client'll route to the corresponding widgets.
- Every reply that isn't a 200 OK will contain a `error` field, which can be used directly to report errors to the user.
- `password`/`new_password` **must already be hashed!!!**
- Hexcodes must have `#` and uppercase hexadecimal digits (`#ABCDEF` , **not** `#abcdef`)
- Timestamps are in ISO 8601 + UTC like `"2026-11-02T04:24:00+00:00"`


| #  | Method | URL                            | Description                                               | OK reply`path`     | Client function (`chat_page.py` / `login_page.py`) |
| -- | ------ | ------------------------------ | --------------------------------------------------------- | ------------------ | -------------------------------------------------- |
| 1  | POST   | `users`                        | Registers a new user                                      | `login/created`    | `LoginPage.handle_signup_click`                    |
| 2  | POST   | `users/login`                  | Logs in, returns`User ID` and a new `Session Token`       | `login/success`    | `LoginPage.handle_login_click`                     |
| 3  | POST   | `users/logout`                 | Ends the session                                          | `login/logout`     | `ChatPage.logout`                                  |
| 4  | GET    | `users/info`                   | Gets the current user's information                       | `profile/info`     | `MainWindow.show_chat_page`                        |
| 5  | PATCH  | `users/profile`                | Updates username and / or the user's text colours         | `profile/updated`  | `ChatPage.request_edit_profile`                    |
| 6  | PATCH  | `users/password`               | Changes the current user's password                       | `profile/password` | `ChatPage.request_change_password`                 |
| 7  | GET    | `chats`                        | Every chat the user is in or invited to                   | `chats/list`       | `ChatPage.set_chats`                               |
| 8  | POST   | `chats`                        | Creates a new group                                       | `chats/created`    | `ChatPage.request_new_group`                       |
| 9  | GET    | `chat/{chat_id}/info`          | Chat information with its member list (and online status) | `chat/info`        | `ChatPage.request_group_members` / `select_chat`   |
| 10 | GET    | `chat/{chat_id}/messages`      | Recent messages, with filters                             | `chat/messages`    | `ChatPage.select_chat`                             |
| 11 | POST   | `chat/{chat_id}/message`       | Sends a message                                           | `chat/sent`        | `ChatPage.send_message`                            |
| 12 | POST   | `chat/{chat_id}/read`          | Marks the chat's messages as read                         | `chat/read`        | `ChatPage.request_mark_read`                       |
| 13 | POST   | `chat/{chat_id}/summary`       | Generates a summary of the chat                           | `chat/summary`     | `ChatPage.generate_summary`                        |
| 14 | POST   | `chat/{chat_id}/invite`        | Invites a user to a group (membership starts as`pending`) | `chat/invited`     | `ChatPage.request_invite`                          |
| 15 | POST   | `chat/{chat_id}/invite/accept` | Accepts an invitation (`pending` → `accepted`)           | `chat/joined`      | `ChatPage.request_accept_invite`                   |
| 16 | POST   | `chat/{chat_id}/invite/reject` | Rejects an invitation                                     | `chat/declined`    | `ChatPage.request_reject_invite`                   |
| 17 | POST   | `users/{user_id}/dm`           | Starts a DM with a first message (no approval needed)     | `chats/dm`         | `ChatPage.request_message`                         |
| 18 | GET    | `users/online`                 | Every user that is online now                             | `users/online`     | `ChatPage.request_online_users`                    |
| 19 | GET    | `users/{user_id}/groups`       | Every group a user is in                                  | `users/groups`     | `ChatPage.request_user_groups`                     |

## RequestCord Call Reference

The following lists the expected JSON of each RequestCord Call and Reply:

```
{Reqest Object}
{Reply Object}
```

### 1. Register — `POST users`

NOTE : No `User ID` / `Session Token` needed!:

```json
{"username": "Sainen420", "password": "<password hash>"}
{"path": "login/created"}
```

### 2. Login — `POST users/login`

NOTE : No `User ID` / `Session Token` needed!:

```json
{"username": "Sainen420", "password": "<password hash>"}
{"path": "login/success", "user_id": "<uuid>", "session_token": "<uuid>", "username": "Sainen420", "text_color": "#171717", "background": "#F2F2F2"}
```

### 3. Logout — `POST users/logout`

```json
{}
{"path": "login/logout"}
```

### 4. Current user — `GET users/info`

```json
{}
{"path": "profile/info", "user_id": "<uuid>", "username": "Sainen420", "text_color": "#171717", "background": "#F2F2F2"}
```

### 5. Edit profile — `PATCH users/profile`

```json
{"username": "Neo", "text_color": "#FFFFFF", "background": "#AABBCC"}
{"path": "profile/updated", "username": "Neo", "text_color": "#FFFFFF", "background": "#AABBCC"}
```

### 6. Change password — `PATCH users/password`

```json
{"new_password": "<password hash>"}
{"path": "profile/password"}
```

### 7. List chats — `GET chats`

```json
{}
{
  "path": "chats/list",
  "chats": [
    {"chat_id": "<uuid>", "name": "Purgatory", "is_dm": false, "pending": false,
     "unread": 66, "last_activity": "2026-11-02T04:24:00+00:00"},
    {"chat_id": "<uuid>", "name": "lztech", "is_dm": true, "pending": false,
     "unread": 0, "last_activity": "2026-10-15T09:00:00+00:00"},
    ...
  ]
}
```

### 8. Create group — `POST chats`

```json
{"name": "Pals"}
{"path": "chats/created", "chat_id": "<uuid>", "name": "Pals"}
```

### 9. Chat info — `GET chat/{chat_id}/info`

```json
{}
{
  "path": "chat/info",
  "chat_id": "<uuid>",
  "name": "Purgatory",
  "is_dm": false,
  "members": [
    {"user_id": "<uuid>", "username": "Sainen420", "online": true,  "text_color": "#171717", "background": "#F2F2F2"},
    {"user_id": "<uuid>", "username": "moss",      "online": false, "text_color": "#0088FF", "background": "#171717"},
    ...
  ]
}
```

### 10. Messages — `GET chat/{chat_id}/messages`

Every field within the request is optional! However, the proper example of every key will be shown below:

```json
{"time":"<timestamp>", "content":"Hello", "count": 50}
{
  "path": "chat/messages",
  "chat_id": "<uuid>",
  "first_unread_id": "<uuid or null>",
  "messages": [
    {"id": "<uuid>", "sender_id": "<uuid>", "sender": "lztech",
     "text": "**Hello, everyone!!!** Nice to see you!", "time": "2026-11-02T04:24:00+00:00"}
  ]
}
```

Messages are oldest first. `first_unread_id` is the oldest message the user has not read (`null` when everything is read, and always `null` when `time` or `content` is used). The client calls `ChatPage.set_messages(messages, first_unread_id, chat_id)`; the chat opens at the NEW marker above that message.

### 11. Send message — `POST chat/{chat_id}/message`

```json
{"text": "I'm on it. I'll post a draft here before we move anything."}
{"path": "chat/sent", "chat_id": "<uuid>", "message": {"id": "<uuid>", "sender_id": "<uuid>", "sender": "Sainen420", "text": "...", "time": "..."}}
```

### 12. Mark as read — `POST chat/{chat_id}/read`

```json
{}
{"path": "chat/read", "chat_id": "<uuid>"}
```

### 13. Summary — `GET chat/{chat_id}/summary`

```json
{}
{"path": "chat/summary", "chat_id": "<uuid>", "summary": "This conversation seems to be ..."}
```

The generated summary isn't stored on the server.

### 14. Invite to a group — `POST chat/{chat_id}/invite`

```json
{"user_id": "<uuid>"}
{"path": "chat/invited", "chat_id": "<uuid>", "user_id": "<uuid>"}
```

### 15. Accept an invitation — `POST chat/{chat_id}/invite/accept`

```json
{}
{"path": "chat/joined", "chat_id": "<uuid>"}
```

### 16. Accept an invitation — `POST chat/{chat_id}/invite/reject`

```json
{}
{"path": "chat/declined", "chat_id": "<uuid>"}
```

### 17. Direct message — `POST users/{user_id}/dm`

If a DM between `{user_id}` and the header's `user_id` exists, then `message` will be sent into it.

```json
{"message": "Hello!"}
{"path": "chats/dm", "chat_id": "<uuid>", "created": true, "message": {"id": "<uuid>", "sender_id": "<uuid>", "sender": "Sainen420", "text": "Hello!", "time": "..."}}
```

### 18. Online users — `GET users/online`

```json
{}
{
  "path": "users/online",
  "users": [
    {"user_id": "<uuid>", "username": "lztech", "text_color": "#171717", "background": "#0088FF"},
    ...
  ]
}
```

### 19. Groups of a user — `GET users/{user_id}/groups`

```json
{}
{
  "path": "users/groups",
  "user_id": "<uuid>",
  "groups": [
    {"chat_id": "<uuid>", "name": "RECONSTRUCTION 3, 2, 1"},
    {"chat_id": "<uuid>", "name": "Purgatory"},
    ...
  ]
}
```

## Live Updates

To ensure the up-to-date nature of chat application, the server will take the initiative to send updating packets to the client. They have status `200` and a `path` like any reply.


| `path`                 | When                                                                   | Reply message                                                                      | Client action                                                      |
| ---------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `chat/new_message`     | someone else sent a message to a chat the user has joined              | `{"path": "chat/new_message", "chat_id": "<uuid>", "message": {...as in call 11}}` | `append_message(message, chat_id)` if open, else `set_chat_unread` |
| `chats/new`            | the user was invited to a group, or someone started a DM with the user | `{"path": "chats/new", "chat": {...one chat entry as in call 7}}`                  | refresh the directory (`set_chats`)                                |
| `chat/members_changed` | a member accepted an invitation, or changed their name or colours      | `{"path": "chat/members_changed", "chat_id": "<uuid>"}`                            | call 9 again                                                       |
| `users/status`         | a user went online or offline                                          | `{"path": "users/status", "user_id": "<uuid>", "online": true}`                    | update the member rows / ONLINE list                               |

## Status Codes


| Code | Description                                                                                    |
| ---- | ---------------------------------------------------------------------------------------------- |
| 200  | OK                                                                                             |
| 250  | Bad Request, this happens to requests with malformed payloads (missing fields)                 |
| 251  | Unauthorized, this happens to requests with invalid`User ID` or `Session Token`              |
| 252  | Forbidden                                                                                      |
| 253  | Not Found, this can include requests with invalid`Method Code`, `User ID`, and `Session Token` |
| 254  | Internal Server Error                                                                          |
