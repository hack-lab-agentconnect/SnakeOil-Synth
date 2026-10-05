import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .bridge import Bridge
from .main_window import MainWindow
from .style import STYLE


def run_gui(engine, registry, router, store, midi_ports, on_exit=None):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyleSheet(STYLE)
    bridge = Bridge(registry, router)
    window = MainWindow(engine, registry, router, store, midi_ports, bridge)
    window.show()
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    pump = QTimer()
    pump.timeout.connect(lambda: None)
    pump.start(200)
    try:
        return app.exec()
    finally:
        if on_exit:
            on_exit()
