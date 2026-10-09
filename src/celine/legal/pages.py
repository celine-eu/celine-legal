"""The legal host's pages: a view (``site.py``) rendered as HTML with ``templates/page/``.

The text of a document is the deployment's own, rendered from its templates and data; the
page around it says only a few words, in Italian or English. A sample host says on every
page that its texts are not valid.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import jinja2

from .build import TEMPLATES

LANGS = ("it", "en")
DEFAULT_LANG = "it"  # the language members read

WORDS = {
    "it": {
        "legal": "Documenti legali",
        "platform": "Documenti della piattaforma",
        "platformNote": "Valgono per ogni organizzazione che usa la piattaforma.",
        "documentsOf": "Documenti di",
        "unscoped": "Ogni comunità pubblica il proprio documento: lo trovi nell'app della tua comunità, "
                    "o all'indirizzo che ti ha comunicato.",
        "unavailable": "Questo documento non è pubblicato online.",
        "requestCopy": "Puoi richiederne copia a",
        "version": "Versione",
        "published": "pubblicata il",
        "notPublished": "non ancora pubblicata",
        "versions": "Versioni",
        "current": "corrente",
        "notCurrent": "Questa non è la versione corrente.",
        "readCurrent": "Leggi la versione corrente",
        "sha": "Impronta SHA-256 del testo",
        "approval": "Impronta da approvare (il testo come sarà, definitivo)",
        "release": "Edizione",
        "pending": "Documento non ancora disponibile",
        "pendingNote": "Questo documento non è ancora stato pubblicato in una versione definitiva.",
        "nothingYet": "Nessun documento è ancora stato pubblicato.",
        "catalogue": "Tutti i documenti in revisione",
        "catalogueNote": "Ogni documento di ogni parte, compresi gli accordi da firmare, per la revisione.",
        "signature": "da firmare",
        "sample": "CAMPIONE — testi in revisione, non validi. Nessuna accettazione registrata qui vincola.",
        "notFound": "Pagina non trovata",
        "home": "Torna ai documenti",
    },
    "en": {
        "legal": "Legal documents",
        "platform": "Platform documents",
        "platformNote": "They apply to every organisation using the platform.",
        "documentsOf": "Documents of",
        "unscoped": "Each community publishes its own document: you find it in your community's app, "
                    "or at the address it gave you.",
        "unavailable": "This document is not published online.",
        "requestCopy": "You can request a copy from",
        "version": "Version",
        "published": "published on",
        "notPublished": "not published yet",
        "versions": "Versions",
        "current": "current",
        "notCurrent": "This is not the current version.",
        "readCurrent": "Read the current version",
        "sha": "SHA-256 of the text",
        "approval": "Fingerprint to approve (the text as it will be, final)",
        "release": "Release",
        "pending": "Document not yet available",
        "pendingNote": "This document has not been published in a final version yet.",
        "nothingYet": "No document has been published yet.",
        "catalogue": "Every document under review",
        "catalogueNote": "Every party's documents, the agreements for signature included, for review.",
        "signature": "for signature",
        "sample": "SAMPLE — texts under review, not valid. No acceptance recorded here binds anyone.",
        "notFound": "Page not found",
        "home": "Back to the documents",
    },
}

_MONTHS = {
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
           "ottobre", "novembre", "dicembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
}


def pick_lang(query: str | None, accept: str | None) -> str:
    """``?lang=``, then the browser's first language we have, then Italian."""
    if query in LANGS:
        return query
    for part in (accept or "").split(","):
        code = part.strip()[:2].lower()
        if code in LANGS:
            return code
    return DEFAULT_LANG


def date(value: str | None, lang: str) -> str:
    """An ISO 8601 timestamp as a long date: ``15 gennaio 2026``, ``15 January 2026``."""
    if not value:
        return ""
    day = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return f"{day.day} {_MONTHS.get(lang, _MONTHS['en'])[day.month - 1]} {day.year}"


class Pages:
    def __init__(self, mode: str, templates: Path = TEMPLATES, base: str = "", label: dict | None = None):
        self.mode = mode
        self.label = label or {}
        self.jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(templates)),
            undefined=jinja2.StrictUndefined,
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.jinja.filters["date"] = date
        # A site path as the reader's browser reaches it: under a draft's prefix.
        self.jinja.filters["u"] = lambda path: base + path if isinstance(path, str) and path.startswith("/") else path

    def view(self, view: dict, lang: str) -> str:
        return self._render(view["view"], lang, view=view)

    def error(self, status: int, lang: str) -> str:
        words = WORDS[lang]
        message = words["notFound"] if status == 404 else {"it": "Errore", "en": "Error"}[lang]
        return self._render("error", lang, message=message)

    def _render(self, name: str, lang: str, **values) -> str:
        return self.jinja.get_template(f"page/{name}.html.j2").render(
            lang=lang, w=WORDS[lang], mode=self.mode, label=self.label, **values)
