"""Render a deployment's legal documents from the templates.

    legal-build --data <data dir> --mode sample|final --out <dir> [--offers <file>]
    legal-build --data <data dir> --mode final --out <dir> --publish --release vX.Y.Z

The templates are the package's own (``templates/`` beside this file in a wheel, the
project's ``templates/`` in a checkout), or ``--templates``. The data directory is
the deployment's: ``register.yaml`` (which document, which template version, for which
actor, and which optional features the deployment has), ``parties.yaml`` (every party that
is not an energy community), ``recs/<rec>/identity.yaml`` (each community's identity, a
snapshot of the rec-registry) and the sharing offers members consent to
(``sharing-offers.yaml`` unless ``--offers``). Nothing in the templates names an actor;
every name comes from the data.

The legal host (``celine.legal.app``) lays out the same two sites at startup; this command
is for checking a deployment's data and for ``--publish``.

Output: ``<out>`` is what the legal host serves; it renders the pages over it.

    <out>/<id>/<version>/<lang>.md                 a document's text, as rendered
    <out>/<id>/<version>/consent-texts.yaml        a community's consent texts
    <out>/<owner>/current.json                     the owner's slots: version, paths, sha256, published_at
    <out>/<owner>/history.json                     per slot, every published version with its published_at
    <out>/<owner>/about.json                       who the owner is: name, website (the host matches a Referer)
    <out>/index.json                               every page (the draft only)
    <out>/healthz                                  "ok"

An owner is a community (its registry key) or ``platform``, for the documents common to
every community.

**Two sites that never meet.** ``sample`` is the draft: the data rendered as it is now,
drafts included, the whole catalogue for review (the agreements accepted by signature
included), and every page and ``current.json`` say it is not valid. ``final`` is the stable
site: the published editions only, as they were frozen, nothing rendered; per slot the
newest published version, and a slot with none is ``pending`` (not yet available). It never
lists one organisation's documents beside another's, and never serves a document accepted
by signature (the agreements between organisations are signed copies). The sha256 in
``current.json`` and ``history.json`` is the text's, the rendered markdown, so a restyled
page does not change what a reader accepted.

**Publishing freezes a text.** ``--publish`` copies each final edition not yet published
into ``<data>/editions/<id>/<version>/`` and records when, with its sha256, in
``<data>/editions/index.yaml``. From then on the build serves that copy, never a new
rendering: a template or a party's data may change, a published text may not. The current
edition must still render to exactly that copy; when it no longer does, the change needs a
new version. Every published version stays on the site, and ``history.json`` says when each
became current, so an acceptance recorded with only a date maps to exactly one version
(``version_at``).

Refused, and reported on exit 1:

- a data file that does not match its schema (``schemas/``);
- a feature not declared, or an environment override naming none (``features.py``);
- a variable a template uses and the data does not supply (StrictUndefined);
- a ``final`` edition still showing the blank ``[•]``;
- a final edition that no longer renders to its published text (the draft), or whose frozen
  copy no longer has the sha256 recorded at publication (both);
- a slot naming a document the register does not have, or a slot named like an owner.

Left out, and reported: a document that exists only with a feature that is off
(``templates/features.yaml``, ``documents``), with its slots.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from datetime import datetime, timezone
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Mapping
from typing import Any

import jinja2
import jsonschema
import yaml
from referencing import Registry, Resource

from . import features as legal_features



def _templates() -> Path:
    """The templates a wheel carries beside this file, else the checkout's ``templates/``."""
    packaged = Path(__file__).resolve().parent / "templates"
    return packaged if packaged.is_dir() else Path(__file__).resolve().parents[3] / "templates"


TEMPLATES = _templates()
BLANK = "[•]"
# Every mode a render is for. Anything else stops it: a misspelt `final` must not render
# drafts, and a misspelt `sample` must not pass for a text in force.
MODES = ("sample", "final")
SAMPLE = "sample"
FINAL = "final"
# First path segments the legal host's people-facing URLs keep for themselves.
RESERVED = {"api", "catalogue", "healthz", "platform", "static"}


