import sys

from PySide6.QtWidgets import QApplication

from .bridge import Bridge
from .main_window import MainWindow
from .style import STYLE


def run_gui(engine, registry, router, store, midi_ports):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyleSheet(STYLE)
    bridge = Bridge(registry, router)
    window = MainWindow(engine, registry, router, store, midi_ports, bridge)
    window.show()
    return app.exec()
