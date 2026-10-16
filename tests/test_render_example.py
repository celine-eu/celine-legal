"""Every template renders for the example deployment, and names none of its actors.

Run: `uv run pytest tests/test_render_example.py`.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from celine.legal import build as legal_build

LEGAL = Path(__file__).resolve().parent.parent
TEMPLATES = LEGAL / "templates"
EXAMPLE = LEGAL / "data" / "example"

TEMPLATE_FILES = sorted(TEMPLATES.glob("documents/*/*/*.j2")) + sorted(TEMPLATES.glob("consent-texts/*/consent-texts.yaml.j2"))


def _build(docs: Path = EXAMPLE) -> legal_build.Build:
    return legal_build.build(docs)


def test_every_template_renders_for_the_example():
    result = _build()
    assert result.problems == []
    rendered = {(f.entry_id.split("/", 1)[1], f.version, f.lang) for f in result.files}
    for path in TEMPLATE_FILES:
        parts = path.relative_to(TEMPLATES).parts
        if parts[0] == "documents":
            _, template, version, name = parts
            assert any(t.endswith(template.removeprefix("rec-").removeprefix("dso-")) and v == version
                       and lang == name.removesuffix(".md.j2") for t, v, lang in rendered), path


def test_the_example_is_final_so_no_template_types_a_blank():
    assert all(f.status == "final" for f in _build().files)


def test_the_consent_texts_cover_every_consent_offer():
    texts = next(yaml.safe_load(f.text) for f in _build().files if f.lang is None)
    offers = yaml.safe_load((EXAMPLE / "sharing-offers.yaml").read_text())["sharing_offers"]
    assert set(texts["texts"]) == {o["id"] for o in offers}
    for entry in texts["texts"].values():
        assert set(entry) == {"version", "it", "en"}


def test_the_rendered_documents_name_the_example_actors():
    """The values come through: each actor's name appears where its documents are."""
    by_id = {(f.entry_id, f.lang): f.text for f in _build().files}
    assert "Example REC" in by_id[("example-rec/terms-of-use", "it")]
    assert "Example DSO" in by_id[("example-dso/data-processing-agreement", "en")]
    assert "Example Platform" in by_id[("platform/sub-processors", "en")]
    assert "EXAMPLE" in by_id[("dataspace/participation-agreement", "en")]


def _actor_values() -> set[str]:
    parties = yaml.safe_load((EXAMPLE / "parties.yaml").read_text())
    identity = yaml.safe_load((EXAMPLE / "recs/example-rec/identity.yaml").read_text())
    values: set[str] = set()

    def walk(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                if key not in {"kind", "legal_form", "country", "region"}:
                    walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)
        elif isinstance(value, str) and len(value) > 3:
            values.add(value)

    walk(parties["parties"])
    walk(parties["providers"])
    walk(parties["project"])
    walk(identity)
    return values


