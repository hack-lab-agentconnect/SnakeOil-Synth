from PySide6.QtCore import QObject, Signal


class Bridge(QObject):
    """Turns registry/router callbacks (fired on the MIDI thread) into Qt signals.

    Qt queues a signal emitted from a non-GUI thread onto the receiver's thread.
    """

    param_changed = Signal(str)
    learned = Signal(str, str)
    message = Signal(str)

    def __init__(self, registry, router):
        super().__init__()
        registry.add_listener(self.param_changed.emit)
        router.on_learned = lambda pid, source: self.learned.emit(pid, source.label())
        router.on_message = self.message.emit