def _url_name(name: str) -> str:
    """A slot or owner as people's URLs write it: ``data_sharing_notice`` → ``data-sharing-notice``."""
    return name.replace("_", "-")
EDITIONS = "editions"
_FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Rendered:
    """One rendered file: where it goes and what it says."""

    entry_id: str
    version: str
    lang: str | None
    path: Path
    text: str
    status: str
    published_at: str | None = None
    # The sha256 this text will have once final: what the parties approve while it is a draft
    # (a final text differs from its draft in its front matter and its signature blocks).
    approval_sha256: str | None = None
    template: str | None = None
    release: str | None = None  # the stable release it was published in


@dataclass
class Build:
    files: list[Rendered] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    features: dict[str, bool] = field(default_factory=dict)
    omitted: dict[str, str] = field(default_factory=dict)  # entry id -> the feature that is off


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _schemas(templates: Path) -> Registry:
    resources = []
    for path in sorted((templates / "schemas").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate(document: Any, schema_id: str, registry: Registry) -> list[str]:
    """Every schema error in ``document``, one line each. Pure."""
    schema = registry.contents(schema_id)
    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    return [
        f"{schema_id}: {'/'.join(str(p) for p in error.absolute_path) or '(root)'}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    ]


def environment(templates: Path) -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates)),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )


def _actors(entry: dict, register: dict, parties: dict, identities: dict) -> dict:
    """The actors a register entry is rendered for: ``rec`` and/or ``dso``."""
    actors: dict[str, Any] = {}
    target = entry.get("for") or {}
    if "rec" in target:
        rec_key = target["rec"]
        actors["rec"] = identities[rec_key]
        dso_key = ((register.get("recs") or {}).get(rec_key) or {}).get("dso")
        if dso_key:
            actors["dso"] = parties["parties"][dso_key]
    if "dso" in target:
        actors["dso"] = parties["parties"][target["dso"]]
    return actors


def context(
    entry: dict,
    lang: str | None,
    register: dict,
    parties: dict,
    identities: dict,
    offers: dict,
    consent_texts: dict | None,
    features: dict[str, bool],
) -> dict:
    """Everything a template may read. Pure."""
    roles = parties.get("roles") or {}
    all_parties = parties.get("parties") or {}
    actors = _actors(entry, register, parties, identities)
    # Offer recipients and holders are named by alias: a party's key, one of its
    # `aliases`, or a community's registry key.
    by_alias: dict[str, dict] = {}
    for key, party in all_parties.items():
        for alias in [key, *(party.get("aliases") or [])]:
            by_alias[alias] = party
    for key, identity in identities.items():
        by_alias[key] = identity
    return {
        "doc": {
            "id": entry["id"],
            "template": entry["template"],
            "version": str(entry["version"]),
            "status": entry.get("status"),
            "lang": lang,
            "langs": list(entry.get("langs") or []),
            # The date the version takes effect (ISO 8601), as the text states it.
            "effective": str(entry.get("effective") or BLANK),
            # The terms a community sets for a template that asks for them.
            "params": entry.get("params") or {},
        },
        "parties": all_parties,
        "roles": roles,
        "platform": all_parties[roles["platform_operator"]],
        "processing": parties.get("processing") or [],
        "hosting": parties.get("hosting") or [],
        "project": parties.get("project") or {},
        "providers": parties.get("providers") or {},
        "party_by_alias": by_alias,
        "offers": offers.get("sharing_offers") or [],
        "offers_by_id": {o["id"]: o for o in offers.get("sharing_offers") or []},
        "consent_texts": consent_texts or {},
        "features": features,
        **actors,
    }


def _template_path(entry: dict, lang: str | None) -> str:
    if entry.get("kind") == "consent-texts":
        return f"consent-texts/{entry['version']}/consent-texts.yaml.j2"
    return f"documents/{entry['template']}/{entry['version']}/{lang}.md.j2"


def offers_file(data: Path, offers: Path | None = None) -> Path:
    """The sharing offers: the given file, else the data's own ``sharing-offers.yaml``."""
    return offers or data / "sharing-offers.yaml"


