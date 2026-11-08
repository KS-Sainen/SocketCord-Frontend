# SocketCord Frontend Client

This is the frontend repository of the Network Term Project: SocketCord, a chatting application that utilizes socket programming instead of HTTP requests.

## Dependencies

- `PySide6` (6.12 needs macOS 14.4 or newer; on an older macOS use `pip install "PySide6==6.8.3"`)

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

These are the calls the client really makes. Except for register and login, every call carries the `User ID` and `Session Token` from the login in its header. Without them the backend answers `253 Not Found`; with a session that was logged out, replaced or expired it answers `251` and the client goes back to the login page.

### Some notes on the calls

- Every request goes through `Api.request(method, url, dict, ok, error)` in `api.py`. It builds the `RequestCord`, adds an integer `rid` to the JSON, and calls `ok(reply)` on status 200 or `error(ApiError)` otherwise. The backend echoes `rid` in the reply, which is how a reply finds its callback.
- Every reply carries `path`, `method`, and the `rid` of the request. `path` is **not** the URL any more: it is the semantic name in the table below (`users/login` answers `login/success`). A packet with **no `rid`** is a server push, and `api.py` hands it to the handlers registered with `Api.on(path, callback)` for that exact `path` (see Live Updates). Routes the table does not name keep their URL as `path`.
- An error reply carries `error` (a code such as `USERNAME_TAKEN`) and `detail` (a sentence the client shows as it is), sometimes also `field` (the input that was wrong) and `retry_after`. Its `path` is the request URL, not the semantic name: a wrong password answers `users/login`, so `rid` is what matches an error to its call.
- **The password is sent in the request body, in clear text, over an unencrypted socket.** Register, login and password change are each one request that contains the password itself. The server stores a salted PBKDF2-HMAC-SHA256 hash and compares the hash of what was sent, so it never keeps the password either — but anything on the network path can read it. This is a deliberate simplification taken to meet the project deadline: the earlier SCRAM-SHA-256 challenge-response (which kept the password on this machine) was dropped because it was judged too complicated. A real deployment would put this socket inside TLS.
- Nothing in the client holds the password after the request is sent: `main.py` drops it as soon as the body is handed to `api.py`, and no key material is kept for later. That is also why the change-password pop-up asks for no current password.
- A password change does **not** rotate the session token. The connection, and the summary's second connection, keep working with the token the login handed out.
- The AI summary goes over a second connection (`api.SideChannel`) with the same User ID and Session Token. The server answers one connection's requests one at a time, so a summary on the main connection would hold back every other call until the AI answers. It opens on the first Generate, ignores pushes, never logs in, and closes on logout.
- Colours are `text_color` and `background`. Replies spell them `#RRGGBB` in upper case; requests may use either case.
- Timestamps are ISO 8601 in UTC with a `+00:00` offset, like `"2026-11-02T04:24:00+00:00"`. The client shows local time.
- The backend sends the field names the widgets draw, so there is no translation layer any more. The three row helpers at the top of `chat_page.py` only add what a reply cannot carry: a local `datetime`, `[System]` for a system line (whose `sender` is `null`), and `own` for a message of the logged-in user.
- One exception to that: the body of call 11 spells the message `content`, while every reply spells it `text`. The backend takes `text` there as well; `content` is what is sent because every build of it accepts that.
- **Invitations are off in the client (R10):** people join a group only by themselves, with Browse Groups → JOIN. The Add people icon and "Invite to group" are hidden, and pending invitation rows are not listed. Calls 14–17 below stay in the protocol, but the client does not use them.
- An invitation is a chat row with `pending: true`, and `GET chats` lists it like any other row, so the client keeps no list of its own: every push that can change an invitation (`chats/new`, `chat/members_changed` with `invite_cancelled`, `chats/group_deleted` of the group) just reloads the directory, and the server's rows are the whole truth.

