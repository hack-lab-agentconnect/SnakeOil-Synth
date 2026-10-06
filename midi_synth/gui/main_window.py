"""Main window: fixed toolbars and status bar around a scrollable grid of parameter groups."""

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QGroupBox, QInputDialog, QLabel,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QToolBar, QHBoxLayout, QWidget,
)

from ..bindings import DEFAULT_NAME
from ..patches import INIT_NAME, PatchError, apply as apply_patch, capture
from ..profiles import ProfileError
from ..recorder import recording_path
from .controls import ParamControl
from .meter import ClickableLabel, LevelMeter
from .qwerty import QwertyKeyboard

# Grid cell (row, column, rowspan, colspan) freed by the LFO merge, holding
# the Mod Matrix group.
MOD_MATRIX_CELL = (1, 4, 1, 1)

GROUP_POSITIONS = {
    "Oscillator 1": (0, 0, 1, 1),
    "Oscillator 2": (0, 1, 1, 1),
    "Modulation": (0, 2, 1, 1),
    "Master": (0, 3, 1, 1),
    "Tempo": (0, 4, 1, 1),
    "Filter": (1, 0, 1, 1),
    "Filter Env": (1, 1, 1, 1),
    "Amp Envelope": (1, 2, 1, 1),
    "LFO": (1, 3, 1, 1),
    "Effects": (2, 0, 1, 3),
    "Unison": (2, 3, 1, 1),
    "Glide": (2, 4, 1, 1),
    "Noise": (0, 4, 1, 1),
}
# Groups listed with the same cell share it side by side (here Tempo and
# Noise, which are both small); this gives their relative widths.
SHARED_CELL_STRETCH = {"Tempo": 2, "Noise": 3}
GROUP_POSITIONS["Mod Matrix"] = MOD_MATRIX_CELL

# Registry groups kept out of the generic body (none at present).
HIDDEN_GROUPS = ()

# Groups whose controls wrap onto a new row after this many columns.
GROUP_COLUMNS = {"Oscillator 1": 3, "Filter": 3}

# Registry groups shown inside another group's box: registry group ->
# (box title, stack index). Each stack is one vertical column under a header
# label carrying the registry group's name. Patches and the registry keep the
# original group names.
MERGED_GROUPS = {"LFO 1": ("LFO", 0), "LFO 2": ("LFO", 1)}

# Groups laid out as toggle "blocks": each toggle heads a block whose
# dependent controls (Param.under) sit in a row beneath it.
BLOCK_GROUPS = ("Effects",)
BLOCK_MAX_COLUMNS = 6

# Mod Matrix columns, left to right: registry param suffix -> column header.
MATRIX_COLUMNS = (("src", "Source"), ("amt", "Scale"), ("dst", "Destination"))
MATRIX_TOOLTIP = ("Scale is relative: the destination's current value x "
                  "(1 + scale x source). A destination whose current value is 0 "
                  "stays 0.")

STACK_COMBO_CHARS = 9

# Short two-choice combos kept as narrow as a knob: param id -> width in pixels.
NARROW_COMBOS = {"lpf_slope": 66}
MIN_WINDOW_SIZE = (640, 420)
METER_INTERVAL_MS = 33


class _BodyScroll(QScrollArea):
    """Scroll area whose size hint follows its content (Qt caps the default)."""

    def sizeHint(self):
        widget = self.widget()
        if widget is None:
            return super().sizeHint()
        frame = 2 * self.frameWidth()
        return widget.sizeHint() + QSize(frame, frame)