def build(
    data: Path, offers_path: Path | None = None, templates: Path = TEMPLATES,
    environ: Mapping[str, str] | None = None,
) -> Build:
    """Render every templated register entry as the data says now (the draft), and add every
    published edition as it was frozen.

    Writes nothing. ``environ`` holds the feature overrides (``LEGAL_FEATURE_*``); none by
    default.
    """
    result = Build()
    registry = _schemas(templates)
    register = _load_yaml(data / "register.yaml")
    parties = _load_yaml(data / "parties.yaml")
    if not offers_file(data, offers_path).is_file():
        result.problems.append(f"no sharing offers at {offers_file(data, offers_path)} (an empty "
                               "`sharing_offers: []` if the deployment has none)")
        return result
    offers = _load_yaml(offers_file(data, offers_path))
    result.problems += validate(parties, "parties.schema.json", registry)
    known = legal_features.catalogue(templates)
    result.features, problems = legal_features.resolve(register.get("features"), environ or {}, known)
    result.problems += problems
    if not problems:
        result.omitted = legal_features.omitted(register.get("documents") or [], result.features, known)

    identities: dict[str, dict] = {}
    for rec_key, rec in (register.get("recs") or {}).items():
        identity = _load_yaml(data / rec["identity"])
        result.problems += [f"{rec_key}: {p}" for p in validate(identity, "identity.schema.json", registry)]
        identities[rec_key] = identity
    if result.problems:
        return result

    jinja = environment(templates)
    entries = [e for e in register.get("documents") or [] if e.get("template") and e["id"] not in result.omitted]
    # Consent texts first: the documents that cite them read their versions and offers.
    entries.sort(key=lambda e: e.get("kind") != "consent-texts")
    texts_by_rec: dict[str, dict] = {}

    for entry in entries:
        status = entry.get("status")
        rec_key = (entry.get("for") or {}).get("rec")
        langs = [None] if entry.get("kind") == "consent-texts" else entry.get("langs") or []
        for lang in langs:
            ctx = context(entry, lang, register, parties, identities, offers, texts_by_rec.get(rec_key),
                          result.features)
            try:
                text = jinja.get_template(_template_path(entry, lang)).render(ctx)
            except jinja2.TemplateNotFound as missing:
                result.problems.append(f"{entry['id']}: no template {missing.name}")
                continue
            except jinja2.UndefinedError as undefined:
                result.problems.append(f"{entry['id']} ({lang or 'all'}): {undefined.message}")
                continue
            if status == "final" and BLANK in text:
                result.problems.append(f"{entry['id']} ({lang or 'all'}): final but still has a blank {BLANK}")
            approval = text
            if status != "final":
                as_final = {**ctx, "doc": {**ctx["doc"], "status": "final"}}
                approval = jinja.get_template(_template_path(entry, lang)).render(as_final)
            name = "consent-texts.yaml" if lang is None else f"{lang}.md"
            path = Path(entry["id"]) / str(entry["version"]) / name
            result.files.append(Rendered(entry["id"], str(entry["version"]), lang, path, text, str(status),
                                         approval_sha256=sha256(approval),
                                         template=f"{entry['template']}/{entry['version']}"))
            if lang is None:
                texts_by_rec[rec_key] = yaml.safe_load(text) or {}
    editions = load_editions(data)
    result.problems += check_editions(editions, data)
    result.problems += check_published(result.files, editions, data)
    for file in result.files:
        published = editions.get(file.entry_id, {}).get(file.version) or {}
        file.published_at, file.release = published.get("published_at"), published.get("release")
    result.files += past_editions(result.files, editions, data)
    return result


def stable(data: Path, templates: Path = TEMPLATES, environ: Mapping[str, str] | None = None) -> Build:
    """What the stable site serves: every published edition, as it was frozen, and nothing
    rendered. A template, code or data change cannot reach it; a draft never does.

    The features only decide which unpublished slots it announces as "not yet available": a
    document that exists only with a feature that is off here is not announced. What was
    published stays served.
    """
    result = Build()
    register = _load_yaml(data / "register.yaml")
    known = legal_features.catalogue(templates)
    features, problems = legal_features.resolve(register.get("features"), environ or {}, known)
    if not problems:  # a broken switch is the draft's to report
        result.omitted = legal_features.omitted(register.get("documents") or [], features, known)
    editions = load_editions(data)
    result.problems += check_editions(editions, data)
    if not result.problems:
        result.files = past_editions([], editions, data)
    return result