| #  | Method | URL                            | Request (key fields)                                                                                                        | Reply `path` and key fields                                                        | Client function                                     |
| -- | ------ | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | --------------------------------------------------- |
| 1  | POST   | `users`                        | `{username, password}`                                                                                                      | `login/created`                                                                    | `MainWindow._flush_pending` (SIGN UP)               |
| 2  | POST   | `users/login`                  | `{username, password}`                                                                                                      | `login/success` `{user_id, session_token, username, text_color, background}`       | `MainWindow._flush_pending` (LOG IN)                |
| 3  | POST   | `users/logout`                 | `{}`                                                                                                                        | `login/logout`; the client then disconnects                                        | `MainWindow.do_logout` (Log out button)             |
| 4  | GET    | `users/info`                   | `{}`                                                                                                                        | `profile/info` `{user: {user_id, username, text_color, background}}`               | `ChatPage.start_session`                            |
| 5  | PATCH  | `users/profile`                | only what changed: `{username, text_color, background}`                                                                     | `profile/updated` `{user}`                                                         | `ChatPage.request_edit_profile`                     |
| 6  | PATCH  | `users/password`               | `{new_password}`                                                                                                            | `profile/password`; the session token stays as it is                               | `ChatPage.request_change_password`                  |
| 7  | GET    | `chats`                        | `{}`                                                                                                                        | `chats/list` `{chats: [chat row]}`, invitations included with `pending: true`       | `ChatPage.refresh_chats`                            |
| 8  | POST   | `chats`                        | `{name}`                                                                                                                    | `chats/created` `{chat}`; the new group opens                                       | `ChatPage.request_new_group`                        |
| 9  | GET    | `chat/{chat_id}/info`          | `{}`                                                                                                                        | `chat/info` `{chat: {name, is_dm, members: [member]}}`                              | `ChatPage.request_group_members` (`select_chat`, MEMBERS arrow) |
| 10 | GET    | `chat/{chat_id}/messages`      | `{count: 100}`; then `{count: 200, before_id}` while the first unread message is older than what is loaded (at most 5 times) | `chat/messages` `{chat_id, first_unread_id, messages, has_more}` (oldest first)     | `ChatPage.select_chat`                              |
| 11 | POST   | `chat/{chat_id}/message`       | `{content}` — the one asymmetric name: the request says `content`, the message that comes back says `text`                    | `chat/sent` `{message}`                                                             | `ChatPage.send_message`                             |
| 12 | POST   | `chat/{chat_id}/read`          | `{message_id}` = the newest message shown, once per message                                                                 | `chat/read`                                                                         | `ChatPage.request_mark_read` (scrolled to the bottom) |
| 13 | GET    | `chat/{chat_id}/summary`       | `{mode: "recent", count: 50}`                                                                                               | `chat/summary` `{summary}`; `null` when there is nothing to summarize (`POST` works too) | `ChatPage.generate_summary` (second connection) |
| 14 | POST   | `chat/{chat_id}/invite`        | `{user_id}`                                                                                                                 | `chat/invited`                                                                      | `ChatPage.request_invite`                           |
| 15 | GET    | `chat/{chat_id}/invitees`      | `{query}` (at most 32 characters)                                                                                           | `chat/{chat_id}/invitees` `{users: [{user_id, username}]}`: who may still be invited | `ChatPage.request_invitees`                        |
| 16 | POST   | `chat/{chat_id}/invite/accept` | `{}`                                                                                                                        | `chat/joined`; the `[Pending]` chat becomes a normal one                             | `ChatPage.request_accept_invite`                    |
| 17 | POST   | `chat/{chat_id}/invite/reject` | `{}`                                                                                                                        | `chat/declined`; the chat leaves the directory                                       | `ChatPage.request_reject_invite`                    |
| 18 | POST   | `users/{user_id}/dm`           | `{message}`                                                                                                                 | `chats/dm` `{chat_id}`; the DM opens at once                                         | `ChatPage.request_message`                          |
| 19 | GET    | `users/online`                 | `{}`                                                                                                                        | `users/online` `{users: [member]}`                                                   | `ChatPage.request_online_users`                     |
| 20 | GET    | `users/{user_id}/groups`       | `{}`                                                                                                                        | `users/groups` `{groups: [{chat_id, name}]}`                                          | `ChatPage.request_user_groups` (See Groups)         |
| 21 | GET    | `users/search`                 | `{query, count}`                                                                                                            | `users/search` `{users}`; only used when a name is not in the member / online list    | `ChatPage._with_user_id`                            |
| 22 | GET    | `chats/groups`                 | `{count: 200}`; then `{count: 200, offset}` while `has_more`                                                                | `chats/groups` `{groups: [{chat_id, name, member_count, members: [member], joined}], offset, has_more}`: every group on the server, oldest first | `ChatPage.request_all_groups` (Browse Groups) |
| 23 | POST   | `chat/{chat_id}/join`          | `{}`                                                                                                                        | `chat/{chat_id}/join` `{chat, info}`; a pending invitation to the group counts as accepted | `ChatPage.request_join_group` (JOIN in Browse Groups) |

### Reply examples

A login (call 2). The username and the colours come back at the top level, not inside a `user` object:

```json
{"path": "login/success", "method": "POST", "rid": 1,
 "user_id": "0193f0c1-5a7e-7c31-9f2d-1b6a4c8e7d55",
 "session_token": "0193f0c1-5a7f-7a10-8c44-9e2f7b3d1c08",
 "username": "lztech", "text_color": "#171717", "background": "#F2F2F2"}
```

A page of messages (call 10). `first_unread_id` is `null` once everything is read; a system line has `sender_id` and `sender` set to `null` and is drawn as `[System]`:

```json
{"path": "chat/messages", "method": "GET", "rid": 7,
 "chat_id": "0193f0c2-1111-7000-8000-000000000001",
 "first_unread_id": "0193f0c3-2222-7000-8000-00000000000b",
 "messages": [
   {"id": "0193f0c3-2222-7000-8000-00000000000a", "sender_id": "0193f0c1-5a7e-7c31-9f2d-1b6a4c8e7d55",
    "sender": "lztech", "text": "Starting fresh in here.", "time": "2026-11-02T04:24:00+00:00"},
   {"id": "0193f0c3-2222-7000-8000-00000000000b", "sender_id": null, "sender": null,
    "text": "moss joined the group", "time": "2026-11-02T04:25:10+00:00"}
 ]}
```

