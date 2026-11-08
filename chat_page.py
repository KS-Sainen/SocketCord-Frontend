import html
import re
import uuid
import zlib
from datetime import datetime, timedelta
from string import Template

from PySide6.QtCore import Qt, Signal, QSize, QRect, QPointF, QTimer, QEvent
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QToolButton, QFrame, QScrollArea, QTextEdit, QTextBrowser, QStyledItemDelegate, QStyle,
    QSizePolicy, QAbstractItemView, QMenu, QApplication, QStackedWidget
)

# Palette tokens come from styles.py. Never write a hex colour in this file.
from styles import BLACK, WHITE, RED, BLUE, PALETTE
from dialogs import (
    EditProfileDialog, ChangePasswordDialog, NewGroupDialog, InviteDialog, MessageDialog, GroupsDialog,
    AddPeopleDialog, BrowseGroupsDialog
)
from api import GET, POST, PATCH, ApiError

# ---------------------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------------------
TAB_WIDTH = 165                 # the black "DIRECTORY / CHAT / ..." tabs
TAB_HEIGHT = 36
INPUT_PLACEHOLDER = "Anything else for the welcome note?"
INPUT_MAX_LINES = 5             # the chat box grows to this many lines, then scrolls
INPUT_BORDER = 3                # px, must match the QSS below
INPUT_PAD_Y = 4                 # px, must match the QSS below
BADGE_PAD_X = 6                 # margin/padding around a user name, left and right (px)
BADGE_PAD_Y = 2                 # ... top and bottom (px)
ENTRY_MARGIN_BOTTOM = 6         # px under the hint line; the blank strip above the input copies the
                                # whole distance from the input's bottom edge to the frame
PENDING_TEXT = "[Pending]"        # shown in the directory instead of the unread count
MEMBERS, ONLINE = "members", "online"   # what the right-hand list shows
MESSAGE_PAGE = 100              # messages loaded when a chat opens (the backend allows up to 200)
OLDER_PAGE = 200                # ... plus older pages of this size while the first unread one is not in
OLDER_PAGES_MAX = 5             # (at most 1100 messages; beyond that NEW goes above the oldest one shown)
MESSAGE_MAX_LEN = 4000          # the backend refuses longer messages
NOTICE_MS = 6000                # how long an error replaces the hint under the chat box
SUMMARY_COUNT = 50              # messages the summary covers
GROUP_PAGE = 200                # groups per GET chats/groups page (the backend's maximum)
SYSTEM_SENDER = "[System]"      # '[' can't appear in a username, so no user can look like this

# (text colour, background)
# default color style
DF_USER_STYLE = (BLACK, WHITE)

def activity_color(selected, unread):
    """Colour of the '(n) - time' line under a chat's name.
    Blue when the chat is NOT selected and has activity; white on the black selected row."""
    if selected:
        return WHITE
    return BLUE if unread else BLACK


# ---------------------------------------------------------------------------------------
# message text: **bold**  *italic* / _italic_  __underline__   (can be nested)
# ---------------------------------------------------------------------------------------
_RX_BOLD_ITALIC = re.compile(r'\*\*\*(?=\S)(.+?)(?<=\S)\*\*\*', re.S)
_RX_BOLD = re.compile(r'\*\*(?=\S)(.+?)(?<=\S)\*\*', re.S)
_RX_UNDERLINE = re.compile(r'__(?=\S)(.+?)(?<=\S)__', re.S)
_RX_ITALIC_STAR = re.compile(r'(?<![\*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\*\w])', re.S)
_RX_ITALIC_UNDER = re.compile(r'(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])', re.S)
_RX_LONG_WORD = re.compile(r'(\S{28})(?=\S)')


def markdown_to_html(text):
    """Turns a chat message into safe rich text. Everything is HTML-escaped first, so a
    message can never inject markup; only the three markers below become tags."""
    s = html.escape(str(text), quote=False)
    s = _RX_LONG_WORD.sub('\\1\u200b', s)               # let very long words wrap instead of widening the page
    s = _RX_BOLD_ITALIC.sub(r'<b><i>\1</i></b>', s)
    s = _RX_UNDERLINE.sub(r'<u>\1</u>', s)
    s = _RX_BOLD.sub(r'<b>\1</b>', s)
    s = _RX_ITALIC_STAR.sub(r'<i>\1</i>', s)
    s = _RX_ITALIC_UNDER.sub(r'<i>\1</i>', s)
    s = s.replace('\n', '<br>')
    return f"<span style='white-space: pre-wrap;'>{s}</span>"


# ---------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------
def _as_datetime(value):
    """A backend timestamp ("2026-11-02T04:24:00+00:00") as a naive local datetime, which is what
    the clock, the day dividers and the directory's sort order work with."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    if not isinstance(value, datetime):
        return None
    return value.astimezone().replace(tzinfo=None) if value.tzinfo is not None else value


# The backend sends the field names the widgets draw, so these only add what a reply cannot
# carry: a local datetime, the label for a system line (its sender is null) and "own".
def _message_row(m, my_id=None):
    m = m or {}
    sender_id = m.get("sender_id")
    return dict(m, sender=str(m.get("sender") or "") or SYSTEM_SENDER,
                time=_as_datetime(m.get("time")),
                own=bool(sender_id) and sender_id == my_id)


def _chat_row(c):
    c = c or {}
    return dict(c, last_activity=_as_datetime(c.get("last_activity")))


def _member_row(m, my_id=None):
    m = m or {}
    return dict(m, is_me=bool(my_id) and m.get("user_id") == my_id)


def _id_before(a, b):
    """Message ids are UUIDv7: a smaller id is an older message (the backend pages by this order)."""
    try:
        return uuid.UUID(str(a)) < uuid.UUID(str(b))
    except ValueError:
        return False


def format_clock(dt):
    return dt.strftime("%I:%M %p").lstrip("0")                      # 11:24 AM


def format_activity_time(dt, now=None):
    """'3:33 AM' for today, '25/10/2026' for any other day (as in the mockup)."""
    now = now or datetime.now()
    if dt.date() == now.date():
        return format_clock(dt)
    return f"{dt.day}/{dt.month}/{dt.year}"


def format_day(dt):
    return f"{dt.day} {dt.strftime('%b')} {dt.year}".upper()       # 2 NOV 2026


def make_icon(kind, color):
    """Draws a small icon in one palette colour (no font or image file needed)."""
    px = QPixmap(96, 96)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    pen = QPen(c, 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    def poly(*pts):
        return QPolygonF([QPointF(x, y) for x, y in pts])

    if kind == "caret":
        p.setBrush(c)
        p.drawPolygon(poly((18, 30), (78, 30), (48, 68)))
    elif kind == "caret_up":
        p.setBrush(c)
        p.drawPolygon(poly((18, 68), (78, 68), (48, 30)))
    elif kind == "pencil":
        p.drawPolygon(poly((62, 14), (82, 34), (36, 80), (12, 84), (16, 60)))
        p.drawLine(48, 28, 70, 50)
    elif kind == "logout":
        p.drawPolyline(poly((44, 16), (16, 16), (16, 80), (44, 80)))
        p.drawLine(34, 48, 84, 48)
        p.drawPolyline(poly((66, 30), (84, 48), (66, 66)))
    elif kind == "send":
        p.drawPolygon(poly((10, 46), (88, 10), (62, 86), (46, 56)))
        p.drawLine(46, 56, 88, 10)
    elif kind == "people_plus":
        p.drawEllipse(QPointF(30, 30), 13, 13)
        p.drawArc(QRect(8, 52, 44, 44), 0, 180 * 16)
        p.drawEllipse(QPointF(58, 36), 10, 10)
        p.drawArc(QRect(44, 56, 34, 36), 20 * 16, 140 * 16)
        p.drawLine(80, 56, 80, 84)
        p.drawLine(66, 70, 94, 70)
    p.end()
    return QIcon(px)


def _repolish(widget, name, value):
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


# ---------------------------------------------------------------------------------------
# widgets
# ---------------------------------------------------------------------------------------
class ElidedLabel(QLabel):
    """A one-line label that shows '...' instead of forcing its parent wider. Plain text only:
    it shows names other users chose (a group called '<b>x</b>' must not turn bold)."""
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = text
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self._apply()

    def setText(self, text):
        self._full = text
        self._apply()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply()

    def _apply(self):
        elided = self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(0, self.width()))
        QLabel.setText(self, elided)
        # a tooltip is rich text whenever it looks like markup: escape it inside a real tag
        self.setToolTip(f"<p>{html.escape(self._full)}</p>" if elided != self._full else "")


class UserBadge(QLabel):
    """A user name drawn in the user's own text colour on the user's own background,
    with padding around the text."""
    def __init__(self, text, fg, bg, parent=None):
        super().__init__(text, parent)
        self.setObjectName("UserBadge")
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setStyleSheet(
            f"background-color: {bg}; color: {fg}; font-size: 11pt; "
            f"padding: {BADGE_PAD_Y}px {BADGE_PAD_X}px;"
        )


class DividerRow(QWidget):
    """──── 2 NOV 2026 ────   /   ──── NEW ────"""
    def __init__(self, text, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(10)
        for part in ("left", "text", "right"):
            if part == "text":
                label = QLabel(text)
                label.setObjectName("DividerText")
                row.addWidget(label)
            else:
                line = QFrame()
                line.setObjectName("DividerLine")
                line.setFixedHeight(1)
                line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                row.addWidget(line, 1, Qt.AlignVCenter)


class MessageContainer(QWidget):
    """Holds the message rows inside the scroll area. Word-wrapped labels report a minimum
    height computed for a very narrow width, which would add empty scroll range below the
    last message. Reporting no minimum lets the scroll area use the height for the real width."""
    def minimumSizeHint(self):
        return QSize(0, 0)


class MessageWidget(QFrame):
    def __init__(self, msg, own, fg, bg, parent=None):
        super().__init__(parent)
        self.setObjectName("OwnMessage" if own else "Message")
        col = QVBoxLayout(self)
        col.setContentsMargins(8, 5, 8, 6)
        col.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(8)
        name = UserBadge("You" if own else str(msg.get("sender", "?")), fg, bg)
        head.addWidget(name, 0, Qt.AlignLeft)
        head.addStretch(1)
        dt = _as_datetime(msg.get("time"))
        stamp = format_clock(dt) if dt else str(msg.get("time", ""))
        if own and msg.get("status"):
            stamp += f" · ✓ {msg['status']}"
        clock = QLabel(stamp)
        clock.setObjectName("MessageTime")
        head.addWidget(clock, 0, Qt.AlignRight)
        col.addLayout(head)

        body = QLabel(markdown_to_html(msg.get("text", "")))
        body.setObjectName("MessageBody")
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        col.addWidget(body)


class AutoGrowTextEdit(QTextEdit):
    """Chat box: one line high, grows with its text up to `max_lines`, then scrolls.
    Enter sends, Shift+Enter inserts a new line."""
    sendRequested = Signal()

    def __init__(self, max_lines=INPUT_MAX_LINES, parent=None):
        super().__init__(parent)
        self._max_lines = max_lines
        self.setObjectName("MessageInput")
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().documentLayout().documentSizeChanged.connect(self._fit)
        self._fit()

    def _chrome(self):
        # everything around the text: border + padding (top and bottom)
        return 2 * (INPUT_BORDER + INPUT_PAD_Y)

    def _fit(self, *_):
        doc = self.document()
        margin = int(doc.documentMargin() * 2)
        line = self.fontMetrics().lineSpacing()
        text_h = int(doc.size().height())
        one_line = line + margin
        max_h = self._max_lines * line + margin
        wanted = max(one_line, min(text_h, max_h))
        self.setFixedHeight(wanted + self._chrome())
        # beyond the limit it turns into a scrolling view of the text
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if text_h > max_h else Qt.ScrollBarAlwaysOff)
        self.ensureCursorVisible()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()                                 # width changed -> lines re-wrap

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                self.insertPlainText("\n")          # a real new line, not a rich-text soft break
            else:
                self.sendRequested.emit()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------------------
# list delegates (paint rows directly: cheap with hundreds of chats / members)
# ---------------------------------------------------------------------------------------
class ChatListDelegate(QStyledItemDelegate):
    ROW_H = 62
    PAD = 12

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, painter, option, index):
        chat = index.data(Qt.UserRole) or {}
        selected = bool(option.state & QStyle.State_Selected)
        unread = int(chat.get("unread", 0) or 0)
        rect = option.rect
        painter.save()
        painter.fillRect(rect, QColor(BLACK if selected else WHITE))

        name_font = QFont(option.font)
        name_font.setPointSizeF(13)
        name_font.setBold(False)
        text_w = rect.width() - 2 * self.PAD
        name = ("[DM] " if chat.get("is_dm") else "") + str(chat.get("name", ""))
        painter.setFont(name_font)
        painter.setPen(QColor(WHITE if selected else BLACK))
        painter.drawText(QRect(rect.left() + self.PAD, rect.top() + 7, text_w, 28),
                         Qt.AlignVCenter | Qt.AlignLeft,
                         QFontMetrics(name_font).elidedText(name, Qt.ElideRight, text_w))

        act_font = QFont(option.font)
        act_font.setPointSizeF(10)
        act_font.setBold(True)
        stamp = _as_datetime(chat.get("last_activity"))
        if chat.get("pending"):                 # invited, not joined yet
            line = PENDING_TEXT
        else:
            line = f"({unread})" + (f" - {format_activity_time(stamp)}" if stamp else "")
        painter.setFont(act_font)
        painter.setPen(QColor(activity_color(selected, unread or chat.get("pending"))))
        painter.drawText(QRect(rect.left() + self.PAD, rect.top() + 35, text_w, 20),
                         Qt.AlignVCenter | Qt.AlignLeft, line)
        painter.restore()


class MemberListDelegate(QStyledItemDelegate):
    ROW_H = 56
    LEFT = 14

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, painter, option, index):
        m = index.data(Qt.UserRole) or {}
        fg, bg = m.get("style", DF_USER_STYLE)
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(rect, QColor(WHITE))

        name_font = QFont(option.font)
        name_font.setPointSizeF(12)
        name_font.setBold(True)
        fm = QFontMetrics(name_font)
        name = str(m.get("username", ""))
        label = f"{name} (You)" if m.get("is_me") else name
        x0 = rect.left() + self.LEFT + 22
        avail = rect.width() - (x0 - rect.left()) - 10 - 2 * BADGE_PAD_X
        label = fm.elidedText(label, Qt.ElideRight, max(10, avail))
        badge = QRect(x0, rect.top() + 7, fm.horizontalAdvance(label) + 2 * BADGE_PAD_X,
                      fm.height() + 2 * BADGE_PAD_Y)
        painter.fillRect(badge, QColor(bg))
        painter.setFont(name_font)
        painter.setPen(QColor(fg))
        painter.drawText(badge, Qt.AlignCenter, label)

        # online = filled dot, offline = hollow dot
        online = bool(m.get("online"))
        centre = QPointF(rect.left() + self.LEFT + 5, badge.center().y() + 0.5)
        pen = QPen(QColor(BLACK), 2)
        painter.setPen(pen)
        painter.setBrush(QColor(BLACK) if online else Qt.NoBrush)
        painter.drawEllipse(centre, 4.5, 4.5)

        status_font = QFont(option.font)
        status_font.setPointSizeF(9)
        painter.setFont(status_font)
        painter.setPen(QColor(BLACK))
        painter.drawText(QRect(x0, badge.bottom() + 4, rect.width() - 30, 18),
                         Qt.AlignVCenter | Qt.AlignLeft, "Online" if online else "Offline")
        painter.restore()


# ---------------------------------------------------------------------------------------
# styling (palette tokens only)
# ---------------------------------------------------------------------------------------
_CHAT_QSS = Template("""
/* black tabs sitting on the top-left corner of every panel */
QFrame#PanelTag { background-color: $black; }
QLabel#PanelTagText {
    background-color: transparent; color: $white; font-size: 17pt;
    font-style: italic; text-decoration: underline; letter-spacing: 1px;
}

