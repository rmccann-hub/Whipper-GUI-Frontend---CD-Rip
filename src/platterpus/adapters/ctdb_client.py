# SPDX-License-Identifier: GPL-3.0-only
"""Adapter for the CUETools Database (CTDB) lookup service.

Clean-room per PLANNING.md KDD-16: implemented from the LGPL `cuetools.net`
reference and the protocol spec in `docs/archive/upstream-modification-investigation.md`
— never from the GPL-2.0-only `python-cuetoolsdb`. As an unmaintained/external
service this lives behind a thin adapter (Critical Rule #1) so the transport or
provider can be swapped without touching the verify logic.

⚠️ HARDWARE-VALIDATION GATE (KDD-16): the endpoint, query parameters, and
response element/attribute names are reconstructed from the spec and confirmed
present in the LGPL `CUEToolsDB.cs`, but the exact wire behaviour (does our
`toc=` string produce a hit? are these the live attribute names?) must be
verified against the real server with a known disc — see `docs/test-plan.md`.
The XML parsing is unit-tested against fixtures for *what we expect*.
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from platterpus import __version__
from platterpus.ctdb.toc import DiscToc

log = logging.getLogger(__name__)

# CTDB is queried over plain HTTP. The reference CUETools client uses
# `http://db.cuetools.net` (CUETools.CTDB/CUEToolsDB.cs: `urlbase = "http://" +
# server`), and the host serves no valid HTTPS certificate — `https://` fails
# with a hostname-mismatch (confirmed on real hardware, KDD-16). HTTP is correct
# here: this is a read-only public CRC lookup, and a rip's trust comes from
# comparing the returned CRC to our locally-computed one, not from the transport.
CTDB_SCHEME: str = "http"
CTDB_HOST: str = "db.cuetools.net"
LOOKUP_PATH: str = "/lookup2.php"
# A descriptive User-Agent is the MusicBrainz/CTDB community convention.
USER_AGENT: str = (
    f"platterpus/{__version__} (https://github.com/rmccann-hub/Platterpus)"
)
_HTTP_TIMEOUT_S: float = 20.0


@dataclass(frozen=True)
class CtdbEntry:
    """One CTDB database entry for a queried TOC.

    `crc`/`confidence` drive the verify verdict; `trackcrcs` is per-track.
    `npar`/`has_parity`/`syndrome`/`entry_id` are Phase-2 (repair) parity
    fields — parsed but unused by verify.
    """

    crc: int | None
    confidence: int
    track_crcs: tuple[int, ...] = ()
    npar: int = 0
    has_parity: bool = False
    entry_id: str = ""


@dataclass(frozen=True)
class CtdbLookupResult:
    """Outcome of a TOC lookup. `entries` empty ⇒ disc not in the database."""

    entries: tuple[CtdbEntry, ...] = ()

    @property
    def in_database(self) -> bool:
        return bool(self.entries)


class CtdbLookupError(RuntimeError):
    """Network/parse failure during a lookup (distinct from 'not in DB')."""


# Injectable fetcher: given a URL, return the response bytes. Default uses
# urllib; tests pass a fake that returns canned XML without touching the net.
Fetcher = Callable[[str], bytes]


class CTDBClient(ABC):
    """What the verify layer needs from CTDB: look up a disc by its TOC."""

    @abstractmethod
    def lookup(self, toc: DiscToc) -> CtdbLookupResult:
        """Return the CTDB entries for `toc` (empty result if not in the DB)."""
        raise NotImplementedError


def _default_fetcher(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_S) as response:
        return response.read()


class CtdbHttpImpl(CTDBClient):
    """HTTP implementation against `db.cuetools.net`."""

    def __init__(self, fetcher: Fetcher = _default_fetcher) -> None:
        self._fetch = fetcher

    def build_url(self, toc: DiscToc) -> str:
        """Compose the lookup2.php GET URL for `toc`.

        Params per the spec: version=3, ctdb=1, fuzzy=0, metadata=none, toc=…
        """
        query = urllib.parse.urlencode(
            {
                "version": "3",
                "ctdb": "1",
                "fuzzy": "0",
                "metadata": "none",
                "toc": toc.toc_string(),
            }
        )
        return f"{CTDB_SCHEME}://{CTDB_HOST}{LOOKUP_PATH}?{query}"

    def lookup(self, toc: DiscToc) -> CtdbLookupResult:
        url = self.build_url(toc)
        log.info("CTDB lookup: %s", url)
        try:
            raw = self._fetch(url)
        except Exception as exc:  # noqa: BLE001 — any transport error → our error
            raise CtdbLookupError(f"CTDB lookup failed: {exc}") from exc
        return parse_lookup_response(raw)


# --- Response parsing (pure; unit-tested against fixtures) ------------------


def _to_int(value: str | None, *, base: int = 10) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value, base)
    except ValueError:
        return None


def parse_lookup_response(raw: bytes) -> CtdbLookupResult:
    """Parse a CTDB `lookup2.php` XML body into a `CtdbLookupResult`.

    Reads ``<entry>`` elements with ``crc``/``confidence``/``npar``/``id``/
    ``hasParity``/``trackcrcs`` (confirmed present in the LGPL `CUEToolsDB.cs`).
    Robust to missing/extra attributes — unknown shapes yield no entries
    rather than raising. CRCs are hex unless they parse as decimal.
    """
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise CtdbLookupError(f"unparseable CTDB response: {exc}") from exc

    entries: list[CtdbEntry] = []
    # Accept <entry> at any depth (the wrapper element name is unconfirmed).
    for el in root.iter("entry"):
        crc = _to_int(el.get("crc"), base=16)
        if crc is None:
            crc = _to_int(el.get("crc"))
        confidence = _to_int(el.get("confidence")) or 0
        npar = _to_int(el.get("npar")) or 0
        has_parity = (el.get("hasParity") or "").strip().lower() in {"1", "true", "yes"}
        track_crcs = tuple(
            v
            for v in (
                _to_int(tok, base=16) for tok in (el.get("trackcrcs") or "").split()
            )
            if v is not None
        )
        entries.append(
            CtdbEntry(
                crc=crc,
                confidence=confidence,
                track_crcs=track_crcs,
                npar=npar,
                has_parity=has_parity,
                entry_id=el.get("id") or "",
            )
        )
    return CtdbLookupResult(entries=tuple(entries))
