"""The legal host's decisions, over a rendered site: which organisation a request is for, and
what a people-facing path shows. Pure: the site is the files ``build.site`` laid out, held in
memory. The HTTP layer is ``app.py``, the pages ``pages.py``.

People's URLs put the slot first, with ``_`` written ``-``:

    /                                platform documents, plus the resolved organisation's
    /{org}                           one organisation's overview
    /{slot}/{org}[/{version}[/{lang}]]
    /{slot}                          no organisation in the path: resolve it, or name none
    /catalogue                       every document, for review (sample mode only)

The organisation is resolved, in order, from ``?for=`` (or ``?org=``), then the ``Referer``:
a page of this host names it in its path, another site by its origin, matched against each
owner's ``website``. A path naming its organisation never needs resolving.

The paths the build has always served, ``/{org}/{slot}/[{lang}/]`` and the versioned pages
``/{owner}/{document}/{version}/{lang}/``, answer with a permanent redirect to the new ones,
so a link an application already holds keeps working.

One organisation's view never lists another's documents; only a sample host's catalogue
lists them all, for review.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit

import markdown

PLATFORM = "platform"
_FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)


def url_name(name: str) -> str:
    return name.replace("_", "-")


def slot_name(segment: str) -> str:
    return segment.replace("-", "_")


def _host(value: str | None) -> str:
    host = (value or "").split("@")[-1].split(":")[0].strip().lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


@dataclass
class Owner:
    key: str
    about: dict
    current: dict
    history: dict

    @property
    def slots(self) -> dict[str, dict]:
        return self.current.get("slots") or {}

    @property
    def pending(self) -> list[str]:
        """Slots with no stable version yet (the stable site only)."""
        return self.current.get("pending") or []

    def has(self, slot: str) -> bool:
        return slot in self.slots or slot in self.pending


@dataclass
class Result:
    """What a path shows: a view, or a redirect, or nothing (404)."""

    status: int = 200
    view: dict | None = None
    redirect: str | None = None

    def as_json(self) -> dict:
        return {"status": self.status, "redirect": self.redirect} if self.redirect else {"status": self.status, **(self.view or {})}


@dataclass
class Request:
    path: str
    query: dict[str, str] = field(default_factory=dict)
    referer: str | None = None
    host: str | None = None
    accept_language: str | None = None


class Site:
    """A rendered site: ``{path: text}``, as ``build.site`` laid it out."""

    def __init__(self, files: dict[str, str]):
        self.files = files
        owners = {}
        for path in sorted(files):
            folder, _, name = path.rpartition("/")
            if name != "current.json" or "/" in folder:
                continue
            owners[folder] = Owner(
                folder,
                json.loads(files.get(f"{folder}/about.json", "null")) or {"owner": folder},
                json.loads(files[path]),
                json.loads(files.get(f"{folder}/history.json", "null")) or {"slots": {}},
            )
        self.owners = owners
        index = files.get("index.json")
        self.catalogue: dict | None = json.loads(index) if index else None
        platform = owners.get(PLATFORM)
        self.mode: str = (platform.current.get("mode") if platform else None) or "sample"
        self.features: dict = (platform.current.get("features") if platform else None) or {}
        self.base = ""  # the path prefix the host serves this site under (a draft's)
        self.label: dict = {}  # {"revision": …} for a draft, {"release": …} for a stable release

    # ── the parts ─────────────────────────────────────────────────────────

    @property
    def platform(self) -> Owner | None:
        return self.owners.get(PLATFORM)

    def organisation(self, key: str | None) -> Owner | None:
        """An organisation (not the platform) by its key, in either spelling."""
        if not key:
            return None
        for candidate in (key, slot_name(key)):
            if candidate != PLATFORM and candidate in self.owners:
                return self.owners[candidate]
        for owner in self.owners.values():
            if owner.key != PLATFORM and url_name(owner.key) == key:
                return owner
        return None

    def text(self, path: str) -> str | None:
        """A file of the site by its site path."""
        return self.files.get(path.lstrip("/"))

    # ── resolution ────────────────────────────────────────────────────────

    def resolve(self, request: Request) -> tuple[Owner | None, str | None]:
        """The organisation a request is for, and how it was found."""
        for name in ("for", "org"):
            owner = self.organisation(request.query.get(name))
            if owner:
                return owner, "query"
        if not request.referer:
            return None, None
        referer = urlsplit(request.referer)
        if request.host and _host(referer.netloc) == _host(request.host):
            # A page of this host: its path or its own query names the organisation.
            for segment in [s for s in referer.path.split("/") if s][:2]:
                owner = self.organisation(segment)
                if owner:
                    return owner, "referer"
            for part in referer.query.split("&"):
                name, _, value = part.partition("=")
                if name in ("for", "org") and self.organisation(value):
                    return self.organisation(value), "referer"
            return None, None
        origin = _host(referer.netloc)
        for owner in self.owners.values():
            website = owner.about.get("website")
            if owner.key != PLATFORM and website and _host(urlsplit(website).netloc) == origin:
                return owner, "referer"
        return None, None

    # ── views ─────────────────────────────────────────────────────────────

    def view(self, request: Request) -> Result:
        segments = [s for s in request.path.split("/") if s]
        lang = request.query.get("lang")
        keep = {"lang": lang} if lang else {}

        if not segments:
            owner, via = self.resolve(request)
            return Result(view={"view": "landing", "platform": self._listing(self.platform, request),
                                "organisation": self._overview(owner, request) if owner else None,
                                "resolved_by": via, "catalogue": self.catalogue is not None})
        head, rest = segments[0], segments[1:]

        if head == "catalogue" and not rest:
            if self.catalogue is None:
                return Result(404)
            return Result(view={"view": "catalogue", "pages": self.catalogue.get("pages") or []})
        if head == PLATFORM:
            if not rest:
                return Result(301, redirect=_url("/", keep))
            if self.platform and slot_name(rest[0]) in self.platform.pending and len(rest) == 1:
                return Result(301, redirect=_url(f"/{rest[0].replace('_', '-')}", keep))
            slot = self._platform_slot(rest[0])
            if slot and len(rest) == 1:
                return Result(301, redirect=_url(f"/{url_name(slot)}", keep))
            if slot and len(rest) == 2 and re.fullmatch(r"[a-z]{2}", rest[1]):
                return Result(301, redirect=self._document_url(
                    self.platform, slot, self.platform.slots[slot].get("version"), rest[1]))
            # A versioned page by register id (`platform/sub-processors/0.1/it/`).
            return self._by_id(PLATFORM, rest)

        org = self.organisation(head)
        if org:
            if not rest:
                return Result(view={"view": "organisation", **self._overview(org, request)})
            return self._legacy(org.key, rest, keep)
        if rest:
            # A versioned page under a register id whose prefix owns no slot (`dataspace/…`,
            # a grid operator's agreement).
            by_id = self._by_id(head, rest)
            if by_id.status != 404:
                return by_id

        slot = slot_name(head)
        if not rest:
            owner, via = self.resolve(request)
            if owner and owner.has(slot):
                return Result(302, redirect=_url(f"/{url_name(slot)}/{url_name(owner.key)}", keep))
            if self.platform and slot in self.platform.slots:
                return self._document(self.platform, slot, [], request)
            if self.platform and slot in self.platform.pending:
                return self._pending(self.platform, slot)
            if any(o.has(slot) for o in self.owners.values()):
                return Result(view={"view": "unscoped", "slot": url_name(slot), "resolved_by": via})
            return Result(404)

        target, pinned = rest[0], rest[1:]
        if len(pinned) > 2:
            return Result(404)
        if target == PLATFORM:
            if not self.platform or slot not in self.platform.slots:
                return Result(404)
            if not pinned:
                return Result(301, redirect=_url(f"/{url_name(slot)}", keep))
            return self._document(self.platform, slot, pinned, request)
        org = self.organisation(target)
        if not org:
            return Result(404)
        if slot in org.pending and not pinned:
            return self._pending(org, slot)
        if slot not in org.slots:
            if self.platform and slot in self.platform.slots and not pinned:
                return Result(301, redirect=_url(f"/{url_name(slot)}", keep))
            return Result(404)
        return self._document(org, slot, pinned, request)

    def _platform_slot(self, segment: str) -> str | None:
        slot = slot_name(segment)
        return slot if self.platform and slot in self.platform.slots else None

    def _legacy(self, owner_key: str, rest: list[str], keep: dict) -> Result:
        """The paths the static host served, redirected for good to people's URLs."""
        # /{org}/{slot}/[{lang}/]
        owner = self.owners.get(owner_key)
        if owner and slot_name(rest[0]) in owner.pending and len(rest) <= 2:
            return Result(301, redirect=_url(self._slot_url(owner, slot_name(rest[0])), keep))
        if owner and slot_name(rest[0]) in owner.slots and len(rest) <= 2:
            slot = slot_name(rest[0])
            if len(rest) == 2:
                return Result(301, redirect=self._document_url(owner, slot, owner.slots[slot].get("version"), rest[1]))
            return Result(301, redirect=_url(self._slot_url(owner, slot), keep))
        return self._by_id(owner_key, rest)

    def _by_id(self, prefix: str, rest: list[str]) -> Result:
        """/{prefix}/{document}/[{version}/[{lang}/]]: a page by register id."""
        if len(rest) > 3:
            return Result(404)
        entry_id = f"{prefix}/{rest[0]}"
        for candidate in self.owners.values():
            for slot, value in candidate.slots.items():
                if value.get("id") == entry_id:
                    version = rest[1] if len(rest) > 1 else None
                    lang = rest[2] if len(rest) > 2 else None
                    return Result(301, redirect=self._document_url(candidate, slot, version, lang))
        if self.catalogue is not None and len(rest) == 3:
            return self._catalogue_document(entry_id, rest[1], rest[2])
        return Result(404)

    def _slot_url(self, owner: Owner, slot: str) -> str:
        return f"/{url_name(slot)}" if owner.key == PLATFORM else f"/{url_name(slot)}/{url_name(owner.key)}"

    def _document_url(self, owner: Owner, slot: str, version: str | None, lang: str | None) -> str:
        base = f"/{url_name(slot)}/{PLATFORM if owner.key == PLATFORM else url_name(owner.key)}"
        if not version:
            return self._slot_url(owner, slot)
        return f"{base}/{version}" + (f"/{lang}" if lang else "")

    def _pending(self, owner: Owner, slot: str) -> Result:
        """A slot with no stable version yet: it exists, and says so."""
        return Result(view={"view": "pending", "slot": url_name(slot), "organisation": _public(owner.about)})

    def _versions(self, owner: Owner, slot: str) -> list[dict]:
        """Every version of a slot the site holds, newest first: the published ones, and the
        current one (which is a draft on a sample host)."""
        current = owner.slots[slot]
        versions = {h["version"]: h for h in (owner.history.get("slots") or {}).get(slot) or []}
        versions.setdefault(current["version"], current)
        return sorted(
            ({"version": v, "published_at": e.get("published_at"), "paths": e.get("paths") or {},
              "texts": e.get("texts") or {}, "sha256": e.get("sha256") or {}} for v, e in versions.items()),
            key=lambda e: (e["published_at"] or "~", e["version"]), reverse=True,
        )

    def _document(self, owner: Owner, slot: str, pinned: list[str], request: Request) -> Result:
        current = owner.slots[slot]
        if current.get("external"):
            if current.get("url"):
                return Result(302, redirect=current["url"])
            return Result(view={"view": "unavailable", "slot": url_name(slot), "title": current.get("title"),
                                "organisation": _public(owner.about)})
        versions = self._versions(owner, slot)
        version = pinned[0] if pinned else current["version"]
        edition = next((v for v in versions if v["version"] == version), None)
        if edition is None or not edition["texts"]:
            return Result(404)
        langs = _ordered_langs(current, edition)
        if len(pinned) > 1:
            if pinned[1] not in edition["texts"]:
                return Result(404)
            lang = pinned[1]
        else:
            lang = _negotiate(request.query.get("lang"), request.accept_language, langs)
        raw = self.text(edition["texts"][lang])
        if raw is None:
            return Result(404)
        match = _FRONT.match(raw)
        body = match.group(2) if match else raw
        title = next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), slot)
        return Result(view={
            "view": "document",
            "slot": url_name(slot),
            "organisation": _public(owner.about),
            "id": current["id"],
            "version": version,
            "current_version": current["version"],
            "is_current": version == current["version"],
            "document_status": current.get("status") if version == current["version"] else "final",
            "published_at": edition["published_at"],
            "lang": lang,
            "langs": [{"lang": code, "url": self._document_url(owner, slot, version, code)} for code in langs],
            "versions": [{"version": v["version"], "published_at": v["published_at"],
                          "url": self._document_url(owner, slot, v["version"], None)} for v in versions],
            "title": title,
            "markdown": body,
            "html": render(body),
            "text": edition["texts"][lang],
            "sha256": edition["sha256"].get(lang),
            "approval_sha256": (current.get("approval_sha256") or {}).get(lang) if version == current["version"] else None,
            "url": self._slot_url(owner, slot),
        })

    def _catalogue_document(self, entry_id: str, version: str, lang: str) -> Result:
        """A document no slot names (an agreement for signing), in a sample host's catalogue only."""
        page = next((p for p in self.catalogue.get("pages") or []
                     if p["id"] == entry_id and p["version"] == version and p["lang"] == lang), None)
        raw = self.text(page["text"]) if page else None
        if raw is None:
            return Result(404)
        match = _FRONT.match(raw)
        return Result(view={"view": "document", "slot": None, "organisation": None, "id": entry_id,
                            "version": version, "current_version": version, "is_current": True,
                            "document_status": page.get("status"), "published_at": page.get("published_at"),
                            "acceptance": page.get("acceptance"),
                            "lang": lang, "langs": [], "versions": [], "title": page.get("title"),
                            "markdown": match.group(2) if match else raw,
                            "html": render(match.group(2) if match else raw), "text": page["text"],
                            "sha256": page.get("sha256"),
                            "approval_sha256": page.get("approval_sha256") if page.get("status") != "final" else None,
                            "url": None})

    def _listing(self, owner: Owner | None, request: Request) -> list[dict]:
        if owner is None:
            return []
        lang = request.query.get("lang")
        items = []
        for slot, value in owner.slots.items():
            titles = value.get("titles") or {}
            preferred = _negotiate(lang, request.accept_language, list(titles)) if titles else None
            items.append({
                "slot": url_name(slot),
                "url": self._slot_url(owner, slot),
                "title": titles.get(preferred) if preferred else value.get("title") or url_name(slot),
                "version": value.get("version"),
                "status": value.get("status"),
                "external": bool(value.get("external")),
            })
        return items

    def _overview(self, owner: Owner, request: Request) -> dict:
        return {"organisation": _public(owner.about), "documents": self._listing(owner, request),
                "platform": self._listing(self.platform, request)}


