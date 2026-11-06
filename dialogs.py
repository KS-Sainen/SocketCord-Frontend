"""Pop-up forms of the chat page.

Every form behaves like the login form:
  * pressing SAVE validates; a bad field gets a red border AND a short red message that sits
    on the same line, right after that field's label
  * a valid form turns the button into its 'processing' look and emits `submitted(values)`
  * the owner (ChatPage) reports the backend's answer with `finish(ok, message, field)`
"""
import re
from string import Template

from PySide6.QtCore import Qt, Signal, QSize, QPointF, QEvent
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QAbstractItemView, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget, QColorDialog, QStyle, QStyleOptionComboBox
)

# Palette tokens come from styles.py. Never write a hex colour in this file.
from styles import BLACK, WHITE, RED, BLUE, PALETTE

DIALOG_WIDTH = 440
USERNAME_MAX = 32
GROUP_NAME_MAX = 40
_HEX = re.compile(r'^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')


def normalize_hex(text):
    """'#abc', 'ABC', ' #AABBCC ' -> '#AABBCC'. None when it is not a hex colour."""
    m = _HEX.match(str(text).strip())
    if not m:
        return None
    digits = m.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return "#" + digits.upper()


def _set_prop(widget, name, value):
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def dropper_icon(color):
    """The droplet used on the colour picker button."""
    px = QPixmap(96, 96)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawLine(48, 10, 24, 46)
    p.drawLine(48, 10, 72, 46)
    p.drawEllipse(QPointF(48, 62), 26, 26)
    p.end()
    return QIcon(px)


# ---------------------------------------------------------------------------------------
# small widgets
# ---------------------------------------------------------------------------------------
class ErrorLabel(QLabel):
    """One-line red message after a field label. Long messages are cut with '...'
    (the full text stays in the tooltip) so they can never widen the dialog."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FieldError")
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

    def full_text(self):
        return self._full

    def setMessage(self, text):
        self._full = str(text)
        self._apply()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply()

    def _apply(self):
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(0, self.width()))
        QLabel.setText(self, shown)
        self.setToolTip(self._full if shown != self._full else "")


class ColorSwatch(QWidget):
    """White cell with a round sample of the colour."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = None
        self.setFixedWidth(64)

    def setColor(self, color):
        self._color = color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(WHITE))
        d = min(self.width(), self.height()) - 16
        p.setPen(QPen(QColor(BLACK), 2))
        p.setBrush(QColor(self._color) if self._color else Qt.NoBrush)
        p.drawEllipse(QPointF(self.width() / 2, self.height() / 2), d / 2, d / 2)


class ColorField(QFrame):
    """[ #171717 | dropper | round sample ] : type a hex code or open the colour picker."""
    changed = Signal()

    def __init__(self, initial, parent=None):
        super().__init__(parent)
        self.setObjectName("ColorRow")
        self.setProperty("status", "ok")
        self.setProperty("focused", False)
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)             # the black frame
        row.setSpacing(0)
        self.hex_edit = QLineEdit(normalize_hex(initial) or str(initial))
        self.hex_edit.setObjectName("HexInput")
        self.hex_edit.setMaxLength(9)
        self.hex_edit.installEventFilter(self)
        row.addWidget(self.hex_edit, 1)
        self.pick_btn = QToolButton()
        self.pick_btn.setObjectName("PickerButton")
        self.pick_btn.setIcon(dropper_icon(WHITE))
        self.pick_btn.setIconSize(QSize(22, 22))
        self.pick_btn.setFixedWidth(48)
        self.pick_btn.setToolTip("Pick a colour")
        self.pick_btn.setCursor(Qt.PointingHandCursor)
        row.addWidget(self.pick_btn)
        self.swatch = ColorSwatch()
        row.addWidget(self.swatch)
        self.hex_edit.textChanged.connect(self._sync)
        self.pick_btn.clicked.connect(self.pick)
        self._sync()

    def _sync(self, *_):
        self.swatch.setColor(self.value())
        self.changed.emit()

    def value(self):
        """'#RRGGBB' (upper case) or None when the text is not a hex colour."""
        return normalize_hex(self.hex_edit.text())

    def setText(self, text):
        self.hex_edit.setText(text)

    def pick(self):
        start = QColor(self.value() or BLACK)
        chosen = QColorDialog.getColor(start, self.window(), "Pick a colour",
                                       QColorDialog.DontUseNativeDialog)
        if chosen.isValid():
            self.hex_edit.setText(chosen.name().upper())

    def setFocus(self, *args):
        self.hex_edit.setFocus(*args)

    def eventFilter(self, obj, event):
        if obj is self.hex_edit and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            _set_prop(self, "focused", event.type() == QEvent.FocusIn)
        return super().eventFilter(obj, event)


