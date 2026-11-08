# SocketCord frontend / backend integration fixes

This package patches frontend only. The original SocketCord-Server works without changes.

## Changes
- `main.py`: route full server paths; handle login and registration errors, show chat UI after login.
- `chat_page.py`: correlate semantic backend reply paths using `rid` to original request URLs.
- Map the nine server push paths to UI handlers for online presence, messages, requests, group updates and logout.
- Use backend v2 response fields for message sender / message ID / timestamp / unread markers / user colours.
- Preserve the `pending` state of group invitation rows.
- `GET chat/{id}/invitees` searches eligible invitees; `GET users/{id}/groups` shows groups.
- Left-click or right-click on a member shows actions; Message is available in both MEMBERS and ONLINE.
- `login_page.py`: show auth errors and fix sign-in and sign-up status text.

## Run
1. Start SocketCord-Server using `python3 -m socketcord --db memory --no-reg-limit` from the server folder, or Docker.
2. `python3 -m pip install PySide6`
3. `python3 main.py` from this folder.
4. Log in with two DIFFERENT accounts in two desktop application processes.
5. Click the arrow next to MEMBERS to view all logged-in users (ONLINE).
6. Left-click a username, choose Message to start a DM.
7. Select **All Group** to browse groups; click **Join Group** to enter one.
8. Joined groups appear in **My Group**, including groups created by you. Direct messages remain under **My Group**.

The socket uses plaintext TCP including login passwords. Use only on trusted networks or add TLS before deployment.

## Group directory update (November 2026)
- Removed the **Edit profile** button and the **Add people to group** header icon.
- Removed **Invite to group** from member context menus; users can join public groups themselves.
- Added **My Group** and **All Group** directory tabs.
- **All Group** is backed by `GET chats/groups` with paginated fetching and live group-created / membership / group-deleted refreshes.
- **Join Group** sends `POST chat/{chat_id}/join`; chatting is not enabled in the public preview, and the user switches to **My Group** only after the server confirms success.
- The creator is automatically a member according to the existing server contract; newly created groups appear in **All Group** for everyone, and in the creator's **My Group** as well.
- Clicking **Open Chat** for an already-joined public group switches to the joined chat.
- The original server is unchanged. Membership and message-access enforcement remain on the server.

Validation: frontend Python compilation, isolated checks of pagination/join/creation logic, and 41 backend API/contract tests passed. Full PySide6 GUI integration was not runnable in the validation environment.