@pytest.mark.parametrize("path", sorted(TEMPLATES.rglob("*.j2")), ids=lambda p: str(p.relative_to(TEMPLATES)))
def test_no_template_types_an_example_value(path):
    values = _actor_values()
    text = re.sub(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", "", path.read_text(), flags=re.S)
    assert [v for v in values if v in text] == []


def test_a_final_edition_with_a_blank_is_refused(tmp_path):
    docs = tmp_path / "docs"
    shutil.copytree(EXAMPLE, docs)
    identity = docs / "recs/example-rec/identity.yaml"
    identity.write_text(identity.read_text().replace('dpo: "dpo@rec.example.org"', 'dpo: "[•]"'))
    problems = _build(docs).problems
    assert problems and all("final but still has a blank" in p for p in problems)


def test_a_missing_value_is_refused(tmp_path):
    docs = tmp_path / "docs"
    shutil.copytree(EXAMPLE, docs)
    identity = docs / "recs/example-rec/identity.yaml"
    identity.write_text("\n".join(l for l in identity.read_text().splitlines() if not l.startswith("pec:")))
    assert any("pec" in p for p in _build(docs).problems)


def test_a_schema_error_stops_the_build(tmp_path):
    docs = tmp_path / "docs"
    shutil.copytree(EXAMPLE, docs)
    identity = docs / "recs/example-rec/identity.yaml"
    identity.write_text(identity.read_text() + "unknown_field: x\n")
    result = _build(docs)
    assert result.files == [] and any("unknown_field" in p for p in result.problems)


# ── the site ──────────────────────────────────────────────────────────────────


def _site(docs: Path = EXAMPLE, mode: str = "sample"):
    result = _build(docs) if mode == "sample" else legal_build.stable(docs)
    assert result.problems == []
    files, problems = legal_build.site(result, docs, mode)
    assert problems == []
    return {f.path: f.text for f in files}


def test_each_community_has_its_own_current_set():
    import json

    site = _site()
    first = json.loads(site["example-rec/current.json"])["slots"]
    second = json.loads(site["example-rec-2/current.json"])["slots"]
    assert first["privacy"]["paths"]["it"] == "/example-rec/app-privacy-notice/0.1/it/"
    assert second["privacy"]["paths"]["it"] == "/example-rec-2/app-privacy-notice/0.1/it/"
    assert first["privacy"]["sha256"] != second["privacy"]["sha256"]
    assert "Example REC 2" in site["example-rec-2/app-privacy-notice/0.1/it.md"]
    assert "Example REC 2" not in site["example-rec/app-privacy-notice/0.1/it.md"]


def test_an_external_slot_links_its_owner_with_the_captured_hash():
    import json

    statute = json.loads(_site()["example-rec/current.json"])["slots"]["statute"]
    assert statute["external"] and statute["url"] == "https://rec.example.org/statute.pdf"
    assert statute["version"] == "2024-01" and statute["sha256"] == "0" * 64


def test_index_lists_every_page_with_the_hash_of_its_text():
    import hashlib
    import json

    site = _site()
    pages = json.loads(site["index.json"])["pages"]
    assert pages
    for page in pages:
        text = site[page["text"].strip("/")]
        assert hashlib.sha256(text.encode()).hexdigest() == page["sha256"]


def _deployed(tmp_path):
    """The example as the stable site serves it: every final edition published."""
    docs, templates = _copy(tmp_path)
    _publish(docs, templates, "2026-01-01T00:00:00Z")
    result = legal_build.stable(docs)
    assert result.problems == []
    files, problems = legal_build.site(result, docs, "final")
    assert problems == []
    return {f.path: f.text for f in files}


# What only one community's text or link carries ("Example REC" is inside the second
# one's legal name, so names are not enough).
COMMUNITIES = {
    "example-rec": ("00000000003", "info@rec.example.org", "/example-rec/"),
    "example-rec-2": ("00000000005", "info@rec2.example.org", "/example-rec-2/"),
}


def _named(text: str) -> list[str]:
    return [key for key, marks in COMMUNITIES.items() if any(mark in text for mark in marks)]


def test_a_deployed_host_never_lists_one_community_beside_another(tmp_path):
    site = _deployed(tmp_path)
    for path, text in site.items():
        assert len(_named(text)) <= 1, f"{path} names {_named(text)}"
    assert "index.json" not in site


def test_a_deployed_host_serves_no_signed_agreement(tmp_path):
    site = _deployed(tmp_path)
    signed = ("example-rec/data-sharing-agreement", "example-rec/data-processing-agreement", "example-dso/")
    assert [p for p in site if p.startswith(signed)] == []


def test_every_host_answers_its_health_check(tmp_path):
    assert _site()["healthz"] == "ok\n"
    assert _deployed(tmp_path)["healthz"] == "ok\n"


def test_a_rebuild_is_identical():
    assert _site() == _site()


def test_a_slot_naming_an_unknown_document_is_refused(tmp_path):
    docs = tmp_path / "docs"
    shutil.copytree(EXAMPLE, docs)
    register = yaml.safe_load((docs / "register.yaml").read_text())
    register["recs"]["example-rec"]["roles"]["terms"] = "example-rec/no-such-document"
    (docs / "register.yaml").write_text(yaml.safe_dump(register))
    _, problems = legal_build.site(_build(docs), docs, "sample")
    assert problems == ["example-rec: slot terms names example-rec/no-such-document, which the register does not have"]


def _copy(tmp_path):
    """A writable copy of the example deployment and of the templates."""
    docs, templates = tmp_path / "docs", tmp_path / "templates"
    shutil.copytree(EXAMPLE, docs)
    shutil.copytree(TEMPLATES, templates, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    return docs, templates


def _publish(docs, templates, when):
    result = legal_build.build(docs, None, templates)
    assert result.problems == []
    return legal_build.publish([f for f in result.files if f.published_at is None], docs, when)


def _site_of(docs, templates, mode="sample"):
    import json

    result = legal_build.build(docs, None, templates) if mode == "sample" else legal_build.stable(docs)
    assert result.problems == []
    files, problems = legal_build.site(result, docs, mode)
    assert problems == []
    return {f.path: (json.loads(f.text) if f.path.endswith(".json") else f.text) for f in files}


def test_a_published_text_cannot_change(tmp_path):
    docs, templates = _copy(tmp_path)
    assert _publish(docs, templates, "2026-01-01T00:00:00Z")
    assert _publish(docs, templates, "2026-02-01T00:00:00Z") == []  # nothing new, nothing overwritten
    identity = docs / "recs/example-rec/identity.yaml"
    identity.write_text(identity.read_text().replace("Piazza Esempio 3", "Piazza Esempio 4"))
    problems = _build(docs).problems
    assert problems and all("no longer renders to its published text" in p for p in problems)
    assert any(p.startswith("example-rec/terms-of-use 0.1") for p in problems)


def test_with_nothing_published_every_stable_slot_is_pending(tmp_path):
    docs, _ = _copy(tmp_path)
    site = _site_of(docs, None, "final")
    current = site["example-rec/current.json"]
    assert set(current["slots"]) == {"statute"}  # the owner's own document, published by its owner
    assert current["pending"] == ["data_sharing_notice", "privacy", "terms"]
    assert [p for p in site if p.endswith(".md")] == []


def test_the_stable_site_serves_the_published_version_while_the_next_is_drafted(tmp_path):
    docs, templates = _copy(tmp_path)
    _publish(docs, templates, "2026-01-01T00:00:00Z")
    shutil.copytree(templates / "documents/terms-of-use/0.1", templates / "documents/terms-of-use/0.9")
    page = templates / "documents/terms-of-use/0.9/en.md.j2"
    page.write_text(page.read_text().replace("\n## 1.", "\nA drafted paragraph.\n\n## 1.", 1))
    register = yaml.safe_load((docs / "register.yaml").read_text())
    for entry in register["documents"]:
        if entry["id"] == "example-rec/terms-of-use":
            entry["version"], entry["status"] = "0.9", "draft"
    (docs / "register.yaml").write_text(yaml.safe_dump(register))
    stable = _site_of(docs, templates, "final")
    assert stable["example-rec/current.json"]["slots"]["terms"]["version"] == "0.1"
    assert stable["example-rec/current.json"]["slots"]["terms"]["status"] == "final"
    assert not any("A drafted paragraph." in v for v in stable.values() if isinstance(v, str))
    draft = _site_of(docs, templates, "sample")
    assert draft["example-rec/current.json"]["slots"]["terms"]["version"] == "0.9"
    assert "A drafted paragraph." in draft["example-rec/terms-of-use/0.9/en.md"]


def test_an_edited_published_text_is_refused(tmp_path):
    docs, templates = _copy(tmp_path)
    _publish(docs, templates, "2026-01-01T00:00:00Z")
    frozen = docs / "editions/example-rec/terms-of-use/0.1/it.md"
    frozen.write_text(frozen.read_text() + "\nAn edit after publication.\n")
    assert any("not the one recorded at publication" in p for p in legal_build.stable(docs).problems)


def test_an_unknown_mode_stops_the_render():
    assert legal_build.render(EXAMPLE, "staging")[2] == ["mode 'staging': not one of sample, final"]


def test_every_published_version_stays_and_a_date_maps_to_one(tmp_path):
    docs, templates = _copy(tmp_path)
    _publish(docs, templates, "2026-01-01T00:00:00Z")
    # A new template version of the terms, then the register moves to it.
    old, new = templates / "documents/terms-of-use/0.1", templates / "documents/terms-of-use/0.9"
    shutil.copytree(old, new)
    for lang in ("it", "en"):
        page = new / f"{lang}.md.j2"
        page.write_text(page.read_text().replace("\n## 1.", "\nNew paragraph.\n\n## 1.", 1))
    register = yaml.safe_load((docs / "register.yaml").read_text())
    for entry in register["documents"]:
        if entry["id"] == "example-rec/terms-of-use":
            entry["version"] = "0.9"
    (docs / "register.yaml").write_text(yaml.safe_dump(register))
    _publish(docs, templates, "2026-03-01T00:00:00Z")

    site = _site_of(docs, templates)
    assert site["example-rec/current.json"]["slots"]["terms"]["version"] == "0.9"
    assert site["example-rec/current.json"]["slots"]["terms"]["published_at"] == "2026-03-01T00:00:00Z"
    assert "New paragraph." not in site["example-rec/terms-of-use/0.1/it.md"]  # served as published
    assert "New paragraph." in site["example-rec/terms-of-use/0.9/it.md"]
    history = site["example-rec/history.json"]["slots"]["terms"]
    assert [h["version"] for h in history] == ["0.1", "0.9"]
    assert legal_build.version_at(history, "2025-12-31T23:59:59Z") is None
    assert legal_build.version_at(history, "2026-02-15T10:00:00Z") == "0.1"
    assert legal_build.version_at(history, "2026-03-01T00:00:00Z") == "0.9"
    assert legal_build.version_at(history, "2026-09-01T00:00:00Z") == "0.9"


def test_current_and_history_follow_their_schemas(tmp_path):
    docs, templates = _copy(tmp_path)
    _publish(docs, templates, "2026-01-01T00:00:00Z")
    site = _site_of(docs, templates)
    registry = legal_build._schemas(TEMPLATES)
    stable = _site_of(docs, templates, "final")
    for owner in ("example-rec", "example-rec-2", "platform"):
        for each in (site, stable):
            assert legal_build.validate(each[f"{owner}/current.json"], "current.schema.json", registry) == []
            assert legal_build.validate(each[f"{owner}/history.json"], "history.schema.json", registry) == []


def test_a_slot_named_like_an_owner_is_refused(tmp_path):
    docs = tmp_path / "docs"
    shutil.copytree(EXAMPLE, docs)
    register = yaml.safe_load((docs / "register.yaml").read_text())
    register["recs"]["example-rec"]["roles"]["platform"] = "example-rec/terms-of-use"
    (docs / "register.yaml").write_text(yaml.safe_dump(register))
    _, problems = legal_build.site(_build(docs), docs, "sample")
    assert problems == ["slot platform is named like an owner or a document folder; rename it"]




# ── publishing what was approved ──────────────────────────────────────────


def _draft_terms(tmp_path) -> Path:
    docs = tmp_path / "docs"
    shutil.copytree(EXAMPLE, docs)
    register = yaml.safe_load((docs / "register.yaml").read_text())
    for entry in register["documents"]:
        entry["approved_sha256"] = {}
        if entry["id"] == "example-rec/terms-of-use":
            entry["status"] = "draft"
    (docs / "register.yaml").write_text(yaml.safe_dump(register))
    return docs


def _approve_what_the_draft_shows(docs: Path) -> None:
    """The parties approve the fingerprints the draft shows; then the entries become final."""
    drafts = _build(docs).files
    register = yaml.safe_load((docs / "register.yaml").read_text())
    for entry in register["documents"]:
        for f in drafts:
            if f.entry_id == entry["id"]:
                entry.setdefault("approved_sha256", {})[f.lang or "all"] = f.approval_sha256
        if entry.get("status") == "draft":
            entry["status"] = "final"
    (docs / "register.yaml").write_text(yaml.safe_dump(register))


def test_publishing_needs_a_release(tmp_path, capsys):
    docs = _draft_terms(tmp_path)
    assert legal_build.main(["--data", str(docs), "--mode", "final", "--out", str(tmp_path / "o"), "--publish"]) == 1
    assert "a stable release is vX.Y.Z" in capsys.readouterr().out


def test_publishing_refuses_what_nobody_approved(tmp_path, capsys):
    docs = _draft_terms(tmp_path)
    register = yaml.safe_load((docs / "register.yaml").read_text())
    for entry in register["documents"]:
        entry["status"] = "final" if entry.get("status") == "draft" else entry.get("status")
    (docs / "register.yaml").write_text(yaml.safe_dump(register))
    args = ["--data", str(docs), "--mode", "final", "--out", str(tmp_path / "o"), "--publish", "--release", "v0.1.0"]
    assert legal_build.main(args) == 1
    assert "no approved_sha256 in the register" in capsys.readouterr().out
    assert not (docs / "editions").exists()


def test_publishing_what_was_approved_records_how_it_was_made(tmp_path, capsys):
    docs = _draft_terms(tmp_path)
    _approve_what_the_draft_shows(docs)
    args = ["--data", str(docs), "--mode", "final", "--out", str(tmp_path / "o"), "--publish",
            "--release", "v0.1.0", "--revision", "f" * 40, "--at", "2026-01-01T00:00:00Z"]
    assert legal_build.main(args) == 0, capsys.readouterr().out
    record = yaml.safe_load((docs / "editions/index.yaml").read_text())["editions"]["example-rec/terms-of-use"]["0.1"]
    assert record["release"] == "v0.1.0" and record["revision"] == "f" * 40
    assert record["template"] == "terms-of-use/0.1" and record["renderer"].startswith("celine-legal ")
    assert record["features"] == {"ai_assistant": True, "document_extraction": True, "dso_data_exchange": True,
                                  "existing_members": True, "sms_verification": True}
    assert legal_build.releases(docs) == ["v0.1.0"]


def test_a_text_changed_after_approval_is_refused(tmp_path, capsys):
    docs = _draft_terms(tmp_path)
    _approve_what_the_draft_shows(docs)
    identity = docs / "recs/example-rec/identity.yaml"
    identity.write_text(identity.read_text().replace("Piazza Esempio 3", "Piazza Esempio 9"))
    args = ["--data", str(docs), "--mode", "final", "--out", str(tmp_path / "o"), "--publish", "--release", "v0.1.0"]
    assert legal_build.main(args) == 1
    assert "differs from the text the parties approved" in capsys.readouterr().out


def test_missing_offers_are_reported_not_a_crash(tmp_path):
    docs = tmp_path / "docs"
    shutil.copytree(EXAMPLE, docs)
    (docs / "sharing-offers.yaml").unlink()
    assert [p for p in legal_build.build(docs).problems if p.startswith("no sharing offers at")]