QToolButton { background-color: transparent; border: none; padding: 2px; }
QToolButton:pressed { background-color: $blue; }

/* directory: profile + chat list */
QFrame#ProfileBox { background-color: $white; }
QPushButton#ProfileButton { padding: 5px 8px; font-size: 12pt; letter-spacing: 0px; }
QPushButton#LinkButton {
    background-color: transparent; color: $black; border: none;
    padding: 4px; font-size: 12pt; letter-spacing: 0px;
}
QPushButton#LinkButton:hover { text-decoration: underline; }
QPushButton#LinkButton:pressed { background-color: transparent; color: $blue; }
QFrame#ProfileDivider { background-color: $black; border: none; }
QListWidget#ChatList, QListWidget#MemberList {
    border: none; outline: 0; background-color: $white;
}
QPushButton#NewGroupButton, QPushButton#BrowseGroupsButton { font-size: 14pt; padding: 11px; border: none; }
QPushButton#NewGroupButton:pressed, QPushButton#BrowseGroupsButton:pressed { background-color: $blue; color: $white; }
QPushButton#BrowseGroupsButton { border-bottom: 2px solid $white; }

/* chat panel */
QFrame#ChatHeader { background-color: $black; }
QLabel#ChatTitle {
    background-color: transparent; color: $white; font-size: 19pt; letter-spacing: 1px;
}
QScrollArea#MessageScroll { border: none; background-color: $white; }
QWidget#MessageContainer { background-color: $white; }
QFrame#Message { border: none; }
QFrame#OwnMessage { border: 2px solid $black; background-color: $white; }
QLabel#MessageTime { font-size: 9pt; }
QLabel#MessageBody { font-size: 12pt; }
QFrame#DividerLine { background-color: $black; border: none; }
QLabel#DividerText { font-size: 9pt; letter-spacing: 1px; }
QTextEdit#MessageInput {
    border: ${border}px solid $black; padding: ${pad}px 6px; font-size: 13pt;
    placeholder-text-color: rgba(23, 23, 23, 140);
    selection-background-color: $black; selection-color: $white;
}
QTextEdit#MessageInput:focus { border: ${border}px solid $blue; }
QLabel#HintLabel { font-size: 8pt; }

/* members + summary */
QLabel#MemberCount { font-size: 10pt; padding: 6px 12px 2px 12px; }
QPushButton#GenerateButton { padding: 4px 10px; font-size: 11pt; letter-spacing: 0px; }
QTextBrowser#SummaryText { border: none; padding: 8px; font-size: 11pt; }

/* group invitation page */
QLabel#InviteText { font-size: 19pt; }
QLabel#InviteError { color: $red; font-size: 12pt; }
QPushButton#InviteButton { font-size: 15pt; padding: 10px 16px; min-width: 90px; }

/* right-click menu of a member */
QMenu { background-color: $white; border: 3px solid $black; padding: 0px; }
QMenu::item { background-color: transparent; color: $black; padding: 7px 26px; font-size: 12pt; }
QMenu::item:selected { background-color: $black; color: $white; }