def _edition_name(lang: str | None) -> str:
    return "consent-texts.yaml" if lang is None else f"{lang}.md"


def load_editions(data: Path) -> dict:
    """``<data>/editions/index.yaml``: per id and version, ``published_at`` and ``sha256``."""
    path = data / EDITIONS / "index.yaml"
    return (_load_yaml(path) or {}).get("editions") or {} if path.exists() else {}


def check_editions(editions: dict, data: Path) -> list[str]:
    """A frozen edition whose file no longer has the sha256 recorded when it was published."""
    problems = []
    for entry_id, versions in sorted(editions.items()):
        for version, published in sorted(versions.items()):
            for key, recorded in sorted((published.get("sha256") or {}).items()):
                archived = data / EDITIONS / entry_id / version / _edition_name(None if key == "all" else key)
                if archived.exists() and sha256(archived.read_text(encoding="utf-8")) != recorded:
                    problems.append(f"{entry_id} {version} ({key}): editions/ holds a text whose sha256 is not "
                                    "the one recorded at publication; a published text was edited")
    return problems


def check_published(files: list[Rendered], editions: dict, data: Path) -> list[str]:
    """A published edition whose current rendering differs from its published text."""
    problems = []
    for file in files:
        published = editions.get(file.entry_id, {}).get(file.version)
        if published is None:
            continue
        key = file.lang or "all"
        archived = data / EDITIONS / file.entry_id / file.version / _edition_name(file.lang)
        if key not in (published.get("sha256") or {}) or not archived.exists():
            problems.append(f"{file.entry_id} {file.version} ({key}): published, but its text is missing from editions/")
        elif archived.read_text(encoding="utf-8") != file.text:
            problems.append(
                f"{file.entry_id} {file.version} ({key}): no longer renders to its published text — "
                "a template or the data changed; publish the change as a new version"
            )
    return problems


def past_editions(current: list[Rendered], editions: dict, data: Path) -> list[Rendered]:
    """Every published edition the current rendering does not already carry, as published."""
    have = {(f.entry_id, f.version, f.lang) for f in current}
    past = []
    for entry_id, versions in sorted(editions.items()):
        for version, published in sorted(versions.items()):
            for key in sorted((published.get("sha256") or {})):
                lang = None if key == "all" else key
                if (entry_id, version, lang) in have:
                    continue
                text = (data / EDITIONS / entry_id / version / _edition_name(lang)).read_text(encoding="utf-8")
                past.append(Rendered(entry_id, version, lang, Path(entry_id) / version / _edition_name(lang),
                                     text, "final", published.get("published_at"), release=published.get("release")))
    return past


RELEASE = re.compile(r"\Av(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")


def releases(data: Path) -> list[str]:
    """Every stable release recorded in ``editions/``, oldest first."""
    found = {record.get("release") for versions in load_editions(data).values() for record in versions.values()}
    return sorted((r for r in found if r and RELEASE.match(r)),
                  key=lambda r: tuple(int(n) for n in RELEASE.match(r).groups()))


def approval_problems(files: list[Rendered], data: Path) -> list[str]:
    """A final edition about to be published whose text is not the one the parties approved.

    The register records, per entry, ``approved_sha256: {<lang>: <sha256>}`` (``all`` for the
    consent texts): the fingerprint a draft page shows, the text as it reads once final.
    Publishing anything else would publish a text nobody approved.
    """
    entries = {e["id"]: e for e in _load_yaml(data / "register.yaml").get("documents") or []}
    problems = []
    for file in files:
        if file.status != "final":
            continue
        key = file.lang or "all"
        approved = (entries.get(file.entry_id, {}).get("approved_sha256") or {}).get(key)
        if approved is None:
            problems.append(f"{file.entry_id} {file.version} ({key}): no approved_sha256 in the register; "
                            "record the fingerprint the parties approved")
        elif approved != sha256(file.text):
            problems.append(f"{file.entry_id} {file.version} ({key}): differs from the text the parties approved "
                            f"(approved {approved[:12]}…, now {sha256(file.text)[:12]}…)")
    return problems