class GroupComboBox(QComboBox):
    """Combo box whose drop-down cell is black with a white caret (QSS can't draw the arrow)."""
    def paintEvent(self, event):
        super().paintEvent(event)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        cell = self.style().subControlRect(QStyle.CC_ComboBox, opt, QStyle.SC_ComboBoxArrow, self)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = cell.center()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(WHITE))
        from PySide6.QtGui import QPolygonF
        p.drawPolygon(QPolygonF([QPointF(c.x() - 7, c.y() - 4), QPointF(c.x() + 7, c.y() - 4),
                                 QPointF(c.x(), c.y() + 5)]))


# ---------------------------------------------------------------------------------------
# styling
# ---------------------------------------------------------------------------------------
_DIALOG_QSS = Template("""
QDialog#FormDialog { background-color: $white; }
QFrame#DialogFrame { background-color: $white; border: 4px solid $black; }
QLabel { background-color: transparent; color: $black; font-size: 14pt; }
QLabel#DialogTitle { font-size: 20pt; font-weight: bold; text-decoration: underline; }
QLabel#FieldError { color: $red; font-size: 11pt; }
QLabel#DialogStatus { color: $red; font-size: 12pt; }

QLineEdit#DialogInput {
    background-color: $white; color: $black; border: 4px solid $black;
    padding: 6px 8px; font-size: 14pt;
    selection-background-color: $black; selection-color: $white;
}
QLineEdit#DialogInput:focus { border: 4px solid $blue; }
QLineEdit#DialogInput[status="error"] { border: 4px solid $red; }

QFrame#ColorRow { background-color: $black; border: none; }
QFrame#ColorRow[focused="true"] { background-color: $blue; }
QFrame#ColorRow[status="error"] { background-color: $red; }
QLineEdit#HexInput, QLineEdit#HexInput:focus {
    background-color: $white; color: $black; border: none; padding: 6px 8px; font-size: 14pt;
    selection-background-color: $black; selection-color: $white;
}
QToolButton#PickerButton { background-color: $black; border: none; }
QToolButton#PickerButton:pressed { background-color: $blue; }

QComboBox#DialogCombo {
    background-color: $white; color: $black; border: 4px solid $black;
    padding: 6px 8px; font-size: 14pt;
}
QComboBox#DialogCombo:focus { border: 4px solid $blue; }
QComboBox#DialogCombo[status="error"] { border: 4px solid $red; }
QComboBox#DialogCombo::drop-down {
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 34px; background-color: $black; border: none;
}
QComboBox#DialogCombo QAbstractItemView {
    background-color: $white; color: $black; border: 3px solid $black; outline: 0;
    selection-background-color: $black; selection-color: $white; font-size: 14pt;
}

QListWidget#GroupList {
    background-color: $white; color: $black; border: 4px solid $black; outline: 0; font-size: 14pt;
}
QListWidget#GroupList::item { padding: 6px 8px; }
QListWidget#GroupList::item:selected { background-color: $black; color: $white; }

QPushButton#DialogButton {
    background-color: $black; color: $white; border: 2px solid $black;
    padding: 10px; font-size: 17pt; letter-spacing: 1px;
}
QPushButton#DialogButton:pressed,
QPushButton#DialogButton[status="processing"] { background-color: $white; color: $black; }
""").substitute(PALETTE)


