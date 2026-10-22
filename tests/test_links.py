"""A text's page links what the text refers to, and the text stays as it is.

The numbered headings get anchors, and the references a template version declares in its
``links.yaml`` become links: to a heading of the same text, or to the slot of the document
they name. Checked over the example deployment, every feature on.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from celine.legal import build as legal_build
from celine.legal.site import Request, Site, link, render

LEGAL = Path(__file__).resolve().parent.parent
EXAMPLE = LEGAL / "data" / "example"
DECLARED = sorted((LEGAL / "templates" / "documents").glob("*/*/links.yaml"))


def _site(base: str = "") -> Site:
    _, files, problems = legal_build.render(EXAMPLE, "sample")
    assert problems == []
    site = Site({f.path: f.text for f in files})
    site.base = base
    return site


SITE = _site()


def _html(path: str, site: Site = SITE) -> str:
    """A page's HTML, its whitespace runs written as one space."""
    result = site.view(Request(path))
    assert result.status == 200, (path, result.status)
    return " ".join(result.view["html"].split())


def test_numbered_headings_get_stable_anchors():
    html = render("## 5. Uso corretto\n\n### 2.1 La domanda\n\n## Annex 3 — Sub-processors\n\n"
                  "## Allegato 2 — Misure\n\n## Signatures\n")
    assert '<h2 id="sec-5">5. Uso corretto</h2>' in html
    assert '<h3 id="sec-2-1">2.1 La domanda</h3>' in html
    assert '<h2 id="annex-3">' in html and '<h2 id="annex-2">' in html
    assert "<h2>Signatures</h2>" in html