def provenance(release: str, revision: str | None, features: dict[str, bool]) -> dict:
    """How a publication was made: what a published edition records beside its text."""
    try:
        from importlib.metadata import version

        renderer = version("celine-legal")
    except Exception:  # noqa: BLE001 - a checkout run without installing still publishes
        renderer = "unknown"
    return {"release": release, "renderer": f"celine-legal {renderer}", "revision": revision,
            "features": dict(sorted(features.items()))}


def publish(files: list[Rendered], data: Path, when: str, made: dict | None = None) -> list[str]:
    """Freeze every final, unpublished edition in ``files`` into ``<data>/editions/``. Never overwrites.

    ``made`` is the publication's provenance (``provenance``), recorded with each edition
    together with its template and version.
    """
    editions = load_editions(data)
    added = []
    for file in files:
        if file.status != "final" or file.version in editions.get(file.entry_id, {}) and (
            file.lang or "all") in editions[file.entry_id][file.version].get("sha256", {}):
            continue
        record = editions.setdefault(file.entry_id, {}).setdefault(
            file.version, {"published_at": when, "sha256": {}, **({"template": file.template} if file.template else {}),
                           **(made or {})})
        record["sha256"][file.lang or "all"] = sha256(file.text)
        target = data / EDITIONS / file.entry_id / file.version / _edition_name(file.lang)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.text, encoding="utf-8")
        added.append(f"{file.entry_id} {file.version} {file.lang or 'all'}")
    if added:
        (data / EDITIONS).mkdir(parents=True, exist_ok=True)
        (data / EDITIONS / "index.yaml").write_text(
            "# Written by `legal-build --publish`. Each published edition: when it became current,\n"
            "# the sha256 of its text per language, and how it was made (release, renderer, template,\n"
            "# features, data revision). The text itself is beside this file and is served as it is.\n"
            "# Never edited: a change is a new version.\n"
            + yaml.safe_dump({"editions": editions}, sort_keys=True, allow_unicode=True),
            encoding="utf-8",
        )
    return added


def version_at(history: list[dict], when: str) -> str | None:
    """The version that was current at ``when`` (ISO 8601), from one slot of ``history.json``.

    The reference for L2: an acceptance recorded with a date and no version maps to the
    newest version published at or before that moment. Pure.
    """
    published = sorted((h for h in history if h.get("published_at")), key=lambda h: h["published_at"])
    current = None
    for entry in published:
        if entry["published_at"] <= when:
            current = entry["version"]
    return current


# ── the site ──────────────────────────────────────────────────────────────────


@dataclass
class SiteFile:
    path: str  # relative to the site root
    text: str


def title_of(text: str, default: str) -> str:
    """A text's first ``# `` heading, past its front matter."""
    match = _FRONT.match(text)
    body = match.group(2) if match else text
    return next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), default)


def _baseline_entry(data: Path, entry: dict) -> dict:
    """The baseline capture an external document's `files` points at, from its index."""
    path = next(iter((entry.get("files") or {}).values()), "")
    folder = data / Path(path).parent
    index = _load_yaml(folder / "index.yaml") if (folder / "index.yaml").exists() else {}
    name = Path(path).name
    return next((d for d in index.get("documents") or [] if d.get("original") == name), {})


def _first(by_lang: dict) -> dict:
    return next(iter(by_lang.values()))


