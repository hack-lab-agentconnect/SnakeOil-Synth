import sys
import time
import traceback

import mido

from .bindings import default_profile
from .midi_router import MidiRouter
from .params import build_registry


REALTIME = frozenset(("clock", "start", "stop", "continue"))


class MidiInput:
    def __init__(self, engine, ports=None, channel=None, router=None):
        self.engine = engine
        self.port_names = list(ports) if ports else None
        self.channel = channel  # 1-16, None = all
        self.ports = []
        if router is None:
            router = MidiRouter(build_registry(engine), default_profile())
        self.router = router
        self.registry = router.registry

    @staticmethod
    def available_ports():
        return mido.get_input_names()

    def start(self):
        names = self.port_names
        if not names:
            names = mido.get_input_names()
        if not names:
            raise RuntimeError("no MIDI input devices found")
        for name in names:
            self.ports.append(mido.open_input(name, callback=self._on_message))
        return [p.name for p in self.ports]

    def stop(self):
        for p in self.ports:
            try:
                p.close()
            except Exception:
                pass
        self.ports = []

    def _accepts(self, msg):
        if self.channel is None:
            return True
        channel = getattr(msg, "channel", None)
        return channel is not None and channel + 1 == self.channel

    def _standard_cc(self, control, value):
        if control == 64:
            self.engine.set_sustain(value >= 64)
        elif control == 120:
            self.engine.panic()
        elif control == 121:
            self.engine.reset_controllers()
        elif control == 123:
            self.engine.all_notes_off()

    def _on_realtime(self, kind):
        tempo = self.engine.tempo
        if kind == "clock":
            tempo.on_clock(time.perf_counter())
        elif kind == "start":
            tempo.on_start()
        elif kind == "stop":
            tempo.on_stop()
        else:
            tempo.on_continue()

    def _on_message(self, msg):
        kind = msg.type
        if kind in REALTIME:
            self._on_realtime(kind)
            return
        if not self._accepts(msg):
            return
        try:
            if msg.type == "note_on" and msg.velocity > 0:
                if not self.router.handle_note(msg.channel, msg.note, msg.velocity, True):
                    self.engine.note_on(msg.note, msg.velocity)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                self.router.handle_note(msg.channel, msg.note, 0, False)
                self.engine.note_off(msg.note)
            elif msg.type == "control_change":
                if not self.router.handle_cc(msg.channel, msg.control, msg.value):
                    self._standard_cc(msg.control, msg.value)
            elif msg.type == "aftertouch":
                self.router.handle_pressure(msg.channel, msg.value)
            elif msg.type == "pitchwheel":
                self.engine.set_pitch_bend(msg.pitch / 8192.0)
        except Exception:
            traceback.print_exc(file=sys.stderr)