class MainWindow(QMainWindow):
    def __init__(self, engine, registry, router, store, midi_ports, bridge,
                 patch_store=None, patch_defaults=None, recorder=None,
                 initial_patch=None):
        super().__init__()
        self.setWindowTitle("SnakeOil Synth")
        self.engine = engine
        self.recorder = recorder
        self.rec_btn = None
        self.qwerty = QwertyKeyboard(engine, self, on_change=self._on_qwerty_change)
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
        self._fit_to_screen()

        bridge.param_changed.connect(self._on_param_changed)
        bridge.learned.connect(self._on_learned)
        bridge.message.connect(self._on_message)

        self._reload_profiles(router.profile.name)
        self._refresh_badges()
        for warning in store.warnings:
            self.statusBar().showMessage(warning, 8000)
        if patch_store is not None:
            self._reload_patches(initial_patch or patch_store.last_used() or INIT_NAME)

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
        bar.addSeparator()
        self.qwerty_btn = QPushButton("QWERTY keys")
        self.qwerty_btn.setCheckable(True)
        self.qwerty_btn.setChecked(True)
        self.qwerty_btn.setToolTip(
            "Play notes from the computer keyboard (A W S E D F T G Y H U J K O L P ;). "
            "Z/X octave, C/V velocity.")
        self.qwerty_btn.toggled.connect(self.qwerty.set_enabled)
        bar.addWidget(self.qwerty_btn)
        if self.recorder is not None:
            self.rec_btn = QPushButton("Rec")
            self.rec_btn.setCheckable(True)
            self.rec_btn.setToolTip("Record the output to a WAV file")
            self.rec_btn.toggled.connect(self._on_rec_toggled)
            bar.addWidget(self.rec_btn)

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

    def _block_widths(self):
        """Columns each toggle block occupies, from its dependents' count."""
        counts = {}
        for param in self.registry:
            if param.group in BLOCK_GROUPS and param.under:
                root = param.under
                while self.registry[root].under:
                    root = self.registry[root].under
                counts[root] = counts.get(root, 0) + 1
        return {root: min(max(n, 1), BLOCK_MAX_COLUMNS) for root, n in counts.items()}

    def _place_block(self, box, param, control, cells, state, widths):
        """Place a control in a toggle-block group."""
        if param.under:
            root = param.under
            while self.registry[root].under:
                root = self.registry[root].under
            count = state[root] = state.get(root, 0) + 1
            rrow, rcol = cells[root]
            width = widths[root]
            row = rrow + 1 + (count - 1) // width
            col = rcol + (count - 1) % width
            span = 1
        else:
            width = widths.get(param.id, 1)
            row = 0
            col = sum(widths.get(k, 1) for k in cells if cells[k][0] == 0)
            span = width
        cells[param.id] = (row, col)
        box.layout().addWidget(control, row, col, 1, span)

    def _place_matrix(self, box, param, control):
        """Place a Mod Matrix control: row from its id, column from its suffix."""
        layout = box.layout()
        if layout.itemAtPosition(0, 0) is None:
            box.setToolTip(MATRIX_TOOLTIP)
            for col, (_suffix, text) in enumerate(MATRIX_COLUMNS):
                header = QLabel(text)
                header.setAlignment(Qt.AlignHCenter)
                header.setToolTip(MATRIX_TOOLTIP)
                layout.addWidget(header, 0, col)
            layout.setColumnStretch(1, 1)
        head, suffix = param.id.split("_")
        col = [s for s, _ in MATRIX_COLUMNS].index(suffix)
        layout.addWidget(control, int(head[3:]), col)

    def _build_body(self):
        groups = {}
        columns = {}
        members = {}
        widths = self._block_widths()
        stack_rows = {}
        for param in self.registry:
            if param.group in HIDDEN_GROUPS:
                continue
            title, stack = MERGED_GROUPS.get(param.group, (param.group, None))
            box = groups.get(title)
            if box is None:
                box = QGroupBox(title)
                box.setLayout(QGridLayout())
                groups[title] = box
            matrix = param.group == "Mod Matrix"
            control = ParamControl(self.registry, param, compact=matrix)
            if param.id in NARROW_COMBOS and isinstance(control.editor, QComboBox):
                control.editor.setFixedWidth(NARROW_COMBOS[param.id])
                control.editor.setStyleSheet("padding: 3px 4px;")
            control.learnRequested.connect(self._on_learn_requested)
            control.clearRequested.connect(self._on_clear_requested)
            cells = columns.setdefault(param.group, {})
            self.controls[param.id] = control
            if matrix:
                self._place_matrix(box, param, control)
                continue
            if stack is not None:
                if param.group not in stack_rows:
                    header = QLabel(param.group)
                    header.setAlignment(Qt.AlignHCenter)
                    box.layout().addWidget(header, 0, stack)
                if isinstance(control.editor, QComboBox):
                    # keep two side-by-side stacks narrow
                    control.editor.setSizeAdjustPolicy(
                        QComboBox.AdjustToMinimumContentsLengthWithIcon)
                    control.editor.setMinimumContentsLength(STACK_COMBO_CHARS)
                row = stack_rows[param.group] = stack_rows.get(param.group, 0) + 1
                box.layout().addWidget(control, row, stack)
                cells[param.id] = (row, stack)
                continue
            if param.group in BLOCK_GROUPS:
                self._place_block(box, param, control, cells, members, widths)
                continue
            if param.under:
                row, col = cells[param.under]
                row += 1
            else:
                index = sum(1 for pid in cells if not self.registry[pid].under)
                wrap = GROUP_COLUMNS.get(param.group)
                row, col = divmod(index, wrap) if wrap else (0, index)
            cells[param.id] = (row, col)
            box.layout().addWidget(control, row, col)
        for box in groups.values():
            box.layout().setContentsMargins(4, 2, 4, 4)
            box.layout().setSpacing(2)
        self.tempo_label = QLabel("")
        groups["Tempo"].layout().addWidget(self.tempo_label, 1, 0)
        self.meter = LevelMeter()
        master = groups["Master"].layout()
        meter_col = master.columnCount()
        master.addWidget(self.meter, 0, meter_col, Qt.AlignTop)
        self.limiter_label = ClickableLabel("GR off", self.engine.reset_limiter)
        self.limiter_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.limiter_label.setToolTip("Click to reset the held gain reduction")
        master.addWidget(self.limiter_label, 1, meter_col, Qt.AlignTop)
        grid = QGridLayout()
        grid.setContentsMargins(6, 2, 6, 4)
        grid.setSpacing(4)
        positions = list(GROUP_POSITIONS)
        cells = {}
        for index, (name, box) in enumerate(groups.items()):
            cells.setdefault(GROUP_POSITIONS.get(name, (3, index, 1, 1)), []).append(box)
        for cell, boxes in cells.items():
            if len(boxes) == 1:
                grid.addWidget(boxes[0], *cell)
                continue
            # several small groups share one grid cell, side by side in the
            # order they are listed in GROUP_POSITIONS
            boxes.sort(key=lambda b: positions.index(b.title()))
            holder = QWidget()
            stack = QHBoxLayout(holder)
            stack.setContentsMargins(0, 0, 0, 0)
            stack.setSpacing(4)
            for box in boxes:
                stack.addWidget(box, SHARED_CELL_STRETCH.get(box.title(), 1))
            grid.addWidget(holder, *cell)
        body = QWidget()
        body.setLayout(grid)
        self.scroll = _BodyScroll()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(body)
        self.setCentralWidget(self.scroll)
        self.setMinimumSize(*MIN_WINDOW_SIZE)

    def _fit_to_screen(self):
        hint = self.sizeHint()
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            hint = hint.boundedTo(QSize(avail.width(), avail.height()))
        self.resize(hint.expandedTo(QSize(*MIN_WINDOW_SIZE)))

    def _build_footer(self, midi_ports):
        bar = self.statusBar()
        self.port_label = QLabel("MIDI: " + (", ".join(midi_ports) or "none"))
        self.msg_label = QLabel("Last MIDI: –")
        self.voice_label = QLabel("Voices: 0")
        self.qwerty_label = QLabel(self.qwerty.status_text())
        self.rec_label = QLabel("")
        for label in (self.port_label, self.msg_label, self.voice_label,
                      self.qwerty_label, self.rec_label):
            bar.addPermanentWidget(label)
        app = QApplication.instance()
        app.installEventFilter(self.qwerty)
        app.applicationStateChanged.connect(self._on_app_state_changed)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(250)
        self._meter_failed = False
        self._meter_timer = QTimer(self)
        self._meter_timer.timeout.connect(self._meter_tick)
        self._meter_timer.start(METER_INTERVAL_MS)

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
        self.patch_box.blockSignals(True)
        self.patch_box.clear()
        for name in self.patch_store.names():
            self.patch_box.addItem(name, name)
        index = self.patch_box.findData(select, Qt.UserRole, Qt.MatchFixedString)
        if index < 0:
            select = INIT_NAME
            index = self.patch_box.findData(select, Qt.UserRole, Qt.MatchFixedString)
        self.patch_box.setCurrentIndex(index)
        self.patch_box.blockSignals(False)
        self.patch_name = select
        self.patch_modified = False
        self._update_patch_ui()

    def _update_patch_ui(self):
        index = self.patch_box.currentIndex()
        if index >= 0:
            name = self.patch_box.itemData(index)
            self.patch_box.setItemText(index, name + ("*" if self.patch_modified else ""))
        is_init = self._patch_is_init()
        exists = index >= 0
        self.patch_btn["save"].setEnabled(exists and not is_init)
        self.patch_btn["save"].setToolTip(
            "Init is read-only; use Save As… to keep this sound" if is_init
            else "Overwrite the current patch")
        self.patch_btn["rename"].setEnabled(exists and not is_init)
        self.patch_btn["delete"].setEnabled(exists and not is_init)

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

    def _update_tempo_label(self):
        external = self.engine.tempo.external_bpm()
        if external is not None:
            self.tempo_label.setText("%.1f BPM (MIDI clock)" % external)
        else:
            self.tempo_label.setText("%.0f BPM (manual)" % self.engine.params["tempo_bpm"])

    def _tick(self):
        self._update_tempo_label()
        self.voice_label.setText("Voices: %d" % self.engine.active_note_count())
        if self.recorder is not None and self.recorder.active:
            self.rec_label.setText("REC %02d:%02d" % divmod(int(self.recorder.elapsed), 60))

    def _meter_tick(self):
        try:
            left, right, clipped = self.engine.take_meter()
            self.meter.update_levels(left, right, clipped)
            reduction = self.engine.limiter_reduction_db()
            if not self.engine.params["auto_limiter"]:
                text = "GR off"
            elif reduction < 0.05:
                text = "GR 0.0 dB"
            else:
                text = "GR %.1f dB" % -reduction
            self.limiter_label.setText(text)
        except Exception as exc:
            if not self._meter_failed:
                self._meter_failed = True
                self.statusBar().showMessage("Level meter failed: %s" % exc, 10000)

    # ---- keyboard and recording ---------------------------------------

    def _on_qwerty_change(self):
        self.qwerty_label.setText(self.qwerty.status_text())

    def _on_app_state_changed(self, state):
        if state != Qt.ApplicationActive:
            self.qwerty.release_all()

    def event(self, event):
        if event.type() == QEvent.WindowDeactivate:
            self.qwerty.release_all()
        return super().event(event)

    def closeEvent(self, event):
        self._meter_timer.stop()
        self.qwerty.release_all()
        QApplication.instance().removeEventFilter(self.qwerty)
        if self.recorder is not None:
            self.recorder.stop()
        super().closeEvent(event)

    def _on_rec_toggled(self, checked):
        if checked:
            try:
                path = recording_path(self.store.directory)
                self.recorder.start(path, self.engine.sr)
            except (OSError, RuntimeError) as exc:
                self.rec_btn.blockSignals(True)
                self.rec_btn.setChecked(False)
                self.rec_btn.blockSignals(False)
                self.statusBar().showMessage("Recording failed: %s" % exc, 8000)
                return
            self.rec_label.setText("REC 00:00")
            self.statusBar().showMessage("Recording to %s" % path)
        else:
            path = self.recorder.path
            self.recorder.stop()
            self.rec_label.setText("")
            problems = self.recorder.problem_summary()
            if problems:
                self.statusBar().showMessage("Saved %s (%s)" % (path, problems), 12000)
            else:
                self.statusBar().showMessage("Saved %s" % path)