def render(body: str) -> str:
    """A text as HTML, as the build renders its pages (the same extensions)."""
    return markdown.markdown(body, extensions=["tables", "sane_lists"], output_format="html")


def _public(about: dict) -> dict:
    return {k: about[k] for k in ("owner", "kind", "name", "short", "website", "email", "pec") if k in about}


def _ordered_langs(current: dict, edition: dict) -> list[str]:
    order = list((current.get("paths") or {}).keys())
    return [code for code in order if code in edition["texts"]] + sorted(set(edition["texts"]) - set(order))


def _negotiate(wanted: str | None, accept: str | None, langs: list[str]) -> str:
    """``?lang=``, then ``Accept-Language`` by weight, then the document's first language."""
    if wanted in langs:
        return wanted
    weighted = []
    for position, part in enumerate((accept or "").split(",")):
        tag, _, params = part.strip().partition(";")
        weight = 1.0
        if params.strip().startswith("q="):
            try:
                weight = float(params.strip()[2:])
            except ValueError:
                weight = 0.0
        if tag:
            weighted.append((-weight, position, tag.split("-")[0].lower()))
    for _, _, code in sorted(weighted):
        if code in langs:
            return code
    return langs[0]


def _url(path: str, query: dict[str, Any]) -> str:
    return f"{path}?{urlencode(query)}" if query else path
