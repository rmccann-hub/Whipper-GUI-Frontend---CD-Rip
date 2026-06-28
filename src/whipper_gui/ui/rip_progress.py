"""Rip progress widget — live status pane + AccurateRip results.

Three panes stacked vertically:

  Status line + QProgressBar
  Live whipper stdout (read-only QPlainTextEdit)
  Verification verdict banner (bold, colour-coded at-a-glance trust headline)
  AccurateRip results table (populated when the rip log lands)
  CTDB verdict line (second, TOC-keyed verification path)

The "View log" button opens the rip log file in the user's default
text viewer via QDesktopServices.openUrl().
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from whipper_gui.ctdb.verify import CtdbVerifyResult, Verdict
from whipper_gui.parsers.rip_log import (
    RipLog,
    track_accuraterip_verified,
)

log = logging.getLogger(__name__)

# AR table column layout. The brief calls out per-track AR confidence;
# we expose v1 and v2 separately since they can disagree.
_AR_COLUMNS: list[str] = ["#", "Title", "Status", "AR v1", "AR v2"]
_AR_COL_NUMBER: int = 0
_AR_COL_TITLE: int = 1
_AR_COL_STATUS: int = 2
_AR_COL_V1: int = 3
_AR_COL_V2: int = 4


# Hook so tests can intercept the "open file" action without launching
# a real text editor.
_OpenUrlFn = Callable[[QUrl], bool]


class RipProgress(QWidget):
    """Live progress + log + AccurateRip results."""

    def __init__(
        self,
        parent: QWidget | None = None,
        open_url: _OpenUrlFn | None = None,
    ) -> None:
        super().__init__(parent)
        # Inject the openUrl function so tests can verify the action
        # without launching a real viewer.
        self._open_url: _OpenUrlFn = open_url or QDesktopServices.openUrl
        self._log_path: Path | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # --- Overall progress (whole rip) ---
        # A coarse start-to-finish bar so the user can gauge how much of
        # the entire disc is left, independent of the per-track churn.
        overall_row = QHBoxLayout()
        overall_row.addWidget(QLabel("Overall", self))
        self._overall_bar: QProgressBar = QProgressBar(self)
        self._overall_bar.setRange(0, 100)
        self._overall_bar.setValue(0)
        self._overall_bar.setTextVisible(True)
        overall_row.addWidget(self._overall_bar, stretch=1)
        root.addLayout(overall_row)

        # --- Status line + current-task progress bar ---
        # The status label names the current operation; the task bar
        # tracks that one operation's 0-100% (it resets read→verify→encode).
        self._status_label: QLabel = QLabel("Idle.", self)
        root.addWidget(self._status_label)

        self._progress_bar: QProgressBar = QProgressBar(self)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        root.addWidget(self._progress_bar)

        # --- Live whipper stdout ---
        self._log_view: QPlainTextEdit = QPlainTextEdit(self)
        self._log_view.setReadOnly(True)
        # Cap at a reasonable scrollback so a long rip doesn't blow up
        # memory; whipper emits thousands of lines per rip.
        self._log_view.setMaximumBlockCount(10_000)
        root.addWidget(self._log_view, stretch=1)

        # --- Verification verdict banner (at-a-glance trust) ---
        # A single bold, colour-coded headline above the per-track table so the
        # user sees "is this rip trustworthy?" without reading every row. Green
        # = every audio track matched AccurateRip (bit-perfect, community-
        # verifiable); amber = a partial match worth a look; grey = nothing to
        # assert yet (e.g. a disc not in the database). Populated from the
        # parsed log by set_rip_log; hidden until then. The wording NEVER over-
        # claims — it mirrors what AccurateRip actually returned.
        self._verdict_banner: QLabel = QLabel("", self)
        self._verdict_banner.setWordWrap(True)
        self._verdict_banner.setVisible(False)
        root.addWidget(self._verdict_banner)

        # --- AccurateRip results table ---
        self._ar_table: QTableWidget = QTableWidget(0, len(_AR_COLUMNS), self)
        self._ar_table.setHorizontalHeaderLabels(_AR_COLUMNS)
        self._ar_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._ar_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._ar_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._ar_table.verticalHeader().setVisible(False)
        header = self._ar_table.horizontalHeader()
        header.setSectionResizeMode(_AR_COL_TITLE, QHeaderView.ResizeMode.Stretch)
        for col in (_AR_COL_NUMBER, _AR_COL_STATUS, _AR_COL_V1, _AR_COL_V2):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._ar_table, stretch=1)

        # --- CTDB verdict line (second, TOC-keyed verification path) ---
        # Sits directly under the AccurateRip table — a one-liner that only
        # appears when a CTDB verify ran (it's an opt-in, post-rip network
        # check). Until the audio-CRC algorithm is hardware-validated a match
        # is shown as "experimental" (KDD-16); see set_ctdb_result.
        self._ctdb_label: QLabel = QLabel("", self)
        self._ctdb_label.setWordWrap(True)
        self._ctdb_label.setVisible(False)
        root.addWidget(self._ctdb_label)

        # --- View log button ---
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._view_log_button: QPushButton = QPushButton("View log", self)
        self._view_log_button.setEnabled(False)
        self._view_log_button.clicked.connect(self._on_view_log_clicked)
        button_row.addWidget(self._view_log_button)
        root.addLayout(button_row)

    # --- Public surface -----------------------------------------------------

    def clear(self) -> None:
        """Reset to the idle state. Called when starting a new rip."""
        self._status_label.setText("Idle.")
        self._overall_bar.setValue(0)
        self._progress_bar.setValue(0)
        self._log_view.clear()
        self._verdict_banner.clear()
        self._verdict_banner.setVisible(False)
        self._ar_table.setRowCount(0)
        self._ctdb_label.clear()
        self._ctdb_label.setVisible(False)
        self._view_log_button.setEnabled(False)
        self._log_path = None

    def append_log_line(self, line: str) -> None:
        """Append one line of whipper output to the streaming log view."""
        self._log_view.appendPlainText(line)

    def set_progress(self, overall: float, task: float) -> None:
        """Update both progress bars.

        `overall` is the whole-rip percentage (monotonic); `task` is the
        current operation's own 0-100%. The status label is driven
        separately via `set_status` (fed from the rip worker's phase
        signal), so the label stays meaningful during phases that have no
        numeric percent.
        """
        self._overall_bar.setValue(int(overall))
        self._progress_bar.setValue(int(task))

    def set_status(self, text: str) -> None:
        """Set the status label (start/finish + per-phase updates)."""
        self._status_label.setText(text)

    def set_rip_log(self, rip_log: RipLog) -> None:
        """Populate the AccurateRip table + verdict banner from a parsed log."""
        message, level = accuraterip_verdict(rip_log)
        if message:
            self._verdict_banner.setText(message)
            self._verdict_banner.setStyleSheet(_banner_style(level))
            self._verdict_banner.setVisible(True)
        else:
            self._verdict_banner.setVisible(False)

        tracks = rip_log.tracks
        self._ar_table.setRowCount(len(tracks))
        for row, track in enumerate(tracks):
            number_item = QTableWidgetItem(str(track.number))
            title_item = QTableWidgetItem(_basename(track.filename))
            status_item = QTableWidgetItem(track.status or "")
            v1_item = QTableWidgetItem(_ar_cell(track.accuraterip_v1))
            v2_item = QTableWidgetItem(_ar_cell(track.accuraterip_v2))
            self._ar_table.setItem(row, _AR_COL_NUMBER, number_item)
            self._ar_table.setItem(row, _AR_COL_TITLE, title_item)
            self._ar_table.setItem(row, _AR_COL_STATUS, status_item)
            self._ar_table.setItem(row, _AR_COL_V1, v1_item)
            self._ar_table.setItem(row, _AR_COL_V2, v2_item)

    def set_ctdb_status(self, text: str) -> None:
        """Show an in-progress CTDB line (e.g. 'Verifying against CTDB…')."""
        self._ctdb_label.setText(text)
        self._ctdb_label.setVisible(True)

    def set_ctdb_result(self, result: CtdbVerifyResult) -> None:
        """Render the final CTDB verdict under the AccurateRip table.

        A match that isn't yet trustworthy (the audio-CRC algorithm is not
        hardware-validated, KDD-16) is labelled experimental — we never claim
        a verification the algorithm can't yet stand behind.
        """
        self._ctdb_label.setText(ctdb_verdict_line(result))
        self._ctdb_label.setStyleSheet(_banner_style(ctdb_verdict_level(result)))
        self._ctdb_label.setVisible(True)

    def set_log_path(self, path: Path | None) -> None:
        """Enable the View Log button (when path is non-empty and exists)."""
        if path is None or str(path) == "":
            self._log_path = None
            self._view_log_button.setEnabled(False)
            return
        self._log_path = path
        # Don't gate on .exists() — the file may be reachable by
        # xdg-open even if a Path test fails (e.g., relative path).
        self._view_log_button.setEnabled(True)

    # --- Internals ----------------------------------------------------------

    def _on_view_log_clicked(self) -> None:
        if self._log_path is None:
            return
        url = QUrl.fromLocalFile(str(self._log_path))
        self._open_url(url)


def ctdb_verdict_line(result: CtdbVerifyResult) -> str:
    """One-line, user-facing summary of a CTDB verify outcome.

    Pure function (no widget) so it's unit-testable. The MATCH wording is the
    important safety case: until ``result.trustworthy`` (the CRC algorithm is
    hardware-validated, KDD-16) a match is spelled out as *experimental*, never
    as a plain "verified" — mirroring the rip's own "never claim a check that
    didn't run" rule.
    """
    verdict = result.verdict
    if verdict is Verdict.MATCH:
        if result.trustworthy:
            return f"CTDB: verified ✓ (confidence {result.confidence})"
        return (
            f"CTDB: CRC matched (confidence {result.confidence}) — "
            "EXPERIMENTAL, pending hardware validation of the CRC algorithm "
            "(not yet a confirmed verification)"
        )
    if verdict is Verdict.NO_MATCH:
        return "CTDB: no match — this rip differs from the database entries"
    if verdict is Verdict.NOT_IN_DATABASE:
        return "CTDB: this disc isn’t in the database"
    if verdict is Verdict.DECODER_UNAVAILABLE:
        return "CTDB: not verified — install the `flac` decoder to enable this"
    return "CTDB: verification unavailable (lookup or decode error)"


def ctdb_verdict_level(result: CtdbVerifyResult) -> str:
    """Banner level ("ok" | "warn" | "neutral") for a CTDB verdict.

    Pairs with :func:`ctdb_verdict_line` to colour the label. A *trustworthy*
    match is green; an experimental (not-yet-hardware-validated) match is amber
    — never green, mirroring the wording's refusal to over-claim. Everything
    else (no match, not in DB, decoder missing, error) is neutral grey: those
    are "couldn't confirm", not "failed".
    """
    verdict = result.verdict
    if verdict is Verdict.MATCH:
        return "ok" if result.trustworthy else "warn"
    return "neutral"


def accuraterip_verdict(rip_log: object) -> tuple[str, str]:
    """At-a-glance AccurateRip verdict: ``(message, level)``.

    ``level`` is "ok" (all audio tracks verified — bit-perfect against the
    shared AccurateRip database), "warn" (some but not all matched), or
    "neutral" (none matched — typically a disc nobody has submitted, e.g. a
    CD-R). An empty ``message`` means "show nothing" (no audio tracks parsed).

    Pure and never-raises (reads via ``getattr``) so it accepts both the
    whipper and cyanrip ``RipLog`` shapes and any partially-parsed log. The
    wording never claims more than AccurateRip returned — this is the trust
    headline, so it must be honest above all.
    """
    tracks = getattr(rip_log, "tracks", ()) or ()
    # Audio tracks only: a data track has neither a Copy CRC nor an AR result.
    audio = [
        t
        for t in tracks
        if getattr(t, "copy_crc", "")
        or getattr(t, "accuraterip_v1", None) is not None
        or getattr(t, "accuraterip_v2", None) is not None
    ]
    total = len(audio)
    if total == 0:
        return "", "neutral"
    verified = sum(1 for t in audio if track_accuraterip_verified(t))
    if verified == total:
        confidences = [
            conf
            for t in audio
            for conf in (
                getattr(getattr(t, "accuraterip_v1", None), "confidence", None),
                getattr(getattr(t, "accuraterip_v2", None), "confidence", None),
            )
            if conf is not None
        ]
        tail = f" (confidence {min(confidences)}+)" if confidences else ""
        return (
            f"✓ Bit-perfect: all {total} tracks verified against AccurateRip{tail}",
            "ok",
        )
    if verified > 0:
        return (
            f"⚠ {verified} of {total} tracks verified against AccurateRip — "
            "the rest aren't in the database or didn't match (see the table)",
            "warn",
        )
    return (
        "AccurateRip: no tracks matched the database — expected for a disc "
        "nobody has submitted (e.g. a burned CD-R); the per-track Copy CRCs "
        "below still prove a secure read",
        "neutral",
    )


# Banner colours by level. Muted, theme-neutral hues that read on both light
# and dark Qt palettes; the bold weight does the "look here" work.
_BANNER_COLORS: dict[str, str] = {
    "ok": "#1a7f37",  # green — trustworthy
    "warn": "#9a6700",  # amber — needs a look
    "neutral": "#57606a",  # grey — nothing to assert
}


def _banner_style(level: str) -> str:
    """Qt stylesheet for a verdict label at the given level."""
    color = _BANNER_COLORS.get(level, _BANNER_COLORS["neutral"])
    return f"QLabel {{ color: {color}; font-weight: bold; padding: 2px; }}"


def _basename(path: str) -> str:
    """Render a track filename as just its basename without extension."""
    if not path:
        return ""
    stem = Path(path).stem
    return stem or path


def _ar_cell(result: object) -> str:
    """Render an AccurateRipResult (or None) for one cell."""
    if result is None:
        return "—"
    # Don't import the dataclass to avoid circular fuss; rely on duck
    # typing — RipLog hands us AccurateRipResult instances directly.
    confidence = getattr(result, "confidence", None)
    result_text = getattr(result, "result", "") or ""
    if confidence is None:
        return result_text or "—"
    if "exact match" in result_text:
        return f"OK ({confidence})"
    if "not present" in result_text.lower():
        return "not in DB"
    return f"{result_text} ({confidence})"
