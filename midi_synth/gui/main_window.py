from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QGroupBox, QInputDialog, QLabel,
    QMainWindow, QMessageBox, QPushButton, QToolBar, QWidget,
)

from ..bindings import DEFAULT_NAME
from ..patches import INIT_NAME, PatchError, apply as apply_patch, capture
from ..profiles import ProfileError
from .controls import ParamControl

GROUP_POSITIONS = {
    "Oscillator 1": (0, 0, 1, 1),
    "Oscillator 2": (0, 1, 1, 1),
    "Modulation": (0, 2, 1, 1),
    "Effects": (1, 0, 1, 1),
    "Filter": (1, 1, 1, 1),
    "Master": (1, 2, 1, 1),
    "Amp Envelope": (2, 0, 1, 1),
    "Filter Env": (2, 1, 1, 1),
    "LFO": (2, 2, 1, 1),
    "Glide": (3, 0, 1, 1),
    "Unison": (3, 1, 1, 1),
}


class MainWindow(QMainWindow):
    def __init__(self, engine, registry, router, store, midi_ports, bridge,
                 patch_store=None, patch_defaults=None):
        super().__init__()
        self.setWindowTitle("MIDI Synth")
        self.engine = engine
        self.registry = registry
        self.router = router
        self.store = store
        self.controls = {}
        self.btn = {}
        self.patch_store = patch_store
        self.patch_defaults = patch_defaults if patch_defaults is not None else capture(registry)
        self.patch_box = None
        self.patch_btn = {}
        self.patch_name = None
        self.patch_modified = False
        self._applying_patch = False

        self._build_toolbar()
        if patch_store is not None:
            self._build_patch_bar()
        self._build_body()
        self._build_footer(midi_ports)

        bridge.param_changed.connect(self._on_param_changed)
        bridge.learned.connect(self._on_learned)
        bridge.message.connect(self._on_message)

        self._reload_profiles(router.profile.name)
        self._refresh_badges()
        for warning in store.warnings:
            self.statusBar().showMessage(warning, 8000)
        if patch_store is not None:
            self._reload_patches(patch_store.last_used() or INIT_NAME)

    # ---- construction -------------------------------------------------

    def _build_toolbar(self):
        bar = QToolBar("Profiles")
        bar.setMovable(False)
        self.addToolBar(bar)
        bar.addWidget(QLabel("Profile: "))
        self.profile_box = QComboBox()
        self.profile_box.setMinimumWidth(160)
        self.profile_box.textActivated.connect(self._switch)
        bar.addWidget(self.profile_box)
        for key, text, slot in (
            ("new", "New", self._new_profile),
            ("duplicate", "Duplicate", self._duplicate_profile),
            ("rename", "Rename", self._rename_profile),
            ("delete", "Delete", self._delete_profile),
            ("reset", "Reset", self._reset_default),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, s=slot: s())
            bar.addWidget(button)
            self.btn[key] = button
        bar.addSeparator()
        self.learn_btn = QPushButton("MIDI Learn")
        self.learn_btn.setCheckable(True)
        self.learn_btn.toggled.connect(self._on_learn_mode)
        bar.addWidget(self.learn_btn)

    def _build_patch_bar(self):
        self.addToolBarBreak()
        bar = QToolBar("Patches")
        bar.setMovable(False)
        self.addToolBar(bar)
        bar.addWidget(QLabel("Patch: "))
        self.patch_box = QComboBox()
        self.patch_box.setMinimumWidth(160)
        self.patch_box.activated.connect(self._on_patch_chosen)
        bar.addWidget(self.patch_box)
        for key, text, slot in (
            ("save", "Save", self._save_patch),
            ("save_as", "Save As…", self._save_patch_as),
            ("rename", "Rename", self._rename_patch),
            ("delete", "Delete", self._delete_patch),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, s=slot: s())
            bar.addWidget(button)
            self.patch_btn[key] = button

    def _build_body(self):
        groups = {}
        columns = {}
        for param in self.registry:
            box = groups.get(param.group)
            if box is None:
                box = QGroupBox(param.group)
                box.setLayout(QGridLayout())
                groups[param.group] = box
            control = ParamControl(self.registry, param)
            control.learnRequested.connect(self._on_learn_requested)
            control.clearRequested.connect(self._on_clear_requested)
            cells = columns.setdefault(param.group, {})
            if param.under:
                row, col = cells[param.under]
                row += 1
            else:
                row, col = 0, sum(1 for r, _ in cells.values() if r == 0)
            cells[param.id] = (row, col)
            box.layout().addWidget(control, row, col)
            self.controls[param.id] = control
        grid = QGridLayout()
        for index, (name, box) in enumerate(groups.items()):
            grid.addWidget(box, *GROUP_POSITIONS.get(name, (2, index, 1, 1)))
        body = QWidget()
        body.setLayout(grid)
        self.setCentralWidget(body)

    def _build_footer(self, midi_ports):
        bar = self.statusBar()
        self.port_label = QLabel("MIDI: " + (", ".join(midi_ports) or "none"))
        self.msg_label = QLabel("Last MIDI: –")
        self.voice_label = QLabel("Voices: 0")
        for label in (self.port_label, self.msg_label, self.voice_label):
            bar.addPermanentWidget(label)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(250)

    # ---- profiles -----------------------------------------------------

    def _reload_profiles(self, select):
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        self.profile_box.addItems(self.store.names())
        self.profile_box.setCurrentText(select)
        self.profile_box.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self):
        is_default = self.profile_box.currentText().lower() == DEFAULT_NAME.lower()
        self.btn["rename"].setEnabled(not is_default)
        self.btn["delete"].setEnabled(not is_default)
        self.btn["reset"].setEnabled(is_default)

    def _switch(self, name):
        try:
            profile = self.store.load(name)
        except ProfileError as exc:
            self.statusBar().showMessage(str(exc), 6000)
            self._reload_profiles(self.router.profile.name)
            return
        self.router.set_profile(profile)
        try:
            self.store.set_active(profile.name)
        except OSError as exc:
            self.statusBar().showMessage(str(exc), 6000)
        self._clear_learning_state()
        self._reload_profiles(profile.name)
        self._refresh_badges()

    def _ask_name(self, title, default=""):
        text, ok = QInputDialog.getText(self, title, "Profile name:", text=default)
        return text.strip() if ok else None

    def _run_store_action(self, action):
        try:
            return action()
        except (ProfileError, OSError) as exc:
            QMessageBox.warning(self, "Profile", str(exc))
            return None

    def _new_profile(self):
        name = self._ask_name("New profile")
        if name and self._run_store_action(lambda: self.store.create(name)):
            self._switch(name)

    def _duplicate_profile(self):
        current = self.profile_box.currentText()
        name = self._ask_name("Duplicate profile", current + " copy")
        if name and self._run_store_action(lambda: self.store.duplicate(current, name)):
            self._switch(name)

    def _rename_profile(self):
        current = self.profile_box.currentText()
        name = self._ask_name("Rename profile", current)
        if not name:
            return
        self.router.disarm()
        if self._run_store_action(lambda: self.store.rename(current, name) or True):
            self._switch(name)

    def _delete_profile(self):
        current = self.profile_box.currentText()
        answer = QMessageBox.question(self, "Delete profile", "Delete profile '%s'?" % current)
        if answer == QMessageBox.Yes:
            self._switch(DEFAULT_NAME)
            self._run_store_action(lambda: self.store.delete(current))

    def _reset_default(self):
        answer = QMessageBox.question(
            self, "Reset Default", "Restore the Default profile to factory bindings?")
        if answer == QMessageBox.Yes:
            if self._run_store_action(lambda: self.store.reset_default() or True):
                self._switch(DEFAULT_NAME)

    # ---- patches ------------------------------------------------------

    def _patch_is_init(self):
        return (self.patch_name or "").lower() == INIT_NAME.lower()

    def _reload_patches(self, select):
        self.patch_name = select
        self.patch_modified = False
        self.patch_box.blockSignals(True)
        self.patch_box.clear()
        for name in self.patch_store.names():
            self.patch_box.addItem(name, name)
        index = self.patch_box.findData(select, Qt.UserRole, Qt.MatchFixedString)
        if index >= 0:
            self.patch_box.setCurrentIndex(index)
        self.patch_box.blockSignals(False)
        self._update_patch_ui()

    def _update_patch_ui(self):
        index = self.patch_box.currentIndex()
        if index >= 0:
            name = self.patch_box.itemData(index)
            self.patch_box.setItemText(index, name + ("*" if self.patch_modified else ""))
        is_init = self._patch_is_init()
        self.patch_btn["save"].setEnabled(not is_init)
        self.patch_btn["save"].setToolTip(
            "Init is read-only; use Save As… to keep this sound" if is_init
            else "Overwrite the current patch")
        self.patch_btn["rename"].setEnabled(not is_init)
        self.patch_btn["delete"].setEnabled(not is_init)

    def _on_patch_chosen(self, index):
        self._load_patch(self.patch_box.itemData(index))

    def _load_patch(self, name):
        try:
            values = self.patch_store.load(name)
        except PatchError as exc:
            self.statusBar().showMessage(str(exc), 8000)
            self._reload_patches(self.patch_name or INIT_NAME)
            return
        self._applying_patch = True
        try:
            warnings = apply_patch(self.registry, values, self.patch_defaults)
        finally:
            self._applying_patch = False
        try:
            self.patch_store.set_last_used(name)
        except OSError as exc:
            self.statusBar().showMessage(str(exc), 8000)
        self._reload_patches(name)
        if warnings:
            self.statusBar().showMessage("; ".join(warnings), 10000)
        else:
            self.statusBar().showMessage("Loaded patch %s" % name, 3000)

    def _ask_patch_name(self, title, default=""):
        text, ok = QInputDialog.getText(self, title, "Patch name:", text=default)
        return text.strip() if ok else None

    def _store_patch(self, name):
        try:
            self.patch_store.save(name, capture(self.registry))
            self.patch_store.set_last_used(name)
        except (PatchError, OSError) as exc:
            QMessageBox.warning(self, "Patch", str(exc))
            return
        self._reload_patches(name)
        self.statusBar().showMessage("Saved patch %s" % name, 3000)

    def _save_patch(self):
        if not self._patch_is_init():
            self._store_patch(self.patch_name)

    def _save_patch_as(self):
        name = self._ask_patch_name(
            "Save patch as", "" if self._patch_is_init() else self.patch_name)
        if not name:
            return
        if name.lower() == INIT_NAME.lower():
            QMessageBox.warning(self, "Patch", "The Init patch is read-only")
            return
        exists = name.lower() in (n.lower() for n in self.patch_store.names())
        if exists and name.lower() != (self.patch_name or "").lower():
            answer = QMessageBox.question(self, "Save patch", "Overwrite patch '%s'?" % name)
            if answer != QMessageBox.Yes:
                return
        self._store_patch(name)

    def _rename_patch(self):
        current = self.patch_name
        name = self._ask_patch_name("Rename patch", current)
        if not name:
            return
        try:
            self.patch_store.rename(current, name)
        except (PatchError, OSError) as exc:
            QMessageBox.warning(self, "Patch", str(exc))
            return
        modified = self.patch_modified
        self._reload_patches(name)
        self.patch_modified = modified
        self._update_patch_ui()

    def _delete_patch(self):
        current = self.patch_name
        answer = QMessageBox.question(self, "Delete patch", "Delete patch '%s'?" % current)
        if answer != QMessageBox.Yes:
            return
        try:
            self.patch_store.delete(current)
        except (PatchError, OSError) as exc:
            QMessageBox.warning(self, "Patch", str(exc))
            return
        self._load_patch(INIT_NAME)

    # ---- learn --------------------------------------------------------

    def _on_learn_mode(self, checked):
        for control in self.controls.values():
            control.set_learn_mode(checked)
        if checked:
            self.statusBar().showMessage("MIDI Learn: click a control, then move a MIDI control", 6000)
        else:
            self._cancel_learn()

    def _on_learn_requested(self, param_id):
        self.router.arm(param_id)
        for pid, control in self.controls.items():
            control.set_learning(pid == param_id)
        self.statusBar().showMessage("Move a control on your MIDI device… (Esc cancels)")

    def _on_clear_requested(self, param_id):
        self.router.clear_binding(param_id)
        self._refresh_badges()

    def _on_learned(self, param_id, label):
        self._clear_learning_state()
        self._refresh_badges()
        self.statusBar().showMessage(
            "Bound %s to %s" % (label, self.registry[param_id].label), 5000)

    def _clear_learning_state(self):
        for control in self.controls.values():
            control.set_learning(False)

    def _cancel_learn(self):
        self.router.disarm()
        self._clear_learning_state()
        self.statusBar().showMessage("Learn cancelled", 3000)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.router.armed is not None:
            self._cancel_learn()
            return
        super().keyPressEvent(event)

    # ---- sync ---------------------------------------------------------

    def _refresh_badges(self):
        profile = self.router.profile
        for pid, control in self.controls.items():
            source = profile.source_for(pid)
            control.set_binding(source.label() if source else None)

    def _on_param_changed(self, param_id):
        control = self.controls.get(param_id)
        if control is not None:
            control.refresh()
        if (self.patch_box is not None and not self._applying_patch
                and not self.patch_modified and param_id in self.patch_defaults):
            self.patch_modified = True
            self._update_patch_ui()

    def _on_message(self, text):
        self.msg_label.setText("Last MIDI: " + text)

    def _tick(self):
        self.voice_label.setText("Voices: %d" % self.engine.active_note_count())