@pytest.mark.parametrize("declared", DECLARED, ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_every_declared_reference_is_found_in_its_text(declared):
    """A pattern that matches nothing is a reference the text no longer makes, or a typo."""
    template = f"{declared.parent.parent.name}/{declared.parent.name}"
    texts = [f for f in legal_build.build(EXAMPLE, None).files if f.template == template and f.lang]
    assert texts, f"the example renders no {template}"
    rules = yaml.safe_load(declared.read_text())
    for lang, declared_rules in rules.items():
        counts = [0] * len(declared_rules)
        for text in (t for t in texts if t.lang == lang):
            body = re.sub(r"\A---\n.*?\n---\n", "", text.text, flags=re.S)
            found = link(render(body), [(r["find"], "#x") for r in declared_rules])[1]
            counts = [a + b for a, b in zip(counts, found)]
        missing = [r["find"] for r, n in zip(declared_rules, counts) if n == 0]
        assert missing == [], (template, lang, missing)


def test_a_reference_to_another_document_links_its_slot():
    html = _html("/privacy/example-rec-2/0.2/it")
    assert '<a href="/sub-processors">elenco dei sub-responsabili della piattaforma</a>' in html
    assert '<a href="/terms/example-rec-2">condizioni d\'uso</a>' in html
    terms = _html("/terms/example-rec-2/0.2/en")
    assert '<a href="/privacy/example-rec-2">privacy notice</a>' in terms
    assert '<a href="/statute/example-rec-2">statute</a>' not in terms  # example-rec-2 has no statute slot


def test_a_slot_the_owner_does_not_have_is_left_unlinked():
    html = _html("/privacy/example-rec-2/0.2/it")
    assert "informativa generale di Example REC 2 per i soci" in html
    assert "member-privacy-notice" not in html and "regulations" not in html


def test_a_reference_within_the_text_links_its_heading():
    for path in ("/privacy/example-rec-2/0.2/it", "/privacy/example-rec-2/0.2/en",
                 "/terms/example-rec-2/0.2/it", "/terms/example-rec-2/0.2/en",
                 "/data-sharing-notice/example-rec/0.2/it", "/data-sharing-notice/example-rec/0.2/en"):
        html = _html(path)
        targets = set(re.findall(r'href="#([^"]+)"', html))
        assert targets, path
        assert targets <= set(re.findall(r'id="([^"]+)"', html)), (path, targets)
    terms = _html("/terms/example-rec-2/0.2/it")
    assert '<a href="#sec-15">art. 15</a>' in terms
    assert 'dagli artt. <a href="#sec-8">8</a> e <a href="#sec-12">12</a>.' in terms
    assert "art. 1411 c.c." in terms and 'href="#sec-1411"' not in terms
    privacy = _html("/privacy/example-rec-2/0.2/en")
    assert '<a href="#sec-2-1">§2.1</a>' in privacy and '<a href="#sec-4">§4</a>' in privacy


def test_the_agreement_links_its_clauses_annexes_and_the_notice():
    catalogue = _html("/example-rec-2/data-processing-agreement/0.2/en")
    assert '<a href="#annex-3">Annex 3</a>' in catalogue
    assert '<a href="/privacy/example-rec-2#sec-6">privacy notice for the platform, §6</a>' in catalogue


def test_a_draft_links_within_the_draft():
    html = _html("/privacy/example-rec-2/0.2/it", _site("/draft/abc"))
    assert '<a href="/draft/abc/sub-processors">' in html


def test_the_links_leave_the_text_unchanged():
    result = SITE.view(Request("/privacy/example-rec-2/0.2/it"))
    assert "<a " not in result.view["markdown"]
    assert result.view["markdown"] in SITE.text(result.view["text"])


def test_a_published_edition_links_as_its_draft_did(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(EXAMPLE, data)
    result = legal_build.build(data, None)
    legal_build.publish([f for f in result.files if f.published_at is None], data, "2026-01-01T00:00:00Z",
                        legal_build.provenance("v1.0.0", None, {}))
    _, files, problems = legal_build.render(data, "final", label={"release": "v1.0.0"})
    assert problems == []
    html = _html("/privacy/example-rec-2/0.2/it", Site({f.path: f.text for f in files}))
    assert '<a href="/sub-processors">elenco dei sub-responsabili della piattaforma</a>' in html


def test_the_platform_notice_links_the_research_notice_where_it_is_published(tmp_path):
    assert '<a href="/research-notice">Informativa al trattamento dei dati personali — Progetto EU EXAMPLE</a>' in \
        _html("/privacy/example-rec-2/0.2/it")
    assert '<a href="/research-notice">Notice on the processing of personal data — EU EXAMPLE Project</a>' in \
        _html("/privacy/example-rec-2/0.2/en")
    data = tmp_path / "data"
    shutil.copytree(EXAMPLE, data)
    register = yaml.safe_load((data / "register.yaml").read_text())
    del register["platform_roles"]["research_notice"]
    (data / "register.yaml").write_text(yaml.safe_dump(register, allow_unicode=True, sort_keys=False))
    texts = {(f.entry_id, f.lang): f.text for f in legal_build.build(data, None).files if f.lang}
    assert "Progetto EU" not in texts[("example-rec-2/app-privacy-notice", "it")]
    assert "EU EXAMPLE Project" not in texts[("example-rec-2/app-privacy-notice", "en")]


def test_a_community_without_a_dpo_names_none(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(EXAMPLE, data)
    identity_path = data / "recs" / "example-rec" / "identity.yaml"
    identity = yaml.safe_load(identity_path.read_text())
    dpo = identity.pop("dpo")
    identity_path.write_text(yaml.safe_dump(identity, allow_unicode=True, sort_keys=False))
    register_path = data / "register.yaml"  # 0.1, as published, still names one
    register = yaml.safe_load(register_path.read_text())
    for entry in register["documents"]:
        if entry["id"] == "example-rec/app-privacy-notice":
            entry["version"] = "0.2"
    register_path.write_text(yaml.safe_dump(register, allow_unicode=True, sort_keys=False))
    result = legal_build.build(data, None)
    assert result.problems == []
    texts = {(f.entry_id, f.lang): f.text for f in result.files if f.lang}
    for lang, label in (("it", "Responsabile della protezione dei dati:"), ("en", "Data protection officer:")):
        assert label not in texts[("example-rec/app-privacy-notice", lang)]
    for lang in ("it", "en"):
        sharing = " ".join(texts[("example-rec/data-sharing-privacy-notice", lang)].split())
        assert dpo not in sharing and "Example DSO dpo@dso.example.org; Example Platform dpo@platform.example.org." in sharing
