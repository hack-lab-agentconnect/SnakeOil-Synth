import threading

from .bindings import CC, NOTE, Source
from .params import TOGGLE


class MidiRouter:
    """Maps incoming CC/note messages to registry params via the active profile.

    Callbacks (all optional) run on the calling MIDI thread:
      on_learned(param_id, source), on_message(text), on_profile_changed(profile)
    """

    def __init__(self, registry, profile):
        self.registry = registry
        self._profile = profile
        self._armed = None
        self._lock = threading.RLock()
        self.on_learned = None
        self.on_message = None
        self.on_profile_changed = None

    @property
    def profile(self):
        return self._profile

    @property
    def armed(self):
        return self._armed

    def set_profile(self, profile):
        with self._lock:
            self._profile = profile
            self._armed = None
            self.registry.reset_pressed()

    def arm(self, param_id):
        if param_id not in self.registry:
            raise KeyError(param_id)
        with self._lock:
            self._armed = param_id

    def disarm(self):
        with self._lock:
            self._armed = None

    def clear_binding(self, param_id):
        with self._lock:
            if self._profile.clear(param_id):
                self._changed()

    def handle_cc(self, channel, control, value):
        """channel is mido-style 0-15. Returns True if the message was consumed."""
        ch = channel + 1
        self._message("CC %d ch%d = %d" % (control, ch, value))
        with self._lock:
            if self._armed is not None:
                self._learn(Source(CC, control, ch))
                return True
            pid = self._profile.param_for(CC, ch, control)
            if pid is None or pid not in self.registry:
                return False
            self.registry.apply_midi(pid, value)
            return True

    def handle_note(self, channel, note, velocity, on):
        """channel is mido-style 0-15. Returns True if the note was consumed."""
        ch = channel + 1
        if on:
            self._message("Note %d ch%d" % (note, ch))
        with self._lock:
            if self._armed is not None and on:
                if self.registry[self._armed].kind == TOGGLE:
                    self._learn(Source(NOTE, note, ch))
                    return True
                return False
            pid = self._profile.param_for(NOTE, ch, note)
            if pid is None or pid not in self.registry:
                return False
            self.registry.apply_midi(pid, 127 if on else 0)
            return True

    def _learn(self, source):
        pid, self._armed = self._armed, None
        self._profile.bind(source, pid)
        self._changed()
        if self.on_learned:
            self.on_learned(pid, source)

    def _changed(self):
        if self.on_profile_changed:
            try:
                self.on_profile_changed(self._profile)
            except Exception as exc:
                self._message("Could not save profile: %s" % exc)

    def _message(self, text):
        if self.on_message:
            self.on_message(text)