/* scroll bars */
QScrollBar:vertical {
    background-color: $white; width: 14px; margin: 0; border-left: 2px solid $black;
}
QScrollBar::handle:vertical { background-color: $black; min-height: 28px; margin: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; width: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background-color: $white; }
""").substitute(PALETTE, border=INPUT_BORDER, pad=INPUT_PAD_Y)


# ---------------------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------------------
class ChatPage(QWidget):
    logout_requested = Signal()             # main.py: disconnect the socket, back to the login page

    def __init__(self, parent=None):
        super().__init__(parent)
        self._me = ""                       # current user's name
        self._chat_id = None                # selected chat
        self._user_styles = {}              # username.lower() -> (text colour, background)
        self._members = []                  # members of the selected chat
        self._online = []                   # everybody online
        self._members_mode = MEMBERS
        self._messages = []
        self._messages_chat = None          # chat the shown messages belong to (None = not loaded yet)
        self._first_unread = None
        self._scroll_to_new = False
        self._stick_to_bottom = True
        self._dialog = None                 # the pop-up that is open, if any
        self._dialog_kind = None
        self._dialog_values = {}
        self._menu = None                   # the member right-click menu
        self._pending = False               # the selected chat is an invitation
        self._invite_busy = False
        self._new_marker = None             # the NEW divider widget
        # backend state (see attach / start_session)
        self.api = None                     # api.Api, set by main.py
        self.side = None                    # api.SideChannel: second connection for the summary
        self.session = None                 # main.Session while logged in
        self._gen = 0                       # bumps on reset: replies for an older session are dropped
        self._my_id = None                  # current user's user_id
        self._loading_chat = None           # chat whose info / messages are on their way
        self._load_seq = 0                  # bumps on every select_chat: replies of an older load are dropped
        self._early = {}                    # chat_id -> pushes that arrived while its messages loaded
        self._refreshing = False            # GET chats in flight
        self._refresh_again = False
        self._after_refresh = []
        self._summary_chat = None           # chat the summary text belongs to
        self._summary_seq = 0
        self._summary_running = None        # _summary_seq of the summary on its way, if any
        self._read_upto = {}                # chat_id -> newest message the server has as read
        self._sending = None                # (chat_id, text) of the message on its way
        self._groups_seq = 0                # bumps on every GET chats/groups: an older answer is dropped
        self.setStyleSheet(_CHAT_QSS)
        self.init_ui()
        self._hint_text = self.hint_label.text()
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(lambda: self.hint_label.setText(self._hint_text))

    # ------------------------------------------------------------------ building the UI
    def _make_tab(self, text, button=None):
        tab = QFrame()
        tab.setObjectName("PanelTag")
        tab.setFixedSize(TAB_WIDTH, TAB_HEIGHT)
        row = QHBoxLayout(tab)
        row.setContentsMargins(6, 0, 6, 0)
        label = QLabel(text)
        label.setObjectName("PanelTagText")
        tab.label = label                   # so the tab can be retitled (MEMBERS / ONLINE)
        row.addWidget(label)
        row.addStretch(1)
        if button is not None:
            row.addWidget(button)
        return tab

    @staticmethod
    def _icon_button(kind, color, tooltip, size=24):
        btn = QToolButton()
        btn.setIcon(make_icon(kind, color))
        btn.setIconSize(QSize(size, size))
        btn.setToolTip(tooltip)
        btn.setAccessibleName(tooltip)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    @staticmethod
    def _column(tab_row, frame):
        col = QVBoxLayout()
        col.setSpacing(0)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(tab_row, 0, Qt.AlignLeft)
        col.addWidget(frame, 1)
        return col

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # 1. DIRECTORY (left)
        # ================= 1. DIRECTORY (left) =================
        dir_frame = QFrame()
        dir_frame.setObjectName("PanelFrame")
        dir_layout = QVBoxLayout(dir_frame)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(0)

        profile = QFrame()
        profile.setObjectName("ProfileBox")
        profile_layout = QVBoxLayout(profile)
        profile_layout.setContentsMargins(10, 10, 10, 8)
        profile_layout.setSpacing(6)
        self.profile_name_row = QHBoxLayout()
        self.profile_name_row.setContentsMargins(0, 0, 0, 2)
        self.profile_name_holder = QWidget()
        self.profile_name_holder.setLayout(self.profile_name_row)
        profile_layout.addWidget(self.profile_name_holder)

        self.edit_profile_btn = QPushButton(" Edit profile")
        self.edit_profile_btn.setObjectName("ProfileButton")
        self.edit_profile_btn.setIcon(make_icon("pencil", WHITE))
        self.logout_btn = QPushButton(" Log out")
        self.logout_btn.setObjectName("ProfileButton")
        self.logout_btn.setIcon(make_icon("logout", WHITE))
        self.change_password_btn = QPushButton("Change password")
        self.change_password_btn.setObjectName("LinkButton")
        for b in (self.edit_profile_btn, self.logout_btn, self.change_password_btn):
            b.setIconSize(QSize(18, 18))
            b.setCursor(Qt.PointingHandCursor)
            profile_layout.addWidget(b)
        dir_layout.addWidget(profile)

        # the border line between the profile and the chat list
        self.profile_divider = QFrame()
        self.profile_divider.setObjectName("ProfileDivider")
        self.profile_divider.setFixedHeight(4)
        dir_layout.addWidget(self.profile_divider)

        self.chat_list = QListWidget()
        self.chat_list.setObjectName("ChatList")
        self.chat_list.setItemDelegate(ChatListDelegate(self.chat_list))
        self.chat_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.chat_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.chat_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chat_list.setUniformItemSizes(True)
        dir_layout.addWidget(self.chat_list, 1)

        self.browse_groups_btn = QPushButton("Browse Groups")
        self.browse_groups_btn.setObjectName("BrowseGroupsButton")
        self.new_group_btn = QPushButton("+   New Group")
        self.new_group_btn.setObjectName("NewGroupButton")
        for b in (self.browse_groups_btn, self.new_group_btn):
            b.setCursor(Qt.PointingHandCursor)
            dir_layout.addWidget(b)

        left = self._column(self._make_tab("DIRECTORY"), dir_frame)

        # 2. CHAT (center)
        # ================= 2. CHAT (center) =================
        chat_frame = QFrame()
        chat_frame.setObjectName("PanelFrame")
        chat_layout = QVBoxLayout(chat_frame)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("ChatHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(14, 8, 10, 8)
        self.chat_title = ElidedLabel("")
        self.chat_title.setObjectName("ChatTitle")
        header_row.addWidget(self.chat_title, 1)
        self.add_people_btn = self._icon_button("people_plus", WHITE, "Add people to group", 30)
        header_row.addWidget(self.add_people_btn)
        self.add_people_btn.hide()          # invitations are off: people join groups only by themselves (R10)
        chat_layout.addWidget(header)

        self.chat_frame = chat_frame
        self.chat_stack = QStackedWidget()          # 0: conversation, 1: invitation
        conversation = QWidget()
        conv_layout = QVBoxLayout(conversation)
        conv_layout.setContentsMargins(0, 0, 0, 0)
        conv_layout.setSpacing(0)

        self.message_scroll = QScrollArea()
        self.message_scroll.setObjectName("MessageScroll")
        self.message_scroll.setWidgetResizable(True)
        self.message_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.message_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        container = MessageContainer()
        container.setObjectName("MessageContainer")
        self.message_layout = QVBoxLayout(container)
        self.message_layout.setContentsMargins(12, 10, 12, 10)
        self.message_layout.setSpacing(8)
        self.message_layout.addStretch(1)
        self.message_scroll.setWidget(container)
        bar = self.message_scroll.verticalScrollBar()
        bar.rangeChanged.connect(self._on_scroll_range_changed)
        bar.valueChanged.connect(self._on_scroll_value_changed)
        conv_layout.addWidget(self.message_scroll, 1)

        entry = QWidget()
        self.entry_layout = entry_layout = QVBoxLayout(entry)
        entry_layout.setContentsMargins(10, 8, 10, ENTRY_MARGIN_BOTTOM)
        entry_layout.setSpacing(3)
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.msg_input = AutoGrowTextEdit()
        self.msg_input.setPlaceholderText(INPUT_PLACEHOLDER)
        input_row.addWidget(self.msg_input, 1)
        self.send_btn = self._icon_button("send", BLACK, "Send message", 30)
        input_row.addWidget(self.send_btn, 0, Qt.AlignBottom)
        entry_layout.addLayout(input_row)
        self.hint_label = hint = QLabel("Enter to send · Shift + Enter for a new line")
        hint.setObjectName("HintLabel")
        entry_layout.addWidget(hint)
        conv_layout.addWidget(entry)
        self._sync_input_gap()
        self.chat_stack.addWidget(conversation)

        # invitation page: no messages, just the question and Accept / Reject
        invite = QWidget()
        invite_col = QVBoxLayout(invite)
        invite_col.setContentsMargins(24, 24, 24, 24)
        invite_col.setSpacing(18)
        invite_col.addStretch(1)
        self.invite_text = QLabel("")
        self.invite_text.setObjectName("InviteText")
        self.invite_text.setTextFormat(Qt.PlainText)        # holds a group name somebody else chose
        self.invite_text.setAlignment(Qt.AlignCenter)
        self.invite_text.setWordWrap(True)
        self.invite_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)    # never widens the column
        invite_col.addWidget(self.invite_text)
        invite_buttons = QHBoxLayout()
        invite_buttons.setSpacing(16)
        invite_buttons.addStretch(1)
        self.accept_btn = QPushButton("Accept")
        self.reject_btn = QPushButton("Reject")
        for b in (self.accept_btn, self.reject_btn):
            b.setObjectName("InviteButton")
            b.setCursor(Qt.PointingHandCursor)
            invite_buttons.addWidget(b)
        invite_buttons.addStretch(1)
        invite_col.addLayout(invite_buttons)
        self.invite_error = QLabel("")
        self.invite_error.setObjectName("InviteError")
        self.invite_error.setAlignment(Qt.AlignCenter)
        self.invite_error.setWordWrap(True)
        invite_col.addWidget(self.invite_error)
        invite_col.addStretch(1)
        self.chat_stack.addWidget(invite)
        chat_layout.addWidget(self.chat_stack, 1)

        center = self._column(self._make_tab("CHAT"), chat_frame)

        # 3. MEMBERS + SUMMARY (right)
        # ================= 3. MEMBERS + SUMMARY (right) =================
        members_frame = QFrame()
        members_frame.setObjectName("PanelFrame")
        members_layout = QVBoxLayout(members_frame)
        members_layout.setContentsMargins(0, 0, 0, 0)
        members_layout.setSpacing(0)
        self.members_count = QLabel("0/0 ONLINE")
        self.members_count.setObjectName("MemberCount")
        members_layout.addWidget(self.members_count)
        self.members_list = QListWidget()
        self.members_list.setObjectName("MemberList")
        self.members_list.setItemDelegate(MemberListDelegate(self.members_list))
        self.members_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.members_list.setFocusPolicy(Qt.NoFocus)
        self.members_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.members_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.members_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        members_layout.addWidget(self.members_list, 1)

        self.members_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.members_list.customContextMenuRequested.connect(self._on_member_context)

        self.switch_member_btn = self._icon_button("caret", WHITE, "Show online users", 22)
        self.members_tab = self._make_tab("MEMBERS", self.switch_member_btn)
        members_col = self._column(self.members_tab, members_frame)

        summary_frame = QFrame()
        summary_frame.setObjectName("PanelFrame")
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_text = QTextBrowser()
        self.summary_text.setObjectName("SummaryText")
        self.summary_text.setOpenLinks(False)
        self.summary_text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.summary_text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        summary_layout.addWidget(self.summary_text)

        # the Generate button sits at the side of the SUMMARY tab
        self.generate_summary_btn = QPushButton("Generate")
        self.generate_summary_btn.setObjectName("GenerateButton")
        self.generate_summary_btn.setToolTip("Generate Summary")
        self.generate_summary_btn.setCursor(Qt.PointingHandCursor)
        tab_row = QHBoxLayout()
        tab_row.setSpacing(0)
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.addWidget(self._make_tab("SUMMARY"))
        tab_row.addSpacing(10)                  # keeps the button visibly apart from the tab
        tab_row.addStretch(1)
        tab_row.addWidget(self.generate_summary_btn, 0, Qt.AlignBottom)
        tab_holder = QWidget()
        tab_holder.setLayout(tab_row)
        summary_col = QVBoxLayout()
        summary_col.setSpacing(0)
        summary_col.setContentsMargins(0, 0, 0, 0)
        summary_col.addWidget(tab_holder)
        summary_col.addWidget(summary_frame, 1)

        right = QVBoxLayout()
        right.setSpacing(12)
        right.addLayout(members_col, 5)
        right.addLayout(summary_col, 4)

        main_layout.addLayout(left, 22)
        main_layout.addLayout(center, 48)
        main_layout.addLayout(right, 21)

        # ================= interactions -> dummy functions =================
        self.edit_profile_btn.clicked.connect(self.edit_profile)
        self.logout_btn.clicked.connect(self.logout)
        self.change_password_btn.clicked.connect(self.change_password)
        self.new_group_btn.clicked.connect(self.new_group)
        self.browse_groups_btn.clicked.connect(self.browse_groups)
        self.generate_summary_btn.clicked.connect(self.generate_summary)
        self.switch_member_btn.clicked.connect(self.switch_member)
        self.add_people_btn.clicked.connect(self.add_people_to_group)
        self.send_btn.clicked.connect(self.send_message)
        self.accept_btn.clicked.connect(self.accept_invite)
        self.reject_btn.clicked.connect(self.reject_invite)
        self.msg_input.sendRequested.connect(self.send_message)
        self.chat_list.currentItemChanged.connect(self._on_chat_item_changed)

    # The buttons open pop-ups (dialogs.py). A pop-up's SAVE button calls one of the request_*
    # methods below; the backend's answer is reported with finish_dialog().
    # ------------------------------------------------------------------ buttons
    # The buttons open pop-ups (dialogs.py). A pop-up's SAVE button calls one of the dummy
    # request_* functions below; the backend's answer is reported with finish_dialog().
    def edit_profile(self):
        """Edit profile button -> pop-up with the user's name and colours."""
        fg, bg = self.user_style(self._me)
        self._open_dialog("profile", EditProfileDialog(self._me, fg, bg, self), self.request_edit_profile)

    def change_password(self):
        """Change password button -> pop-up."""
        self._open_dialog("password", ChangePasswordDialog(self), self.request_change_password)

    def new_group(self):
        """+ New Group button -> pop-up asking for the group name."""
        self._open_dialog("group", NewGroupDialog(self), self.request_new_group)

    def browse_groups(self):
        """Browse Groups button -> pop-up listing every group on the server with its members.
        JOIN calls request_join_group(chat_id)."""
        dialog = BrowseGroupsDialog(self)
        self._open_dialog("browse", dialog, self.request_join_group)
        if self._dialog is dialog:
            self.request_all_groups()

    def logout(self):
        """Log out button. main.py listens to logout_requested: it disconnects the socket,
        forgets the session and shows the login page again."""
        self.logout_requested.emit()

    def switch_member(self):
        """Arrow next to MEMBERS: toggles between the members of the selected chat and
        everybody who is online (the tab is then titled ONLINE)."""
        if self._members_mode == MEMBERS:
            self._members_mode = ONLINE
            self.request_online_users()
        else:
            self._members_mode = MEMBERS
            if self._chat_id is not None and not self._pending:
                self.request_group_members(self._chat_id)
        self._sync_members_view()

    # Generate button next to SUMMARY. -> ask the backend for a summary of the selected chat. When the reply arrives call set_summary(text).
    def generate_summary(self):
        """Generate button next to SUMMARY. -> GET chat/{chat_id}/summary {mode, count}
        (an AI summary of the latest messages; it can take a few seconds) -> set_summary(text).
        It goes over the second connection (api.SideChannel), so the other calls don't wait for it."""
        chat_id = self._chat_id
        if chat_id is None or self._pending or self.api is None or self._summary_busy():
            return
        self._summary_seq += 1
        seq, self._summary_chat = self._summary_seq, chat_id
        self._summary_running = seq
        self.set_summary("Generating summary...")
        self._sync_summary_button()

        def current():
            return seq == self._summary_seq and chat_id == self._chat_id

        def finished(text):
            if self._summary_running == seq:
                self._summary_running = None
            if current():
                self.set_summary(text)
                self._sync_summary_button()

        # GET chat/{chat_id}/summary: the newest 50 messages (the server may take a while)
        self._call(GET, f"chat/{chat_id}/summary", {"mode": "recent", "count": SUMMARY_COUNT},
                   lambda data: finished(data.get("summary") or "Nothing to summarize yet."),
                   lambda err: finished(f"Couldn't generate a summary: {err.message}"),
                   via=self.side)

    def _summary_busy(self):
        """A summary for the chat on screen is still being made."""
        return self._summary_running is not None and self._summary_running == self._summary_seq

    def _sync_summary_button(self):
        self.generate_summary_btn.setEnabled(not self._pending and not self._summary_busy())

    def add_people_to_group(self):
        """Add-people icon in the chat header -> pop-up: search the online users and everyone the
        user has a DM with, pick one, INVITE calls request_invite(username, chat_id, user_id)."""
        if self._chat_id is None or self._pending or self._chat_is_dm():
            return
        chat_id = self._chat_id
        dialog = AddPeopleDialog(chat_id, self)
        dialog.searched.connect(lambda query: self.request_invitees(chat_id, query))
        self._open_dialog("add_people", dialog, self.request_invite)
        if self._dialog is dialog:
            dialog.search("")                       # list everybody to start with

    def set_invitees(self, chat_id, query, users):
        """Reply to request_invitees: users = [{'user_id', 'username'}] matching `query`."""
        d = self._dialog
        if d is not None and self._dialog_kind == "add_people" and d.chat_id == chat_id:
            d.set_users(query, users)

    # Send button / Enter in the chat box. -> POST /chat/{chat_id}/message Read the text with message_text(); call clear_input() once the backend accepted it.
    def send_message(self):
        """Send button / Enter in the chat box. -> POST chat/{chat_id}/message {content}
        The backend takes "content" or "text" on the way in and spells it "text" in the message
        that comes back; "content" is sent because every build of the backend accepts it.
        The box is cleared once the backend accepted the message."""
        text, chat_id = self.message_text(), self._chat_id
        if not text or chat_id is None or self._pending or self.api is None:
            return
        if len(text) > MESSAGE_MAX_LEN:
            self.show_notice(f"Message too long ({len(text)}/{MESSAGE_MAX_LEN} characters)")
            return
        if self._sending == (chat_id, text):
            return                                  # the same text is already on its way (Enter twice)
        self._sending = (chat_id, text)

        def sent(data):
            self._sending = None
            if self.message_text() == text:
                self.clear_input()
            msg = _message_row(data.get("message") or data, self._my_id)
            msg["own"] = True
            self.append_message(msg, chat_id)       # ignored if another chat is open by now
            self._touch_chat(chat_id, msg["time"])

        def failed(err):
            self._sending = None
            self.show_notice(f"Couldn't send: {err.message}")

        self._call(POST, f"chat/{chat_id}/message", {"content": text}, sent, failed)

    # A chat was clicked in the directory. -> GET /chat/{chat_id}/info and /messages, then feed set_members(..., chat_id), set_messages(..., chat_id=chat_id).
    def select_chat(self, chat_id):
        """A chat was clicked in the directory. -> GET chat/{chat_id}/info and chat/{chat_id}/messages,
        then set_members(..., chat_id), set_messages(..., chat_id=chat_id). When the first unread
        message is older than the newest page, older pages (before_id) are loaded until it is in, so
        the NEW line is drawn and no unread message is marked read without being shown."""
        if chat_id is None or self.api is None:
            return
        chat = self._chat_data(chat_id)
        if chat is None or chat.get("pending"):
            return
        if chat_id != self._summary_chat:            # the summary belongs to the chat it was made for
            self._summary_seq += 1
            self._summary_chat = None
            self.summary_text.clear()
        self._sync_summary_button()
        self._load_seq += 1
        token = self._load_seq
        self._loading_chat = chat_id
        self._early[chat_id] = []
        self.request_group_members(chat_id)  # GET chat/{id}/info
        st = {"rows": [], "first": None, "older": 0}    # rows loaded so far (oldest first)

        def current():
            return token == self._load_seq and chat_id == self._chat_id and not self._pending

        def show(first):
            if self._loading_chat == chat_id:
                self._loading_chat = None
            rows = st["rows"]
            if st["first"] is None and rows:
                self._read_upto[chat_id] = rows[-1]["id"]      # the server has all of these as read
            seen = {m["id"] for m in rows}
            # pushes that came while loading (counted as unread meanwhile; cleared at the bottom)
            rows = rows + [m for m in self._early.pop(chat_id, []) if m["id"] not in seen]
            self.set_messages(rows, first_unread_id=first, chat_id=chat_id)

        def loaded(data):
            if not current():
                return                              # the user moved on: a late reply
            st["rows"] = [_message_row(m, self._my_id) for m in data.get("messages", [])] + st["rows"]
            if st["older"] == 0:
                st["first"] = data.get("first_unread_id")
            rows, first = st["rows"], st["first"]
            if first is not None and rows and _id_before(first, rows[0]["id"]):
                if data.get("has_more") and st["older"] < OLDER_PAGES_MAX:
                    st["older"] += 1
                    self._call(GET, f"chat/{chat_id}/messages", {"count": OLDER_PAGE, "before_id": rows[0]["id"]},
                               loaded, failed)
                    return
                first = rows[0]["id"]               # still further back: NEW above the oldest one shown
            show(first)

        def failed(err):
            if not current():
                return
            if st["rows"]:                          # an older page failed: show what is here
                show(st["rows"][0]["id"])
            elif self._loading_chat == chat_id:
                self._loading_chat = None
            self.show_notice(f"Couldn't load the messages: {err.message}")

        self._call(GET, f"chat/{chat_id}/messages", {"count": MESSAGE_PAGE}, loaded, failed)

    # Each one sends a RequestCord through api.py (README: RequestCord Calls). For the pop-up
    # ones the answer goes to finish_dialog(ok, message, field).
    def request_edit_profile(self, username, text_color, background):
        """PATCH users/profile  {username, text_color, background}: only the fields that changed."""
        dialog = self._dialog
        fg, bg = self.user_style(self._me)
        body = {}
        if username != self._me:
            body["username"] = username
        if text_color != fg.upper():            # styles.py writes its own defaults in lower case
            body["text_color"] = text_color
        if background != bg.upper():
            body["background"] = background
        if not body:
            self._finish_for(dialog, True)
            return

        def saved(data):
            u = data.get("user") or data
            values = {"username": u.get("username") or username,
                      "text_color": u.get("text_color") or text_color,
                      "background": u.get("background") or background}
            if self._dialog is dialog:
                self._dialog_values = values
                self.finish_dialog(True)
            else:                                   # the pop-up was closed meanwhile: still apply it
                self._apply_dialog_result("profile", values)

        def failed(err):
            field = {"username": "username", "text_color": "text_color",
                     "background": "background"}.get(err.field)
            self._finish_for(dialog, False, err.message, field)

        self._call(PATCH, "users/profile", body, saved, failed)

    def request_change_password(self, new_password):
        """PATCH users/password  {new_password}. The pop-up asks for no current password, and the
        session token does not change, so this connection and the summary's keep working."""
        dialog = self._dialog
        self._call(PATCH, "users/password", {"new_password": new_password},
                   lambda data: self._finish_for(dialog, True),
                   lambda err: self._finish_for(dialog, False, err.message,
                                                "new_password" if err.field == "new_password" else None))

    # POST chats {name}
    def request_new_group(self, name):
        """POST chats {name} -> the directory is refreshed and the new group opens."""
        dialog = self._dialog

        def created(data):
            self._finish_for(dialog, True)
            chat_id = (data.get("chat") or data).get("chat_id")
            self.refresh_chats(then=lambda: self.open_chat(chat_id))

        self._call(POST, "chats", {"name": name}, created,
                   lambda err: self._finish_for(dialog, False, err.message,
                                                "name" if err.field == "name" else None))

    def request_all_groups(self):
        """GET chats/groups {count, offset}, page after page while has_more -> set_all_groups(groups).
        Only the newest read is shown, so an older answer cannot hide what a push just changed."""
        self._groups_seq += 1
        seq, groups = self._groups_seq, []

        def got(data):
            if seq != self._groups_seq:
                return
            page = data.get("groups") or []
            groups.extend(page)
            if data.get("has_more") and page:
                self._call(GET, "chats/groups", {"count": GROUP_PAGE, "offset": len(groups)}, got, failed)
            else:
                self.set_all_groups(groups)

        def failed(err):
            d = self._dialog
            if seq == self._groups_seq and d is not None and self._dialog_kind == "browse":
                d.groups_field.show_message(err.message)

        self._call(GET, "chats/groups", {"count": GROUP_PAGE}, got, failed)

    def request_join_group(self, chat_id):
        """JOIN in the Browse groups pop-up: POST chat/{chat_id}/join. The user joins by themselves (a
        pending invitation to the group counts as accepted); the pop-up closes and the group opens."""
        dialog = self._dialog

        def joined(data):
            self._finish_for(dialog, True)
            self.refresh_chats(then=lambda: self.open_chat(chat_id))

        self._call(POST, f"chat/{chat_id}/join", None, joined,
                   lambda err: self._finish_for(dialog, False, err.message))

    # POST chat/{chat_id}/invite {user_id}
    def request_invite(self, username, chat_id, user_id=None):
        """POST chat/{chat_id}/invite  {user_id}
        user_id is known when the user was picked in the Invite people pop-up; from the right-click
        pop-up only the name is known, so it comes from the member row."""
        dialog = self._dialog

        def failed(err):
            self._finish_for(dialog, False, err.message)

        def invite(uid):
            self._call(POST, f"chat/{chat_id}/invite", {"user_id": uid},
                       lambda data: self._finish_for(dialog, True), failed)

        if user_id is not None:
            invite(user_id)
        else:
            self._with_user_id(username, invite, failed)

    def request_invitees(self, chat_id, query):
        """GET chat/{chat_id}/invitees  {query} -> set_invitees(chat_id, query, users)"""
        def found(data):
            users = [{"user_id": u.get("user_id"), "username": u.get("username", "")}
                     for u in data.get("users", [])]
            self.set_invitees(chat_id, query, users)

        def failed(err):
            d = self._dialog
            if (d is not None and self._dialog_kind == "add_people" and d.chat_id == chat_id
                    and getattr(d, "_query", query) == query):
                d.results.show_message(err.message)

        self._call(GET, f"chat/{chat_id}/invitees", {"query": query}, found, failed)

    # POST users/{user_id}/dm {message}
    def request_message(self, username, greeting):
        """POST users/{user_id}/dm  {message: greeting}. The backend opens the DM at once (or reuses
        the existing one) and the client switches to it."""
        dialog = self._dialog

        def failed(err):
            self._finish_for(dialog, False, err.message)

        def sent(data):
            self._finish_for(dialog, True)
            chat_id = data.get("chat_id") or (data.get("chat") or {}).get("chat_id")
            if not chat_id:
                self.show_notice(f"The DM with {username} did not open")
                return
            self.refresh_chats(then=lambda: self.open_chat(chat_id))

        self._with_user_id(username, lambda uid: self._call(POST, f"users/{uid}/dm", {"message": greeting},
                                                            sent, failed), failed)

    def request_user_groups(self, username):
        """GET users/{user_id}/groups -> set_user_groups(username, groups)
        (or finish_dialog(False, message) when it failed)."""
        dialog = self._dialog

        def failed(err):
            self._finish_for(dialog, False, err.message)

        def got(data):
            self.set_user_groups(username, data.get("groups", []))

        self._with_user_id(username, lambda uid: self._call(GET, f"users/{uid}/groups", None, got, failed),
                           failed)

    def request_accept_invite(self, chat_id):
        """Accept button on an invitation: POST chat/{chat_id}/invite/accept
        -> resolve_invite / invite_failed."""
        def joined(data):
            self.resolve_invite(chat_id, True)      # loads the chat if it is open
            self.refresh_chats()                    # real unread count and last activity

        self._call(POST, f"chat/{chat_id}/invite/accept", None, joined,
                   lambda err: self.invite_failed(chat_id, err.message))

    def request_reject_invite(self, chat_id):
        """Reject button on an invitation: POST chat/{chat_id}/invite/reject
        -> resolve_invite / invite_failed."""
        self._call(POST, f"chat/{chat_id}/invite/reject", None,
                   lambda data: self.resolve_invite(chat_id, False),
                   lambda err: self.invite_failed(chat_id, err.message))

    # GET chat/{chat_id}/info -> set_members
    def request_group_members(self, chat_id):
        """GET chat/{chat_id}/info -> set_members(members, chat_id)"""
        def got(data):
            members = (data.get("chat") or data).get("members", [])
            self._absorb_users(members)
            self.set_members([_member_row(m, self._my_id) for m in members], chat_id)

        self._call(GET, f"chat/{chat_id}/info", None, got,
                   lambda err: chat_id == self._chat_id and self.show_notice(
                       f"Couldn't load the members: {err.message}"))

    # GET users/online -> set_online_users
    def request_online_users(self):
        """GET users/online -> set_online_users(users)"""
        def got(data):
            users = data.get("users", [])
            self._absorb_users(users)
            self.set_online_users([_member_row(u, self._my_id) for u in users])

        self._call(GET, "users/online", None, got)

    # POST chat/{chat_id}/read {message_id: newest message shown}
    def request_mark_read(self, chat_id, message_id):
        """The user is at the bottom of the chat: POST chat/{chat_id}/read {message_id: newest shown}."""
        def failed(err):
            if self._read_upto.get(chat_id) == message_id:
                self._read_upto.pop(chat_id, None)  # not read on the server: the next look tries again

        self._call(POST, f"chat/{chat_id}/read", {"message_id": message_id}, None, failed)

    # called by main.py
    def attach(self, api, side=None):
        """Wires the page to the dispatcher (api.py): its calls and the server pushes.
        side: the SideChannel for the summary (without one it uses the main connection)."""
        self.api, self.side = api, side
        for path, handler in (("chat/new_message", self._on_new_message),
                              ("chats/new", self._on_chats_changed),
                              ("chat/members_changed", self._on_members_changed),
                              ("users/profile_changed", self._on_profile_changed),
                              ("users/status", self._on_status_event),
                              ("chats/group_created", self._refresh_browse),
                              ("chats/group_deleted", self._on_group_deleted)):
            api.on(path, lambda data, h=handler: self.session is not None and h(data))

    def start_session(self, user, session):
        """Logged in: show the profile, then GET users/info and the chat list."""
        self.session = session
        self._my_id = str(user.get("user_id") or session.user_id)
        self._apply_me(user)
        self._call(GET, "users/info", None, lambda data: self._apply_me(data.get("user") or data))
        self.refresh_chats()

    def _apply_me(self, user):
        name = user.get("username")
        if not name:
            return
        self._me = str(name)
        fg, bg = user.get("text_color"), user.get("background")
        if fg and bg:
            self.set_user_style(self._me, fg, bg)       # also redraws the profile badge
        else:
            self.set_profile(self._me)

    def show_notice(self, text):
        """A short error message where the 'Enter to send' hint is, for a few seconds."""
        self.hint_label.setText(str(text))
        self.hint_label.setToolTip(str(text))
        self._notice_timer.start(NOTICE_MS)

    def refresh_chats(self, then=None):
        """GET chats -> set_chats. The list holds the joined chats and the invitations that are
        still open (`pending`, drawn as [Pending]).
        `then` runs after the new list is shown (e.g. open_chat of a chat that was just made)."""
        if then is not None:
            self._after_refresh.append(then)
        if self.api is None or self.session is None:
            return
        if self._refreshing:
            self._refresh_again = True
            return
        self._refreshing, self._refresh_again = True, False

        def got(data):
            self._refreshing = False
            if self._refresh_again:             # something changed while this was on its way
                self.refresh_chats()
                return
            callbacks, self._after_refresh = self._after_refresh, []
            self._apply_chat_list(data)
            for callback in callbacks:
                callback()

        def failed(err):
            if self._refreshing:
                self._refreshing = False
                self.show_notice(f"Couldn't load the chats: {err.message}")

        self._call(GET, "chats", None, got, failed)

    def _call(self, method, url, data=None, ok=None, error=None, via=None):
        """api.request, but replies that arrive after a logout (or for an older login) are dropped.
        Errors without a handler are shown with show_notice. via: another connection (SideChannel)."""
        if self.api is None:
            return None
        gen = self._gen

        def guard(callback):
            def run(arg):
                if gen == self._gen and callback is not None:
                    callback(arg)
            return run

        if error is None:
            error = lambda err: self.show_notice(err.message)   # noqa: E731
        return (via or self.api).request(method, url, data, guard(ok), guard(error))

    def _finish_for(self, dialog, ok, message="", field=None):
        """finish_dialog, but only if that pop-up is still the one that is open."""
        if dialog is not None and self._dialog is dialog:
            self.finish_dialog(ok, message, field)

    def _with_user_id(self, username, then, failed):
        """then(user_id) for a name from the member / online list (GET users/search if unknown)."""
        for rows in (self._members, self._online):
            for row in rows:
                if row.get("username") == username and row.get("user_id"):
                    then(row["user_id"])
                    return

        def found(data):
            for u in data.get("users", []):
                if str(u.get("username", "")).lower() == str(username).lower():
                    then(u["user_id"])
                    return
            failed(ApiError(0, "USER_NOT_FOUND", f"Can't find the user {username}"))

        self._call(GET, "users/search", {"query": str(username)[:32], "count": 5}, found, failed)

    def _absorb_users(self, users):
        """Takes what the member / online rows say about people: the colours every message and badge
        is drawn in, and their current name. A fresh list is also where a rename shows up, since
        chat/members_changed says only which chat changed."""
        changed = False
        for u in users:
            name, uid = str(u.get("username") or ""), u.get("user_id")
            fg, bg = u.get("text_color"), u.get("background")
            if name and fg and bg and self._user_styles.get(name.lower()) != (fg, bg):
                self._user_styles[name.lower()] = (fg, bg)
                changed = True
            if not name or not uid:
                continue
            for msg in self._messages:
                if msg.get("sender_id") == uid and msg.get("sender") != name:
                    msg["sender"] = name
                    changed = True
        if changed and self._messages:
            self._render_messages(keep_scroll=True)

    def _touch_chat(self, chat_id, when):
        chat = self._chat_data(chat_id)
        if chat is not None and when is not None:
            self.set_chat_unread(chat_id, int(chat.get("unread", 0) or 0), when)

    def _apply_chat_list(self, chats_reply):
        # invitations are off (R10): a pending invitation from an older version is not listed;
        # the group still shows in Browse Groups, where JOIN works as usual
        rows = [_chat_row(c) for c in chats_reply.get("chats", []) if not c.get("pending")]
        rows.sort(key=lambda c: c.get("last_activity") or datetime.min, reverse=True)
        self.set_chats(rows, selected_id=self._chat_id)
        if self.chat_list.count() == 0:
            if self._chat_id is not None or self._pending:
                self._show_chat({})                 # the open chat is gone
            return
        chat_id = self._chat_id
        if (chat_id is not None and not self._pending and self._messages_chat != chat_id
                and self._loading_chat != chat_id):
            self.select_chat(chat_id)               # set_chats picked a chat that is not loaded yet
        else:
            self._maybe_mark_read()                 # the open chat now shows the server's count, which
                                                    # can predate a read sent a moment ago

    def _on_new_message(self, data):
        """chat/new_message: append it if that chat is open, otherwise count it as unread."""
        chat_id = data.get("chat_id")
        msg = _message_row(data.get("message"), self._my_id)
        chat = self._chat_data(chat_id)
        if chat is None or chat.get("pending"):
            self.refresh_chats()                    # a chat this list does not have yet
            return
        if chat_id == self._chat_id:
            if self._loading_chat == chat_id:
                self._early.setdefault(chat_id, []).append(msg)    # shown once the chat has loaded
                unread = int(chat.get("unread", 0) or 0) + (0 if msg["own"] else 1)
                self.set_chat_unread(chat_id, unread, msg["time"])
                return
            if self._messages_chat == chat_id:
                if not any(m.get("id") == msg["id"] for m in self._messages):
                    self.append_message(msg, chat_id)
                self._touch_chat(chat_id, msg["time"])
                return
        unread = int(chat.get("unread", 0) or 0) + (0 if msg["own"] else 1)
        self.set_chat_unread(chat_id, unread, msg["time"])

    def _on_status_event(self, data):
        """users/status {user_id, online}: the ONLINE list and the dots in the member list. The push
        carries no name or colours, so someone appearing for the first time needs the whole list."""
        uid, online = data.get("user_id"), bool(data.get("online"))
        if uid is None:
            return
        for m in self._members:
            if m.get("user_id") == uid:
                m["online"] = online
        known = next((u for u in self._online if u.get("user_id") == uid), None)
        if online and known is None:
            if self._members_mode == ONLINE:
                self.request_online_users()
            else:
                self._refresh_members()             # the dots are already right
            return
        if not online:
            self._online = [u for u in self._online if u.get("user_id") != uid]
        self._refresh_members()

    def _on_chats_changed(self, data):
        """chats/new {chat}: invited to a group, or a DM was opened with this user. The row is
        not kept from the push: GET chats lists the invitations too (`pending`), so the list it
        answers with is the whole truth and a row cannot be left behind once the invitation is
        answered or the inviter takes it back. An open Browse groups pop-up then marks the invitation."""
        self.refresh_chats(then=self._refresh_browse)

    def _on_profile_changed(self, data):
        """users/profile_changed {user}: somebody's new username and colours. chat/members_changed
        covers the chats shared with them; this also reaches the ONLINE list and an open Browse groups
        pop-up, where somebody the user shares no chat with would otherwise keep their old name."""
        user = data.get("user") or {}
        uid, name = user.get("user_id"), str(user.get("username") or "")
        if not uid or not name:
            return
        for rows in (self._members, self._online):
            for row in rows:
                if row.get("user_id") == uid:
                    row.update({"username": name, "text_color": user.get("text_color"),
                                "background": user.get("background")})
        self._absorb_users([user])
        self._refresh_members()
        self._refresh_browse()

    def _on_members_changed(self, data):
        """chat/members_changed {chat_id, change}: `joined`, `left`, `profile` (renamed or
        recoloured) or `invite_cancelled`. The push says no more than which chat changed, so the
        member list is read again; the directory too, because a DM is named after the other
        person, a group can have lost its last member, and a cancelled invitation leaves it.
        Joins and leaves reach everyone, which keeps an open Browse groups pop-up current."""
        chat_id = data.get("chat_id")
        if self._members_mode == ONLINE:
            self.request_online_users()             # a rename or a new colour shows up there too
        if self._chat_data(chat_id) is None:
            self.refresh_chats(then=self._refresh_browse)   # a chat this list does not have yet
            return
        if chat_id == self._chat_id and not self._pending:
            self.request_group_members(chat_id)  # somebody came or went: refresh the member list
        self.refresh_chats(then=self._refresh_browse)

    def _on_group_deleted(self, data):
        """chats/group_deleted {chat_id}: its last member left. An invitation to it leaves the directory."""
        if self._chat_data(data.get("chat_id")) is not None:
            self.refresh_chats(then=self._refresh_browse)
        else:
            self._refresh_browse()

    def _refresh_browse(self, *_):
        """chats/group_created, and every push that changes a group or its members: the Browse groups
        pop-up, if it is open, reads every group again."""
        if self._dialog is not None and self._dialog_kind == "browse":
            self.request_all_groups()

    # ------------------------------------------------------------------ pop-ups
    def _open_dialog(self, kind, dialog, request):
        if self._dialog is not None:
            dialog.deleteLater()
            return
        self._dialog, self._dialog_kind, self._dialog_values = dialog, kind, {}

        if request is not None:
            def submitted(values):
                self._dialog_values = dict(values)
                request(**values)

            dialog.submitted.connect(submitted)
        dialog.finished.connect(self._dialog_closed)
        dialog.open()

    def _dialog_closed(self, *_):
        dialog, self._dialog = self._dialog, None
        if dialog is not None:
            dialog.deleteLater()

    def close_dialog(self):
        if self._dialog is not None:
            self._dialog.reject()

    def finish_dialog(self, ok, message="", field=None):
        """The backend answered the open pop-up's request. ok -> it closes (and the change is
        applied here); not ok -> `message` appears after the label of `field` (or under the form)
        and the user can try again."""
        dialog = self._dialog
        if dialog is None:
            return
        if ok:
            self._apply_dialog_result(self._dialog_kind, self._dialog_values)
        dialog.finish(ok, message, field)

    def _apply_dialog_result(self, kind, values):
        if kind != "profile":
            return
        old, new = self._me, values["username"]
        if new != old:
            for rows in (self._members, self._online):
                for row in rows:
                    if row.get("username") == old:
                        row["username"] = new
            for msg in self._messages:
                if msg.get("sender") == old:
                    msg["sender"] = new
        self._me = new
        self.set_user_style(new, values["text_color"], values["background"])

    # ------------------------------------------------------------------ member right-click
    def _chat_data(self, chat_id):
        for i in range(self.chat_list.count()):
            chat = self.chat_list.item(i).data(Qt.UserRole) or {}
            if chat.get("chat_id") == chat_id:
                return chat
        return None

    def _chat_is_dm(self):
        chat = self._chat_data(self._chat_id)
        return bool(chat and chat.get("is_dm"))

    def _build_member_menu(self, username):
        """Group: Invite to group + Message.  DM: Invite to group only."""
        menu = QMenu(self.members_list)
        # "Invite to group" is off: people join groups only by themselves, with Browse Groups -> JOIN (R10)
        if not self._chat_is_dm():
            menu.addAction("Message").triggered.connect(lambda: self.message_member(username))
        menu.addAction("See Groups").triggered.connect(lambda: self.see_groups(username))
        return menu

    def _on_member_context(self, pos):
        item = self.members_list.itemAt(pos)
        if item is None:
            return
        member = item.data(Qt.UserRole) or {}
        if member.get("is_me"):
            return                                  # no need to invite or message yourself
        if self._menu is not None:
            self._menu.deleteLater()
        self._menu = self._build_member_menu(member.get("username", ""))
        self._menu.popup(self.members_list.viewport().mapToGlobal(pos))

    def invite_member(self, username):
        """'Invite to group': pop-up with a group selector."""
        groups = []
        for i in range(self.chat_list.count()):
            chat = self.chat_list.item(i).data(Qt.UserRole) or {}
            if chat.get("is_dm") or chat.get("pending"):
                continue                            # DMs aren't groups; an invitation isn't joined yet
            if self._members_mode == MEMBERS and chat.get("chat_id") == self._chat_id:
                continue                            # the member is already in this group
            groups.append({"chat_id": chat.get("chat_id"), "name": chat.get("name", "")})
        self._open_dialog("invite", InviteDialog(username, groups, self), self.request_invite)

    def see_groups(self, username):
        """'See Groups': pop-up listing every group the user is in."""
        dialog = GroupsDialog(username, self)
        self._open_dialog("groups", dialog, None)
        if self._dialog is dialog:
            self._dialog_values = {"username": username}
            self.request_user_groups(username)

    def set_user_groups(self, username, groups):
        """Reply to request_user_groups: groups = [{'chat_id', 'name'}]."""
        d = self._dialog
        if d is not None and self._dialog_kind == "groups" and self._dialog_values.get("username") == username:
            d.set_groups(groups)

    def set_all_groups(self, groups):
        """Reply to request_all_groups: every group with its members. A group with a [Pending]
        invitation in the directory is marked as one."""
        d = self._dialog
        if d is None or self._dialog_kind != "browse":
            return
        invited = set()
        for i in range(self.chat_list.count()):
            chat = self.chat_list.item(i).data(Qt.UserRole) or {}
            if chat.get("pending"):
                invited.add(chat.get("chat_id"))
        d.set_groups(groups, invited)

    def message_member(self, username):
        """'Message': pop-up with the initial greeting."""
        self._open_dialog("message", MessageDialog(username, self), self.request_message)

    # called by main.py and by the request_* replies
    # ------------------------------------------------------------------ data in (called by main.py)
    def message_text(self):
        return self.msg_input.toPlainText().strip()

    def clear_input(self):
        self.msg_input.clear()

    def current_chat_id(self):
        return self._chat_id

    def set_profile(self, username):
        self._me = str(username)
        self._clear_profile()
        fg, bg = self.user_style(self._me)
        badge = UserBadge(self._me, fg, bg)
        badge.setStyleSheet(badge.styleSheet() + " font-size: 15pt;")
        self.profile_name_row.addWidget(badge, 0, Qt.AlignLeft)
        self.profile_name_row.addStretch(1)

    def _clear_profile(self):
        while self.profile_name_row.count():
            old = self.profile_name_row.takeAt(0).widget()
            if old is not None:
                old.setParent(None)
                old.deleteLater()

    def user_style(self, username):
        return self._user_styles.get(str(username).lower()) or DF_USER_STYLE

    def set_user_style(self, username, text_color, background):
        """Give one user a particular text colour and background (e.g. from their profile)."""
        self._user_styles[str(username).lower()] = (text_color, background)
        if self._me:
            self.set_profile(self._me)
        self._refresh_members()
        if self._messages:
            self._render_messages(keep_scroll=True)

    def set_chats(self, chats, selected_id=None):
        """chats: [{'chat_id', 'name', 'unread': int, 'last_activity': datetime, 'is_dm': bool}]"""
        self.chat_list.blockSignals(True)
        self.chat_list.clear()
        pick = None
        for chat in chats:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, dict(chat))
            self.chat_list.addItem(item)
            if chat.get("chat_id") == (selected_id if selected_id is not None else self._chat_id):
                pick = item
        if pick is None and self.chat_list.count():
            pick = self.chat_list.item(0)
        if pick is not None:
            self.chat_list.setCurrentItem(pick)
            self._show_chat(pick.data(Qt.UserRole))
        self.chat_list.blockSignals(False)
        self.chat_list.viewport().update()

    def set_chat_unread(self, chat_id, count, last_activity=None):
        """The number in '(n) - time' of one chat (a message arrived in a chat that is not open,
        or the chat was read elsewhere)."""
        for i in range(self.chat_list.count()):
            item = self.chat_list.item(i)
            chat = dict(item.data(Qt.UserRole) or {})
            if chat.get("chat_id") == chat_id:
                chat["unread"] = max(0, int(count))
                if last_activity is not None:
                    chat["last_activity"] = last_activity
                item.setData(Qt.UserRole, chat)
        self.chat_list.viewport().update()

    def set_members(self, members, chat_id=None):
        """members of the selected chat: [{'username', 'online': bool, 'is_me': bool (optional)}].
        Pass chat_id so a late reply for a chat that is no longer selected is ignored."""
        if chat_id is not None and chat_id != self._chat_id:
            return
        self._members = [dict(m) for m in members]
        self._refresh_members()

    def set_online_users(self, users):
        """everybody online: [{'username', 'is_me': bool (optional)}] (shown under ONLINE)."""
        self._online = [dict(u, online=True) for u in users]
        self._refresh_members()

    def set_messages(self, messages, first_unread_id=None, chat_id=None):
        """messages: [{'id', 'sender', 'text', 'time': datetime, 'own': bool (optional),
        'status': 'Sent' (optional, own messages)}]. A NEW marker goes above first_unread_id and the
        view opens there; otherwise it opens at the bottom. Pass chat_id so a late reply for a chat
        that is no longer selected is ignored."""
        if chat_id is not None and chat_id != self._chat_id:
            return
        self._messages = [dict(m) for m in messages]
        self._messages_chat = self._chat_id
        self._first_unread = first_unread_id
        has_new = first_unread_id is not None and any(m.get("id") == first_unread_id for m in self._messages)
        self._scroll_to_new = has_new
        self._stick_to_bottom = not has_new
        self._render_messages()
        QTimer.singleShot(0, self._after_messages_loaded)

    def append_message(self, message, chat_id=None):
        """A new message arrived (own or incoming) in the selected chat."""
        if (chat_id is not None and chat_id != self._chat_id) or self._pending:
            return
        message = dict(message)
        at_bottom = self._at_bottom()
        self._messages.append(message)
        self._add_message_row(message, self._previous_day(len(self._messages) - 1))
        own = bool(message.get("own", message.get("sender") == self._me and bool(self._me)))
        if at_bottom:
            self._stick_to_bottom = True
            self._maybe_mark_read(at_bottom=True)       # it is being read right now
        elif not own and self._chat_id is not None:
            chat = self._chat_data(self._chat_id) or {}
            self.set_chat_unread(self._chat_id, int(chat.get("unread", 0) or 0) + 1)

    def set_summary(self, text):
        self.summary_text.setPlainText(str(text))

    def set_chat_title(self, title):
        self.chat_title.setText(str(title))

    def open_chat(self, chat_id):
        """Select a chat in the directory as if it was clicked (e.g. the DM that was just created)."""
        for i in range(self.chat_list.count()):
            if (self.chat_list.item(i).data(Qt.UserRole) or {}).get("chat_id") == chat_id:
                self.chat_list.setCurrentRow(i)
                return

    # invitations ([Pending] chats)
    # ---- invitations ([Pending] chats)
    def accept_invite(self):
        self._answer_invite(True)

    def reject_invite(self):
        self._answer_invite(False)

    def _answer_invite(self, accepted):
        if not self._pending or self._invite_busy or self._chat_id is None:
            return
        self._invite_busy = True
        self.invite_error.setText("")
        _repolish(self.accept_btn if accepted else self.reject_btn, "status", "processing")
        (self.request_accept_invite if accepted else self.request_reject_invite)(self._chat_id)

    def invite_failed(self, chat_id, message):
        """The backend refused Accept / Reject: show why, allow another try."""
        if chat_id != self._chat_id or not self._pending:
            return
        self._invite_busy = False
        for b in (self.accept_btn, self.reject_btn):
            _repolish(b, "status", "pending")
        self.invite_error.setText(str(message))

    def resolve_invite(self, chat_id, accepted):
        """The backend processed the answer. Accepted: the chat becomes a normal one and is loaded.
        Rejected: it leaves the directory."""
        for i in range(self.chat_list.count()):
            item = self.chat_list.item(i)
            chat = dict(item.data(Qt.UserRole) or {})
            if chat.get("chat_id") != chat_id:
                continue
            was_current = chat_id == self._chat_id
            if accepted:
                chat["pending"], chat["unread"] = False, 0
                item.setData(Qt.UserRole, chat)
                self.chat_list.viewport().update()
                if was_current:
                    self._show_chat(chat)
                    self.select_chat(chat_id)
                return
            self.chat_list.blockSignals(True)
            self.chat_list.takeItem(i)
            if was_current and self.chat_list.count():
                self.chat_list.setCurrentRow(min(i, self.chat_list.count() - 1))
            self.chat_list.blockSignals(False)
            if was_current:
                if self.chat_list.count():
                    self._on_chat_item_changed(self.chat_list.currentItem(), None)
                else:
                    self._show_chat({})             # clears the invitation page too
                    self.chat_title.setText("")
            return

    def reset(self):
        """Blank page again (after logging out)."""
        self._gen += 1                              # replies still on their way are dropped
        self.session, self._my_id = None, None
        self._loading_chat, self._early = None, {}
        self._refreshing, self._refresh_again, self._after_refresh = False, False, []
        self._summary_chat, self._summary_seq = None, self._summary_seq + 1
        self._summary_running = None
        self._read_upto = {}
        self._sending = None
        self._notice_timer.stop()
        self.hint_label.setText(self._hint_text)
        self.hint_label.setToolTip("")
        self.generate_summary_btn.setEnabled(True)
        self.close_dialog()
        if self._menu is not None:
            self._menu.close()
        self._me = ""
        self._chat_id = None
        self._user_styles = {}
        self._members, self._online = [], []
        self._messages, self._messages_chat, self._first_unread = [], None, None
        self._scroll_to_new = False
        self._stick_to_bottom = True
        self._members_mode = MEMBERS
        self._pending = False
        self._invite_busy = False
        self.chat_stack.setCurrentIndex(0)
        self.add_people_btn.hide()
        self.chat_list.blockSignals(True)
        self.chat_list.clear()
        self.chat_list.blockSignals(False)
        self._clear_profile()
        self._clear_messages()
        self._refresh_members()
        self._sync_members_view()
        self.chat_title.setText("")
        self.summary_text.clear()
        self.msg_input.clear()

    # ------------------------------------------------------------------ internals
    def _sync_input_gap(self):
        """Blank strip above the chat box (messages are cut off at its top edge). It is as tall as
        the distance from the chat box's bottom edge to the frame: hint line + spacing + margin."""
        below = (self.hint_label.sizeHint().height() + self.entry_layout.spacing()
                 + ENTRY_MARGIN_BOTTOM)
        m = self.entry_layout.contentsMargins()
        if m.top() != below:
            self.entry_layout.setContentsMargins(m.left(), below, m.right(), m.bottom())

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_input_gap()                      # fonts are known now

    def input_gap(self):
        return self.entry_layout.contentsMargins().top()

    def _sync_members_view(self):
        online = self._members_mode == ONLINE
        self.members_tab.label.setText("ONLINE" if online else "MEMBERS")
        self.switch_member_btn.setIcon(make_icon("caret_up" if online else "caret", WHITE))
        tip = "Show members of this chat" if online else "Show online users"
        self.switch_member_btn.setToolTip(tip)
        self.switch_member_btn.setAccessibleName(tip)
        self._refresh_members()

    def _refresh_members(self):
        online_mode = self._members_mode == ONLINE
        source = self._online if online_mode else self._members
        self.members_list.clear()
        online = 0
        for m in source:
            row = dict(m)
            row.setdefault("is_me", row.get("username") == self._me)
            row["style"] = self.user_style(row.get("username", ""))
            online += 1 if row.get("online") else 0
            item = QListWidgetItem()
            item.setData(Qt.UserRole, row)
            self.members_list.addItem(item)
        if online_mode:
            self.members_count.setText(f"{len(source)} ONLINE")
        else:
            self.members_count.setText(f"{online}/{len(source)} ONLINE")

    def _show_chat(self, chat):
        chat_id = chat.get("chat_id")
        pending = bool(chat.get("pending"))
        changed = chat_id != self._chat_id or pending != self._pending
        self._chat_id = chat_id
        self._pending = pending
        self.chat_title.setText(("[DM] " if chat.get("is_dm") else "") + str(chat.get("name", "")))
        if pending:
            self.invite_text.setText(f"You've been invited to join the group {chat.get('name', '')}")
        self.add_people_btn.setVisible(False)   # groups only; invitations are off now (R10)
        self._sync_summary_button()                  # stays off while this chat's summary is made
        if changed:                                  # nothing of the previous chat may linger
            self.chat_stack.setCurrentIndex(1 if pending else 0)
            self._invite_busy = False
            self.invite_error.setText("")
            for b in (self.accept_btn, self.reject_btn):
                _repolish(b, "status", "pending")
            if pending:
                self.summary_text.clear()
            self._messages, self._messages_chat, self._first_unread = [], None, None
            self._scroll_to_new = False
            self._stick_to_bottom = True
            self._clear_messages()
            self._members = []
            self._members_mode = MEMBERS
            self._sync_members_view()

    def _on_chat_item_changed(self, current, previous):
        if current is None:
            return
        chat = current.data(Qt.UserRole) or {}
        self._show_chat(chat)
        if not chat.get("pending"):                 # an invitation has nothing to load
            self.select_chat(chat.get("chat_id"))

    def _clear_messages(self):
        self._new_marker = None
        while self.message_layout.count() > 1:          # keep the trailing stretch
            old = self.message_layout.takeAt(0).widget()
            if old is not None:
                old.setParent(None)                     # gone from the screen at once, freed later
                old.deleteLater()

    def _previous_day(self, index):
        for earlier in range(index - 1, -1, -1):
            dt = _as_datetime(self._messages[earlier].get("time"))
            if dt:
                return dt.date()
        return None

    def _add_message_row(self, msg, previous_day):
        dt = _as_datetime(msg.get("time"))
        stretch_at = self.message_layout.count() - 1
        if dt and dt.date() != previous_day:
            self.message_layout.insertWidget(stretch_at, DividerRow(format_day(dt)))
            stretch_at += 1
        if self._first_unread is not None and msg.get("id") == self._first_unread:
            self._new_marker = DividerRow("NEW")
            self.message_layout.insertWidget(stretch_at, self._new_marker)
            stretch_at += 1
        sender = str(msg.get("sender", ""))
        own = bool(msg.get("own", sender == self._me and bool(self._me)))
        fg, bg = self.user_style(self._me if own else sender)
        self.message_layout.insertWidget(stretch_at, MessageWidget(msg, own, fg, bg))

    def _render_messages(self, keep_scroll=False):
        bar = self.message_scroll.verticalScrollBar()
        old = bar.value()
        self._clear_messages()
        previous_day = None
        for msg in self._messages:
            self._add_message_row(msg, previous_day)
            dt = _as_datetime(msg.get("time"))
            previous_day = dt.date() if dt else previous_day
        if keep_scroll:
            self._stick_to_bottom = False
            QTimer.singleShot(0, lambda: bar.setValue(old))

    def _at_bottom(self):
        bar = self.message_scroll.verticalScrollBar()
        return bar.value() >= bar.maximum() - 2

    def _after_messages_loaded(self):
        """Layout is settled: open at the NEW marker if there is one, then see if everything is read."""
        QApplication.sendPostedEvents(None, QEvent.LayoutRequest)    # sizes first, then measure
        self.message_scroll.widget().layout().activate()
        if self._scroll_to_new:
            self._scroll_to_new = False
            marker = self._new_marker
            if marker is not None:
                self.message_scroll.verticalScrollBar().setValue(max(0, marker.y() - 8))
        self._maybe_mark_read()

    # Notifications are cleared once the user is at the bottom of the loaded chat.
    def _maybe_mark_read(self, at_bottom=None):
        """At the bottom of the loaded chat everything is read: its count goes to 0, and the server
        hears about the newest message once. That is decided by the message, not by the count, which
        can lag behind the server (a push that came while the chat loaded, a list from before a read)."""
        chat_id = self._chat_id
        if chat_id is None or self._pending or self._messages_chat != chat_id:
            return
        if not (self._at_bottom() if at_bottom is None else at_bottom):
            return
        chat = self._chat_data(chat_id)
        if chat and int(chat.get("unread", 0) or 0) > 0:
            self.set_chat_unread(chat_id, 0)
        newest = next((m for m in reversed(self._messages) if m.get("id")), None)
        if newest is None or self._read_upto.get(chat_id) == newest["id"]:
            return
        self._read_upto[chat_id] = newest["id"]
        if not newest.get("own"):                   # the server marks your own messages read itself
            self.request_mark_read(chat_id, newest["id"])

    def _on_scroll_range_changed(self, low, high):
        if self._stick_to_bottom:
            self.message_scroll.verticalScrollBar().setValue(high)

    def _on_scroll_value_changed(self, value):
        self._stick_to_bottom = self._at_bottom()
        if self._stick_to_bottom:
            self._maybe_mark_read()

    # preview only
    # ------------------------------------------------------------------ demo data (preview only)
    def load_demo_data(self):
        now = datetime.now()
        today = lambda h, m: now.replace(hour=h, minute=m, second=0, microsecond=0)
        self.set_user_style("Sainen420", WHITE, BLACK)
        self.set_user_style("lztech", BLACK, BLUE)
        self.set_user_style("GreatGodChal...", WHITE, RED)
        self.set_user_style("moss", BLUE, BLACK)
        self.set_profile("Sainen420")
        self.set_chats([
            {"chat_id": 1, "name": "RECONSTRUCTION 3, 2, 1", "unread": 0, "last_activity": today(11, 29)},
            {"chat_id": 2, "name": "Purgatory", "unread": 66, "last_activity": today(3, 33)},
            {"chat_id": 3, "name": "gng this group got...", "unread": 5, "last_activity": datetime(2026, 10, 25)},
            {"chat_id": 4, "name": "lztech", "unread": 0, "is_dm": True, "last_activity": datetime(2026, 10, 15)},
            {"chat_id": 5, "name": "GreatGodChal...", "unread": 0, "is_dm": True, "last_activity": datetime(2026, 5, 9)},
            {"chat_id": 6, "name": "Study Circle", "pending": True},
        ], selected_id=1)
        self.set_members([
            {"username": "Sainen420", "online": True},
            {"username": "lztech", "online": True},
            {"username": "GreatGodChal...", "online": True},
            {"username": "moss", "online": False},
        ])
        d = datetime(2026, 11, 2)
        self.set_messages([
            {"id": 1, "sender": "lztech", "time": d.replace(hour=11, minute=24),
             "text": "Starting fresh in here. What should we rebuild first?"},
            {"id": 2, "sender": "GreatGodChal...", "time": d.replace(hour=11, minute=25),
             "text": "The **welcome space**. One place for links and a short intro."},
            {"id": 3, "sender": "moss", "time": d.replace(hour=11, minute=26),
             "text": "Yes. Keep the old archive, but make the new rooms *easier* to find."},
            {"id": 4, "sender": "lztech", "time": d.replace(hour=11, minute=28),
             "text": "I'll sort the links. Can someone draft the __welcome note__?"},
            {"id": 5, "sender": "Sainen420", "own": True, "status": "Sent", "time": d.replace(hour=11, minute=29),
             "text": "I'm on it. I'll post a draft here before we move anything."},
        ], first_unread_id=3)
        self.set_summary("This conversation seems to be relating to setting up the group chat.\n"
                         "Lztech seems to be coordinating the setup of this group chat.")