def site(result: Build, data: Path, mode: str, label: dict | None = None) -> tuple[list[SiteFile], list[str]]:
    """Every file the legal host serves, from a build. Pure apart from reading the data.

    ``label`` names what is served, in every ``current.json``: ``{"revision": <commit>}`` for a
    draft, ``{"release": "vX.Y.Z"}`` for a stable release.
    """
    register = _load_yaml(data / "register.yaml")
    entries = {e["id"]: e for e in register.get("documents") or []}
    files: list[SiteFile] = []
    problems: list[str] = []
    pages: dict[tuple[str, str], dict] = {}  # (id, version) -> {lang: page}

    catalogue = mode != FINAL
    for rendered in result.files:
        if not catalogue and entries.get(rendered.entry_id, {}).get("acceptance") == "signature":
            continue  # a signed copy, never published
        base = f"{rendered.entry_id}/{rendered.version}"
        if rendered.lang is None:
            files.append(SiteFile(f"{base}/consent-texts.yaml", rendered.text))
            continue
        files.append(SiteFile(f"{base}/{rendered.lang}.md", rendered.text))
        entry = entries[rendered.entry_id]
        pages.setdefault((rendered.entry_id, rendered.version), {})[rendered.lang] = {
            "path": f"/{base}/{rendered.lang}/",
            "text": f"/{base}/{rendered.lang}.md",
            "sha256": sha256(rendered.text),
            "approval_sha256": rendered.approval_sha256,
            "title": title_of(rendered.text, rendered.entry_id),
            "status": rendered.status,
            "published_at": rendered.published_at,
            "release": rendered.release,
            "acceptance": entry.get("acceptance"),
        }

    def _langs(entry_id: str, by_lang: dict) -> list[str]:
        order = entries.get(entry_id, {}).get("langs") or []
        return [lang for lang in order if lang in by_lang] + sorted(set(by_lang) - set(order))

    versions_of: dict[str, list[str]] = {}
    for entry_id, version in pages:
        versions_of.setdefault(entry_id, []).append(version)

    recs = register.get("recs") or {}

    def slot(owner: str, name: str, entry_id: str) -> dict | None:
        entry = entries.get(entry_id)
        if entry_id in result.omitted and catalogue:
            return None  # its feature is off: the slot is not offered
        if entry is None:
            problems.append(f"{owner}: slot {name} names {entry_id}, which the register does not have")
            return None
        if entry.get("external"):
            capture = _baseline_entry(data, entry)
            url = entry.get("publish") if entry.get("publish") not in (None, BLANK) else None
            return {
                "id": entry_id, "external": True, "version": str(entry.get("version") or capture.get("fetched")),
                "url": url, "title": entry.get("title"),
                "captured": capture.get("fetched"), "sha256": capture.get("sha256"),
            }
        if not catalogue:
            # The stable site: the newest published version, whatever the register is drafting.
            published = [v for v in versions_of.get(entry_id, []) if _first(pages[(entry_id, v)]).get("published_at")]
            if not published:
                if entry_id not in result.omitted:  # announced only if it can exist here
                    pending.setdefault(owner, []).append(name)
                return None
            version = max(published, key=lambda v: _first(pages[(entry_id, v)])["published_at"])
        else:
            version = str(entry["version"])
        by_lang = pages.get((entry_id, version))
        if not by_lang:
            problems.append(f"{owner}: slot {name} names {entry_id} {version}, which was not rendered")
            return None
        langs = _langs(entry_id, by_lang)
        status = "final" if not catalogue else entry.get("status")
        value = {
            "id": entry_id, "version": version, "status": status,
            "published_at": _first(by_lang).get("published_at"),
            "paths": {lang: by_lang[lang]["path"] for lang in langs},
            "texts": {lang: by_lang[lang]["text"] for lang in langs},
            "sha256": {lang: by_lang[lang]["sha256"] for lang in langs},
            "titles": {lang: by_lang[lang]["title"] for lang in langs},
        }
        if status != "final":
            value["approval_sha256"] = {lang: by_lang[lang]["approval_sha256"] for lang in langs}
        return value

    def history(entry_id: str, current: dict) -> list[dict]:
        if current.get("external"):
            return [{"version": current["version"], "published_at": current.get("captured"),
                     "url": current.get("url"), "sha256": current.get("sha256")}]
        published = [
            {"version": v, "published_at": _first(pages[(entry_id, v)])["published_at"],
             **({"release": _first(pages[(entry_id, v)])["release"]} if _first(pages[(entry_id, v)])["release"] else {}),
             "paths": {lang: p["path"] for lang, p in pages[(entry_id, v)].items()},
             "texts": {lang: p["text"] for lang, p in pages[(entry_id, v)].items()},
             "sha256": {lang: p["sha256"] for lang, p in pages[(entry_id, v)].items()}}
            for v in versions_of.get(entry_id, []) if _first(pages[(entry_id, v)]).get("published_at")
        ]
        return sorted(published, key=lambda h: h["published_at"])

    owners: list[tuple[str, dict]] = [(rec, spec.get("roles") or {}) for rec, spec in recs.items()]
    owners.append(("platform", register.get("platform_roles") or {}))
    owner_keys = {owner for owner, _ in owners} | {e.split("/", 1)[0] for e in entries}
    # People's URLs are `/<slot>/<owner>` with `_` written `-`, so a slot and an owner, or
    # either and a path the host reserves, must differ in that form too.
    url_owners = {_url_name(o) for o in owner_keys}
    for owner, roles in owners:
        if owner != "platform" and _url_name(owner) in RESERVED:
            problems.append(f"owner {owner} is named like a path the legal host reserves; rename it")
        for name in roles:
            if _url_name(name) in RESERVED or _url_name(name) in url_owners:
                problems.append(f"slot {name} is named like an owner or a document folder; rename it")
    pending: dict[str, list[str]] = {}
    for owner, roles in owners:
        slots = {name: slot(owner, name, entry_id) for name, entry_id in roles.items()}
        current = {"owner": owner, "mode": mode, "valid": mode == FINAL, **(label or {}),
                   **({} if mode == FINAL else {"features": result.features}),
                   "slots": {k: v for k, v in slots.items() if v is not None}}
        if mode == FINAL:
            # Slots with no stable version yet: the host answers "not yet available" there.
            current["pending"] = sorted(pending.get(owner, []))
        files.append(SiteFile(f"{owner}/current.json", json.dumps(current, indent=2, ensure_ascii=False) + "\n"))
        past = {"owner": owner, "mode": mode,
                "slots": {k: history(roles[k], v) for k, v in current["slots"].items()}}
        files.append(SiteFile(f"{owner}/history.json", json.dumps(past, indent=2, ensure_ascii=False) + "\n"))
        files.append(SiteFile(f"{owner}/about.json", json.dumps(
            _about(owner, recs, data), indent=2, ensure_ascii=False) + "\n"))

    files.append(SiteFile("healthz", "ok\n"))
    if catalogue:
        index = [
            {"id": entry_id, "version": version, "lang": lang, **page,
             "owners": _owners(entries.get(entry_id, {}))}
            for (entry_id, version), by_lang in sorted(pages.items())
            for lang, page in by_lang.items()
        ]
        files.append(SiteFile("index.json", json.dumps({"mode": mode, "pages": index}, indent=2, ensure_ascii=False) + "\n"))
    return files, problems