The chat directory (call 7). A DM's `name` is the other person's username; `pending` is true for an invitation that has not been answered yet:

```json
{"path": "chats/list", "method": "GET", "rid": 3,
 "chats": [
   {"chat_id": "0193f0c2-1111-7000-8000-000000000001", "name": "RECONSTRUCTION 3, 2, 1",
    "is_dm": false, "pending": false, "unread": 2, "last_activity": "2026-11-02T04:29:00+00:00"},
   {"chat_id": "0193f0c2-1111-7000-8000-000000000002", "name": "Study Circle",
    "is_dm": false, "pending": true, "unread": 0, "last_activity": "2026-11-01T10:00:00+00:00"}
 ]}
```

The members of a chat (call 9). The same member shape is what `users/online` lists:

```json
{"path": "chat/info", "method": "GET", "rid": 6,
 "chat": {"name": "RECONSTRUCTION 3, 2, 1", "is_dm": false,
          "members": [{"user_id": "0193f0c1-5a7e-7c31-9f2d-1b6a4c8e7d55", "username": "lztech",
                       "online": true, "text_color": "#F2F2F2", "background": "#0088FF"}]}}
```

A failed call: the status is not 200 and the reply says why. `detail` is shown to the user as it is, and `field` marks the input to put it next to:

```json
{"path": "users/login", "method": "POST", "rid": 2,
 "error": "INVALID_CREDENTIALS", "detail": "wrong username or password"}
```

The full request and reply JSON of every call is in the backend's `docs/API.md` (SocketCord-Server).

## Live Updates

The server pushes updates by itself. A push has status `200`, **no `rid`**, and a `path` naming what happened; `api.py` hands it to the handlers registered with `Api.on(path, callback)`.

| `path`                 | When                                                                  | Payload                        | Client action                                                                                              |
| ---------------------- | --------------------------------------------------------------------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `chat/new_message`     | someone else posted in a chat the user is in (also the system lines)  | `{chat_id, message}`           | `append_message` if that chat is open (marked read when at the bottom), otherwise its unread count goes up |
| `chats/new`            | the user was invited to a group, or a DM was opened with them         | `{chat}` (one chat row)        | reload the directory, which lists the `[Pending]` invitation itself; then Browse Groups*                   |
| `chat/members_changed` | a member joined, left, renamed or changed colours, or an invitation was cancelled; a join or a leave reaches everyone, members or not | `{chat_id, change}` | read the member list of that chat again, and the directory (a DM is named after the other person; a cancelled invitation leaves it); then Browse Groups* |
| `chats/group_created`  | somebody else created a group                                         | `{group}` (a `chats/groups` row) | Browse Groups*                                                                                           |
| `chats/group_deleted`  | a group's last member left                                            | `{chat_id}`                    | an invitation to it leaves the directory; Browse Groups*                                                   |
| `users/profile_changed`| somebody changed their username or colours                            | `{user}`                       | the new name and colours in the member and ONLINE rows, the badges and the messages; Browse Groups*        |
| `users/status`         | somebody went online or offline                                       | `{user_id, online}`            | the dots in the member list; the ONLINE list is fetched again when somebody new appears                     |
| `login/revoked`        | logged in somewhere else, logged out, the session expired             | `{reason}`                     | back to the login page with the reason                                                                      |

\* Browse Groups: if that pop-up is open, it reads every group again with `GET chats/groups` (after the directory, when the push reloads that too, so its "you're invited" mark agrees with the `[Pending]` rows). It keeps no list of its own.

`chat/members_changed` carries the chat id and what happened (`joined`, `left`, `profile` or `invite_cancelled`), so a rename or a new colour is noticed by reading that chat's member list again: that reply is where the client learns the names and colours it draws messages and badges with. `users/profile_changed` carries the user itself and reaches everyone, which is how the ONLINE list follows a rename by somebody the user shares no chat with.

`login/revoked` is the one push the wire contract does not name in its own table: it only requires that this push survive, because the client depends on it to leave the chat page when the session ends. Its `reason` is one of `logged_in_elsewhere`, `password_changed`, `logged_out`, `expired` or `too_many_connections`, and `main.REVOKED_TEXT` turns it into the sentence on the login page.

## Status Codes

| Code | Description                                                                                    |
| ---- | ---------------------------------------------------------------------------------------------- |
| 200  | OK                                                                                             |
| 250  | Bad Request: a missing or malformed field (`MISSING_FIELD`, `INVALID_FIELD`, `INVALID_USERNAME`) |
| 251  | Unauthorized: the session is invalid, logged out or expired, or the username and password do not match (`INVALID_CREDENTIALS`, the same code for a wrong name and a wrong password, so the reply does not say which accounts exist) |
| 252  | Forbidden: not allowed here, the name is taken, or too many tries (`USERNAME_TAKEN`, `RATE_LIMITED`) |
| 253  | Not Found: unknown method code or URL, unknown chat / user, or no `User ID` / `Session Token`   |
| 254  | Internal Server Error                                                                          |