# ---------------------------------------------------------------------------------------
# base form
# ---------------------------------------------------------------------------------------
class FormDialog(QDialog):
    """Title, labelled fields, CANCEL / SAVE. Subclasses add fields and implement collect()."""
    submitted = Signal(dict)

    def __init__(self, title, parent=None, submit_text="SAVE"):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName("FormDialog")
        self.setModal(True)
        self.setStyleSheet(_DIALOG_QSS)
        self.setFixedWidth(DIALOG_WIDTH)
        self._rows = {}                  # key -> (field widget, ErrorLabel)
        self._busy = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("DialogFrame")
        outer.addWidget(frame)
        self._body = QVBoxLayout(frame)
        self._body.setContentsMargins(22, 18, 22, 22)
        self._body.setSpacing(0)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("DialogTitle")
        self._body.addWidget(self.title_label)
        self._body.addSpacing(12)

        self.status_label = QLabel("")
        self.status_label.setObjectName("DialogStatus")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        self._body.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(16)
        self.cancel_btn = QPushButton("CANCEL")
        self.submit_btn = QPushButton(submit_text)
        for b in (self.cancel_btn, self.submit_btn):
            b.setObjectName("DialogButton")
            b.setProperty("status", "pending")
            b.setCursor(Qt.PointingHandCursor)
            b.setAutoDefault(False)
            buttons.addWidget(b, 1)
        self.submit_btn.setDefault(True)
        self._body.addSpacing(6)
        self._body.addLayout(buttons)
        self.cancel_btn.clicked.connect(self.reject)
        self.submit_btn.clicked.connect(self.submit)

    # ------------------------------------------------------------------ building
    @staticmethod
    def line_edit(text="", password=False, read_only=False, placeholder=""):
        edit = QLineEdit(text)
        edit.setObjectName("DialogInput")
        edit.setProperty("status", "ok")
        if password:
            edit.setEchoMode(QLineEdit.Password)
        if placeholder:
            edit.setPlaceholderText(placeholder)
        if read_only:
            edit.setReadOnly(True)
            edit.setFocusPolicy(Qt.NoFocus)
        return edit

    def add_field(self, key, label_text, widget):
        """Label row (label + its error message right after it), then the field."""
        err = ErrorLabel()
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(QLabel(label_text))
        head.addWidget(err, 1)
        index = self._body.indexOf(self.status_label)        # before the status line
        holder = QVBoxLayout()
        holder.setSpacing(6)
        holder.addLayout(head)
        holder.addWidget(widget)
        self._body.insertLayout(index, holder)
        self._body.insertSpacing(index + 1, 14)
        widget.setProperty("status", "ok")
        self._rows[key] = (widget, err)
        return widget

    # ------------------------------------------------------------------ validation
    def collect(self):
        """-> (values dict, errors {key: message}). Subclasses override."""
        return {}, {}

    def clear_errors(self):
        for widget, err in self._rows.values():
            _set_prop(widget, "status", "ok")
            err.setMessage("")
        self.status_label.setText("")
        self.status_label.hide()

    def set_error(self, key, message):
        widget, err = self._rows[key]
        _set_prop(widget, "status", "error")
        err.setMessage(message)

    def error_text(self, key):
        return self._rows[key][1].full_text()

    def has_error(self, key):
        return self._rows[key][0].property("status") == "error"

    def submit(self):
        if self._busy:
            return                                  # a request is already on its way
        self.clear_errors()
        values, errors = self.collect()
        if errors:
            first = None
            for key, message in errors.items():
                self.set_error(key, message)
                first = first or key
            self._rows[first][0].setFocus()
            return
        self._busy = True
        _set_prop(self.submit_btn, "status", "processing")
        self.submitted.emit(values)

    def is_busy(self):
        return self._busy

    def finish(self, ok, message="", field=None):
        """The backend answered. ok -> close; otherwise show the message and allow another try."""
        self._busy = False
        _set_prop(self.submit_btn, "status", "pending")
        if ok:
            self.accept()
            return
        if field in self._rows:
            self.set_error(field, message)
        else:
            self.status_label.setText(message)
            self.status_label.show()


# ---------------------------------------------------------------------------------------
# the forms
# ---------------------------------------------------------------------------------------
class EditProfileDialog(FormDialog):
    def __init__(self, username, text_color, background, parent=None):
        super().__init__("Edit profile", parent)
        self.username_input = self.add_field("username", "Username", self.line_edit(username))
        self.text_color = self.add_field("text_color", "Personal Text Color", ColorField(text_color))
        self.background = self.add_field("background", "Personal Text Background", ColorField(background))

    def collect(self):
        errors = {}
        name = self.username_input.text().strip()
        if not name:
            errors["username"] = "Required"
        elif len(name) > USERNAME_MAX:
            errors["username"] = f"Max {USERNAME_MAX} characters"
        fg, bg = self.text_color.value(), self.background.value()
        if fg is None:
            errors["text_color"] = "Invalid hex colour"
        if bg is None:
            errors["background"] = "Invalid hex colour"
        return {"username": name, "text_color": fg, "background": bg}, errors