def _owners(entry: dict) -> list[str]:
    """Who a register entry belongs to: its ``owner`` (one or a list), else what it is ``for``."""
    owner = entry.get("owner")
    if owner:
        return owner if isinstance(owner, list) else [owner]
    return list((entry.get("for") or {}).values()) or [entry.get("id", "").split("/", 1)[0]]


def _about(owner: str, recs: dict, data: Path) -> dict:
    """Who an owner is, as its own pages name it: what the legal host shows and matches a
    reader's ``Referer`` against (``website``). Only what its documents already publish."""
    if owner == "platform":
        parties = _load_yaml(data / "parties.yaml")
        operator = (parties.get("parties") or {}).get((parties.get("roles") or {}).get("platform_operator"), {})
        about = {"owner": owner, "kind": "platform", "name": operator.get("name"), "short": operator.get("short"),
                 "website": operator.get("website")}
    else:
        identity = _load_yaml(data / recs[owner]["identity"]) if recs.get(owner, {}).get("identity") else {}
        about = {"owner": owner, "kind": identity.get("kind", "rec"), "name": identity.get("name"),
                 "short": identity.get("display_name") or identity.get("short"), "website": identity.get("website"),
                 "email": identity.get("email"), "pec": identity.get("pec")}
    return {k: v for k, v in about.items() if v not in (None, BLANK)}


