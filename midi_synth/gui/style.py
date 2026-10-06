STYLE = """
QWidget { background: #1b1e25; color: #dfe3ec; font-size: 12px; }
QMainWindow, QStatusBar { background: #1b1e25; }
QToolBar { background: #232733; border: 0; padding: 2px; spacing: 4px; }
QGroupBox { border: 1px solid #343a4a; border-radius: 6px; margin-top: 12px; padding-top: 4px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #8f98ad; }
QFrame#control { border: 1px solid transparent; border-radius: 6px; }
QFrame#control[learning="true"] { border: 1px solid #ffb74d; background: #2a2620; }
QLabel#badge { color: #ffb74d; font-size: 10px; }
QLabel[level="warn"] { color: #ffb74d; }
QLabel[level="bad"] { color: #ef5350; }
QPushButton, QComboBox { background: #2c3242; border: 1px solid #3d445a; border-radius: 4px; padding: 3px 8px; }
QPushButton:hover, QComboBox:hover { background: #343b50; }
QPushButton:checked { background: #1e88e5; border-color: #42a5f5; }
QPushButton:disabled { color: #666c7c; }
QComboBox QAbstractItemView { background: #2c3242; selection-background-color: #1e88e5; }
"""
