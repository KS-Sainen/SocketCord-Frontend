APP_STYLESHEET = """
/* Global Window / Widget Base */
QWidget {
    background-color: #f2f2f2;
    color: #171717;
    font-family: 'Source Sans Pro';
    font-size: 13pt;
}

/* Input Fields */
QLineEdit {
    background-color: #f2f2f2;
    color: #171717;
    border: 2px solid #171717;
    padding: 6px;
    selection-background-color: #171717;
    selection-color: #f2f2f2;
}

QLineEdit:focus {
    border: #0088ff;
}

/* Primary Buttons (SIGN UP, LOG IN, SEND) */
QPushButton {
    background-color: #171717;
    color: #f2f2f2;
    border: 2px solid #171717;
    padding: 10px;
    font-weight: normal;
    letter-spacing: 1px;
}

QPushButton:pressed {
    background-color: #f2f2f2;
    color: #171717;
}

/* Panels and Frames */
QFrame#PanelFrame {
    background-color: #f2f2f2;
    border: 4px solid #171717;
}

/* Labels */
QLabel {
    color: #171717;
}

/* List Widgets (Directory, Chat History, Members) */
QListWidget {
    background-color: #f2f2f2;
    border: 4px solid #171717;
    color: #171717;
}
"""