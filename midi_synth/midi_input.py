import mido

from .config import WAVEFORMS, MODES, SEMITONE_MIN, SEMITONE_MAX, CENTS_MIN, CENTS_MAX


def _waveform_from_cc(value):
    idx = min(int(value) // 32, len(WAVEFORMS) - 1)
    return WAVEFORMS[idx]


def _mode_from_cc(value):
    idx = min(int(value) * len(MODES) // 128, len(MODES) - 1)
    return MODES[idx]


class MidiInput:
    def __init__(self, engine, ports=None, channel=None):
        self.engine = engine
        self.port_names = list(ports) if ports else None
        self.channel = channel
        self.ports = []
        self._toggle_state = {}
        self.cc_map = {
            1: self._cc_fm,
            7: self._cc_volume,
            20: lambda v: self._cc_toggle("chorus", v),
            21: lambda v: self._cc_toggle("delay", v),
            22: lambda v: self._cc_toggle("reverb", v),
            23: lambda v: self._cc_toggle("bitcrush", v),
            24: lambda v: self._cc_wave(1, v),
            25: lambda v: self._cc_wave(2, v),
            26: self._cc_tune2,
            27: self._cc_cents2,
            28: lambda v: self.engine.set_osc_level(2, v / 127.0),
            29: lambda v: self.engine.set_osc_level(1, v / 127.0),
            30: lambda v: self.engine.set_mod_mode(_mode_from_cc(v)),
        }

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
        return self.channel is None or getattr(msg, "channel", None) == self.channel

    def _on_message(self, msg):
        if not self._accepts(msg):
            return
        try:
            if msg.type == "note_on" and msg.velocity > 0:
                self.engine.note_on(msg.note, msg.velocity)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                self.engine.note_off(msg.note)
            elif msg.type == "control_change":
                handler = self.cc_map.get(msg.control)
                if handler:
                    handler(msg.value)
            elif msg.type == "pitchwheel":
                self.engine.set_pitch_bend(msg.pitch / 8192.0)
            elif msg.type == "program_change":
                self.engine.set_osc1_waveform(_waveform_from_cc(msg.program * 2))
        except Exception:
            pass

    def _cc_toggle(self, name, value):
        pressed = value >= 64
        was = self._toggle_state.get(name, False)
        if pressed and not was:
            self.engine.toggle_effect(name)
        self._toggle_state[name] = pressed

    def _cc_wave(self, osc, value):
        if osc == 1:
            self.engine.set_osc1_waveform(_waveform_from_cc(value))
        else:
            self.engine.set_osc2_waveform(_waveform_from_cc(value))

    def _cc_fm(self, value):
        self.engine.set_fm_depth(value / 127.0)

    def _cc_volume(self, value):
        self.engine.set_master_gain(value / 127.0 * 1.2)

    def _cc_tune2(self, value):
        semis = SEMITONE_MIN + (SEMITONE_MAX - SEMITONE_MIN) * (value / 127.0)
        self.engine.set_detune2(semis)

    def _cc_cents2(self, value):
        cents = CENTS_MIN + (CENTS_MAX - CENTS_MIN) * (value / 127.0)
        self.engine.set_detune2(self.engine.params["detune2_semitones"], cents)
