from string import Template

BLACK = "#171717"
WHITE = "#f2f2f2"
RED = "#ff383c"
BLUE = "#0088ff"
 
PALETTE = {"black": BLACK, "white": WHITE, "red": RED, "blue": BLUE}
 
_QSS = Template("""
/* Global Window / Widget Base */
QWidget {
    background-color: $white;
    color: $black;
    font-family: 'Source Sans Pro';
    font-size: 13pt;
}
 
/* Input Fields */
QLineEdit {
    background-color: $white;
    color: $black;
    border: 2px solid $black;
    padding: 6px;
    selection-background-color: $black;
    selection-color: $white;
}
 
QLineEdit[status='error']{
    border: 2px solid $red;
}

QLineEdit:focus {
    border: 2px solid $blue;
}
 
/* Primary Buttons (SIGN UP, LOG IN, SEND) */
QPushButton {
    background-color: $black;
    color: $white;
    border: 2px solid $black;
    padding: 10px;
    font-weight: normal;
    letter-spacing: 1px;
}
 
QPushButton[status="processing"] {
    background-color: $white;
    color: $black;
}

QPushButton:pressed {
    background-color: $white;
    color: $black;
}
 
/* Panels and Frames */
QFrame#PanelFrame {
    background-color: $white;
    border: 4px solid $black;
}
 
/* Labels */
QLabel {
    color: $black;
}
 
/* List Widgets (Directory, Chat History, Members) */
QListWidget {
    background-color: $white;
    border: 4px solid $black;
    color: $black;
}
 
/* ---- Login / Sign-up page ------------------------------------------------ */
 
/* Text inside the card is larger than the application default */
QFrame#PanelFrame QLabel,
QFrame#PanelFrame QLineEdit {
    font-size: 16pt;
}
 
QFrame#PanelFrame QPushButton {
    font-size: 17pt;
}
 
/* "WELCOME" tab sitting on the top-left corner of the card */
QLabel#WelcomeTag {
    background-color: $black;
    color: $white;
    font-size: 17pt;
    font-style: italic;
    text-decoration: underline;
    padding: 0px 12px;
}
 
/* Status line below the card: red by default (failure), blue on success */
QLabel#StatusLabel {
    color: $red;
    font-size: 14pt;
}
 
QLabel#StatusLabel[state="ok"] {
    color: $blue;
}
""")
 
APP_STYLESHEET = _QSS.substitute(PALETTE)