# if this application is the main, then it's run in TEST mode
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    from styles import APP_STYLESHEET

    class DemoPage(ChatPage):
        """Preview only: pretends the backend accepts every pop-up after a moment."""
        def _ok(self, *_):
            QTimer.singleShot(600, lambda: self.finish_dialog(True))
        request_edit_profile = request_change_password = request_new_group = _ok
        request_invite = request_message = _ok

        def request_accept_invite(self, chat_id):
            QTimer.singleShot(600, lambda: self.resolve_invite(chat_id, True))

        def request_reject_invite(self, chat_id):
            QTimer.singleShot(600, lambda: self.resolve_invite(chat_id, False))

        def request_invitees(self, chat_id, query):
            people = ["lztech", "moss", "GreatGodChal..."]
            hit = [{"user_id": n, "username": n} for n in people if query.lower() in n.lower()]
            QTimer.singleShot(300, lambda: self.set_invitees(chat_id, query, hit))

        def request_user_groups(self, username):
            QTimer.singleShot(400, lambda: self.set_user_groups(username, [{"chat_id": 1, "name": "RECONSTRUCTION 3, 2, 1"}, {"chat_id": 2, "name": "Purgatory"}]))

        def request_all_groups(self):
            groups = [{"chat_id": 1, "name": "RECONSTRUCTION 3, 2, 1", "member_count": 4, "joined": True,
                       "members": [{"username": n} for n in ("Sainen420", "lztech", "GreatGodChal...", "moss")]},
                      {"chat_id": 6, "name": "Study Circle", "member_count": 2,
                       "members": [{"username": n} for n in ("lztech", "moss")]}]
            QTimer.singleShot(400, lambda: self.set_all_groups(groups))

        def request_join_group(self, chat_id):
            QTimer.singleShot(600, lambda: self.finish_dialog(True))

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    page = DemoPage()
    page.load_demo_data()
    page.logout_requested.connect(app.quit)
    page.resize(900, 640)
    page.show()
    sys.exit(app.exec())