class ChangePasswordDialog(FormDialog):
    def __init__(self, parent=None):
        super().__init__("Change password", parent)
        self.new_input = self.add_field("new_password", "New password", self.line_edit(password=True))
        self.confirm_input = self.add_field("confirm_password", "Confirm new password",
                                            self.line_edit(password=True))

    def collect(self):
        errors = {}
        new, confirm = self.new_input.text(), self.confirm_input.text()
        if not new:
            errors["new_password"] = "Required"
        if not confirm:
            errors["confirm_password"] = "Required"
        elif new != confirm:
            errors["confirm_password"] = "Doesn't match"
        return {"new_password": new}, errors


class NewGroupDialog(FormDialog):
    def __init__(self, parent=None):
        super().__init__("New group", parent, submit_text="CREATE")
        self.name_input = self.add_field("name", "Group name", self.line_edit())

    def collect(self):
        errors = {}
        name = self.name_input.text().strip()
        if not name:
            errors["name"] = "Required"
        elif len(name) > GROUP_NAME_MAX:
            errors["name"] = f"Max {GROUP_NAME_MAX} characters"
        return {"name": name}, errors


class InviteDialog(FormDialog):
    """groups: [{'chat_id', 'name'}] the user may be invited to."""
    def __init__(self, username, groups, parent=None):
        super().__init__("Invite to group", parent, submit_text="INVITE")
        self.username = username
        self.add_field("username", "User", self.line_edit(username, read_only=True))
        self.group_combo = GroupComboBox()
        self.group_combo.setObjectName("DialogCombo")
        for g in groups:
            self.group_combo.addItem(str(g.get("name", "")), g.get("chat_id"))
        self.add_field("group", "Group", self.group_combo)

    def collect(self):
        if self.group_combo.count() == 0:
            return {}, {"group": "No group available"}
        return {"username": self.username, "chat_id": self.group_combo.currentData()}, {}


class MessageDialog(FormDialog):
    GREETING = "Hello!"

    def __init__(self, username, parent=None):
        super().__init__("Message", parent, submit_text="SEND")
        self.username = username
        self.add_field("username", "To", self.line_edit(username, read_only=True))
        self.greeting_input = self.add_field("greeting", "Greeting", self.line_edit(self.GREETING))
        self.greeting_input.selectAll()

    def collect(self):
        text = self.greeting_input.text().strip()
        if not text:
            return {}, {"greeting": "Required"}
        return {"username": self.username, "greeting": text}, {}


class GroupsDialog(FormDialog):
    """'See Groups': every group one user is in. Opens with 'Loading...', then set_groups()."""
    def __init__(self, username, parent=None):
        super().__init__(f"Groups", parent, submit_text="CLOSE")
        self.username = username
        self.cancel_btn.hide()
        self.submit_btn.clicked.disconnect(self.submit)     # nothing to validate or send
        self.submit_btn.clicked.connect(self.accept)
        self.group_list = QListWidget()
        self.group_list.setObjectName("GroupList")
        self.group_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.group_list.setFocusPolicy(Qt.NoFocus)
        self.group_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.group_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.group_list.setFixedHeight(210)
        self.add_field("groups", f"{username} is in", self.group_list)
        self._fill(["Loading..."])

    def _fill(self, names):
        self.group_list.clear()
        for name in names:
            item = QListWidgetItem(str(name))
            item.setToolTip(str(name))
            self.group_list.addItem(item)

    def set_groups(self, groups):
        """groups: [{'chat_id', 'name'}] (plain names work too)."""
        names = [g.get("name", "") if isinstance(g, dict) else g for g in groups]
        self._fill(names or ["Not in any group"])

    def finish(self, ok, message="", field=None):
        super().finish(ok, message, field or "groups")      # a failure shows after the label

    def shown_groups(self):
        return [self.group_list.item(i).text() for i in range(self.group_list.count())]