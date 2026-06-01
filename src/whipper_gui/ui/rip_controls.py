"""Rip controls widget — Start / Cancel buttons.

On Start click, assembles a `RipParameters` from the current state and
emits `rip_requested(params)`. On Cancel, emits `cancel_requested`.

State (drive, release_id, unknown flag) is pushed in from the main
window via setter methods rather than queried from sibling widgets,
so this widget stays decoupled and easy to unit-test.

The Start button enables only when the minimum required state is
present: a drive AND a release_id (or just a drive when the user has
opted into unknown-album mode). Cancel is only enabled while a rip
is active.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from whipper_gui.config import Config
from whipper_gui.workers.rip_worker import RipParameters


class RipControls(QWidget):
    """Start / Cancel button pair plus the RipParameters assembly."""

    rip_requested = Signal(object)        # carries a RipParameters
    cancel_requested = Signal()
    force_stop_requested = Signal()       # drastic stop: eject + kill reader

    def __init__(
        self,
        config: Config,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config: Config = config
        self._drive: str = ""
        self._release_id: str = ""
        self._unknown_mode: bool = False
        self._rip_active: bool = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)

        self._start_button: QPushButton = QPushButton("Start rip", self)
        self._cancel_button: QPushButton = QPushButton("Cancel", self)
        # Force stop is the drastic escalation: eject + kill the in-container
        # reader, for when Cancel leaves the drive spinning. Enabled only
        # during a rip, same as Cancel.
        self._force_stop_button: QPushButton = QPushButton("Force stop", self)
        self._force_stop_button.setToolTip(
            "Eject and kill the reader if the drive keeps spinning after Cancel."
        )

        self._start_button.clicked.connect(self._on_start)
        self._cancel_button.clicked.connect(self._on_cancel)
        self._force_stop_button.clicked.connect(self._on_force_stop)

        layout.addWidget(self._start_button)
        layout.addWidget(self._cancel_button)
        layout.addWidget(self._force_stop_button)

        self._refresh_button_state()

    # --- Setters (called by main window) ------------------------------------

    def set_config(self, config: Config) -> None:
        """Replace the Config used to assemble rip parameters.

        The main window calls this after the user saves Settings so the
        next rip reflects the edited output dir, templates, and the
        Continue-on-CD-R toggle. Without it the widget would keep using
        the Config it was constructed with.
        """
        self._config = config

    def set_drive(self, device: str) -> None:
        self._drive = device or ""
        self._refresh_button_state()

    def set_release_id(self, mbid: str) -> None:
        self._release_id = mbid or ""
        self._refresh_button_state()

    def set_unknown_mode(self, unknown: bool) -> None:
        self._unknown_mode = bool(unknown)
        self._refresh_button_state()

    def set_rip_active(self, active: bool) -> None:
        """Toggle button states during a rip.

        Active rip: Start disabled, Cancel enabled.
        Idle:       Start enabled (if can_start), Cancel disabled.
        """
        self._rip_active = bool(active)
        self._refresh_button_state()

    # --- Read-back ----------------------------------------------------------

    def can_start(self) -> bool:
        """Return whether the Start button is currently enabled."""
        return self._start_button.isEnabled()

    def is_unknown_mode(self) -> bool:
        """Whether unknown-album mode is currently set.

        Used by the main window to guard against re-prompting the
        Unknown Album dialog when the user has already accepted it
        once in the current session.
        """
        return self._unknown_mode

    # --- Internals ----------------------------------------------------------

    def _refresh_button_state(self) -> None:
        self._start_button.setEnabled(
            (not self._rip_active) and self._has_minimum_state()
        )
        self._cancel_button.setEnabled(self._rip_active)
        self._force_stop_button.setEnabled(self._rip_active)

    def _has_minimum_state(self) -> bool:
        if not self._drive:
            return False
        if self._unknown_mode:
            return True
        return bool(self._release_id)

    def _on_start(self) -> None:
        # Unknown discs use the literal "Unknown Album" templates so the
        # disc-ID hash whipper puts in %d never reaches the path; known
        # discs use the rich tag-driven templates.
        if self._unknown_mode:
            track_template = self._config.track_template_unknown
            disc_template = self._config.disc_template_unknown
        else:
            track_template = self._config.track_template
            disc_template = self._config.disc_template
        params = RipParameters(
            drive=self._drive,
            release_id=self._release_id,
            output_dir=Path(self._config.output_dir),
            track_template=track_template,
            disc_template=disc_template,
            unknown=self._unknown_mode,
            cdr=self._config.continue_on_cdr,
            # EAC parity-gap flags, carried from Settings (KDD-13).
            cover_art=self._config.cover_art,
            force_overread=self._config.force_overread,
            max_retries=self._config.max_retries,
            keep_going=self._config.keep_going,
            read_offset_override=(
                self._config.read_offset
                if self._config.override_read_offset
                else None
            ),
        )
        self.rip_requested.emit(params)

    def _on_cancel(self) -> None:
        self.cancel_requested.emit()

    def _on_force_stop(self) -> None:
        self.force_stop_requested.emit()