def render(data: Path, mode: str, offers: Path | None = None, templates: Path = TEMPLATES,
           environ: Mapping[str, str] | None = None, label: dict | None = None,
           ) -> tuple[Build, list[SiteFile], list[str]]:
    """One site, laid out: the draft (``sample``, the data rendered now) or the stable site
    (``final``, the published editions only). What the legal host runs at startup."""
    if mode not in MODES:
        return Build(), [], [f"mode {mode!r}: not one of {', '.join(MODES)}"]
    result = build(data, offers, templates, environ) if mode != FINAL else stable(data, templates, environ)
    if result.problems:
        return result, [], result.problems
    files, problems = site(result, data, mode, label)
    return result, files, problems


def write(files: list[SiteFile], out: Path) -> None:
    """Replace the site in ``out`` with ``files``: a page dropped from the build disappears."""
    if out.exists() and any(out.iterdir()):
        if not (out / "healthz").exists():
            raise SystemExit(f"{out} is not empty and holds no site this tool wrote; refusing to clear it")
        for old in sorted(out.rglob("*"), reverse=True):
            old.unlink() if old.is_file() else old.rmdir()
    for file in files:
        path = out / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file.text, encoding="utf-8")


def _git_head(path: Path) -> str | None:
    """The commit a git checkout holding ``path`` is at, or None."""
    import subprocess

    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--templates", type=Path, default=TEMPLATES)
    parser.add_argument("--offers", type=Path, help="the sharing offers; default <data>/sharing-offers.yaml")
    parser.add_argument("--mode", required=True, choices=MODES,
                        help="sample: the draft, rendered from the data now; final: the stable site, published editions only")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--publish", action="store_true", help="freeze every final, approved, unpublished edition")
    parser.add_argument("--at", help="the publication time to record (ISO 8601, UTC); default now")
    parser.add_argument("--release", help="with --publish: the release these editions belong to, vX.Y.Z")
    parser.add_argument("--revision", help="with --publish: the data's commit; default the data checkout's HEAD")
    args = parser.parse_args(argv)

    if args.publish:
        if not args.release or not RELEASE.match(args.release):
            print(f"  !! --release {args.release or '(missing)'}: a stable release is vX.Y.Z")
            return 1
        result = build(args.data, args.offers, args.templates, os.environ)
        fresh = [f for f in result.files if f.status == "final" and f.published_at is None]
        problems = result.problems or approval_problems(fresh, args.data)
        if problems:
            for problem in problems:
                print(f"  !! {problem}")
            return 1
        when = args.at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        made = provenance(args.release, args.revision or _git_head(args.data), result.features)
        added = publish(fresh, args.data, when, made)
        print(f"  published as {args.release}: {', '.join(added) or 'nothing new'}")
    result, files, problems = render(args.data, args.mode, args.offers, args.templates, os.environ)
    for problem in problems:
        print(f"  !! {problem}")
    if problems:
        return 1
    write(files, args.out)
    for entry_id, feature in sorted(result.omitted.items()):
        print(f"  -- left out, {feature} is off: {entry_id}")
    if args.mode == FINAL:
        pending = sorted({f"{f.path.split('/')[0]}: {', '.join(json.loads(f.text)['pending'])}"
                          for f in files if f.path.endswith("current.json") and json.loads(f.text)["pending"]})
        print(f"  -- not yet available: {'; '.join(pending) or 'none'}")
    else:
        drafts = sorted({f.entry_id for f in result.files if f.status != "final"})
        if drafts:
            print(f"  -- drafts: {', '.join(drafts)}")
        off = sorted(name for name, on in result.features.items() if not on)
        print(f"  -- features off: {', '.join(off) or 'none'}")
    print(f"  ok {args.mode}: {len(result.files)} documents, {len(files)} files in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
