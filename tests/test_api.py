"""The legal host's decisions over the example deployment: resolution, scoping, the old paths.

Two hosts serve `data/example/`: a sample one (the full catalogue, drafts allowed) and a
final one (every final edition published, scoped). Asked through ``/api/view``, the JSON of
what a page shows.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from celine.legal import build as legal_build
from celine.legal.app import create_app

LEGAL = Path(__file__).resolve().parent.parent
EXAMPLE = LEGAL / "data" / "example"
REVISION = "0123456789abcdef0123456789abcdef01234567"
RELEASE = "v1.0.0"
DRAFT = f"/draft/{REVISION}"


def _env(mode: str, data, **extra: str) -> dict:
    """What a deployment sets: the data, and the draft's commit (``sample``: the draft is what
    the test reads) or the release it pins (``final``: the stable site)."""
    names = {"LEGAL_REVISION": REVISION} if mode == "sample" else {"LEGAL_RELEASE": RELEASE}
    return {"LEGAL_DATA": str(data), **names, **extra}


def _publish(files, data) -> None:
    made = legal_build.provenance(RELEASE, None, {})
    legal_build.publish([f for f in files if f.published_at is None], data, "2026-01-01T00:00:00Z", made)
HOST = "legal.example.org"

# What only one community's text or link carries ("Example REC" is inside the second
# one's legal name, so names are not enough).
MARKS = {
    "example-rec": ("00000000003", "info@rec.example.org", "/example-rec", "rec.example.org"),
    "example-rec-2": ("00000000005", "info@rec2.example.org", "/example-rec-2", "rec2.example.org"),
}


def _named(text: str) -> set[str]:
    # "/example-rec" is a prefix of "/example-rec-2": look for it on its own.
    text_without_second = text.replace("/example-rec-2", "")
    named = {key for key, marks in MARKS.items() if any(m in text for m in marks[:2] + marks[3:])}
    if "/example-rec-2" in text:
        named.add("example-rec-2")
    if "/example-rec" in text_without_second:
        named.add("example-rec")
    return named


def _host(tmp: Path, mode: str) -> TestClient:
    data = tmp / "data"
    shutil.copytree(EXAMPLE, data)
    if mode == "final":
        published = legal_build.build(data)
        assert published.problems == []
        _publish(published.files, data)
    base = f"http://testserver{DRAFT}" if mode == "sample" else "http://testserver"
    return TestClient(create_app(_env(mode, data)), base_url=base, follow_redirects=False)


@pytest.fixture(scope="module")
def final(tmp_path_factory):
    return _host(tmp_path_factory.mktemp("final"), "final")


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return _host(tmp_path_factory.mktemp("sample"), "sample")


def _view(client, path, referer=None, accept_language=None, **query):
    headers = {"x-forwarded-host": HOST}
    if referer:
        headers["referer"] = referer
    if accept_language:
        headers["accept-language"] = accept_language
    return client.get("/api/view", params={"path": path, **query}, headers=headers)


# ── the landing page ──────────────────────────────────────────────────────

def test_the_landing_page_shows_the_platform_documents_only(final):
    view = _view(final, "/").json()
    assert view["view"] == "landing" and view["organisation"] is None
    assert {d["slot"] for d in view["platform"]} == {"sub-processors", "research-notice", "participation-agreement"}
    assert _named(json.dumps(view)) == set()
    assert view["catalogue"] is False


def test_the_landing_page_adds_the_organisation_the_query_names(final):
    view = _view(final, "/", **{"for": "example-rec"}).json()
    assert view["organisation"]["organisation"]["owner"] == "example-rec"
    assert view["resolved_by"] == "query"
    assert _named(json.dumps(view)) == {"example-rec"}


def test_the_landing_page_adds_the_organisation_whose_site_linked_it(final):
    view = _view(final, "/", referer="https://www.rec2.example.org/soci/").json()
    assert view["organisation"]["organisation"]["owner"] == "example-rec-2"
    assert view["resolved_by"] == "referer"


# ── a slot with no organisation in the path ───────────────────────────────

@pytest.mark.parametrize("how", [
    {"query": {"for": "example-rec"}},
    {"query": {"org": "example-rec"}},
    {"referer": "https://rec.example.org/privacy"},
    {"referer": f"https://{HOST}/example-rec"},
    {"referer": f"https://{HOST}/privacy/example-rec/0.1/it"},
])
def test_a_slot_redirects_to_the_organisation_it_resolves(final, how):
    response = _view(final, "/terms", referer=how.get("referer"), **how.get("query", {}))
    assert response.json() == {"mode": "final", "status": 302, "redirect": "/terms/example-rec"}


def test_a_redirect_keeps_the_language_asked_for(final):
    assert _view(final, "/terms", lang="en", **{"for": "example-rec-2"}).json()["redirect"] == "/terms/example-rec-2?lang=en"


@pytest.mark.parametrize("referer", [None, "https://elsewhere.example.net/", f"https://{HOST}/"])
def test_a_slot_with_no_organisation_names_none(final, referer):
    view = _view(final, "/privacy", referer=referer).json()
    assert view == {"mode": "final", "status": 200, "view": "unscoped", "slot": "privacy", "resolved_by": None}


def test_an_unknown_organisation_resolves_to_none(final):
    assert _view(final, "/privacy", **{"for": "no-such-community"}).json()["view"] == "unscoped"


def test_a_platform_slot_is_the_platforms_document(final):
    view = _view(final, "/sub-processors").json()
    assert view["view"] == "document" and view["organisation"]["owner"] == "platform"
    assert view["url"] == "/sub-processors"


def test_an_unknown_slot_is_a_404(final):
    assert _view(final, "/no-such-slot").status_code == 404


# ── documents ─────────────────────────────────────────────────────────────

def test_a_document_carries_its_text_and_the_hash_of_it(final):
    view = _view(final, "/terms/example-rec").json()
    assert view["view"] == "document" and view["version"] == "0.1" and view["lang"] == "it"
    assert view["status"] == 200 and view["document_status"] == "final"
    text = final.get(view["text"])
    assert text.status_code == 200 and text.headers["content-type"].startswith("text/markdown")
    assert hashlib.sha256(text.content).hexdigest() == view["sha256"]
    assert view["markdown"] in text.text and not view["markdown"].startswith("---")
    assert view["html"].startswith("<h1>") and "<table>" in _view(final, "/sub-processors").json()["html"]
    assert _named(json.dumps(view)) == {"example-rec"}


def test_the_language_follows_the_query_then_the_browser(final):
    assert _view(final, "/terms/example-rec", accept_language="en-GB,en;q=0.9,it;q=0.5").json()["lang"] == "en"
    assert _view(final, "/terms/example-rec", accept_language="de-DE,de;q=0.9").json()["lang"] == "it"
    assert _view(final, "/terms/example-rec", accept_language="en", lang="it").json()["lang"] == "it"


def test_a_pinned_version_and_language(final):
    view = _view(final, "/terms/example-rec/0.1/en").json()
    assert (view["version"], view["lang"], view["is_current"]) == ("0.1", "en", True)
    assert [lang["url"] for lang in view["langs"]] == ["/terms/example-rec/0.1/it", "/terms/example-rec/0.1/en"]
    assert _view(final, "/terms/example-rec/0.1/de").status_code == 404
    assert _view(final, "/terms/example-rec/9.9").status_code == 404


def test_slots_take_either_spelling(final):
    assert _view(final, "/data-sharing-notice/example-rec").json()["slot"] == "data-sharing-notice"
    assert _view(final, "/data_sharing_notice/example-rec").json()["slot"] == "data-sharing-notice"


def test_a_slot_the_organisation_does_not_have_is_a_404(final):
    assert _view(final, "/data-sharing-notice/example-rec-2").status_code == 404


def test_an_external_document_redirects_to_its_owner(final):
    assert _view(final, "/statute/example-rec").json() == {
        "mode": "final", "status": 302, "redirect": "https://rec.example.org/statute.pdf"}


def test_an_organisation_overview_lists_its_documents_and_the_platforms(final):
    view = _view(final, "/example-rec-2").json()
    assert view["view"] == "organisation"
    assert {d["url"] for d in view["documents"]} == {"/privacy/example-rec-2", "/terms/example-rec-2"}
    assert {d["url"] for d in view["platform"]} == {"/sub-processors", "/research-notice", "/participation-agreement"}
    assert _named(json.dumps(view)) == {"example-rec-2"}


def test_no_view_of_one_organisation_names_another(final):
    for org in MARKS:
        for path in [f"/{org}", f"/terms/{org}", f"/privacy/{org}", "/", "/terms", "/sub-processors"]:
            response = _view(final, path, **{"for": org})
            if response.json().get("redirect"):
                response = _view(final, response.json()["redirect"].split("?")[0])
            assert _named(json.dumps(response.json())) <= {org}, (org, path)


# ── the paths the earlier static host served ──────────────────────────────────────

@pytest.mark.parametrize("old, new", [
    ("/example-rec/terms/", "/terms/example-rec"),
    ("/example-rec/terms/en/", "/terms/example-rec/0.1/en"),
    ("/example-rec/data_sharing_notice/", "/data-sharing-notice/example-rec"),
    ("/example-rec/terms-of-use/0.1/it/", "/terms/example-rec/0.1/it"),
    ("/example-rec/terms-of-use/", "/terms/example-rec"),
    ("/platform/sub_processors/", "/sub-processors"),
    ("/platform-not-a-slot/", None),
    ("/platform/sub-processors/0.1/it/", "/sub-processors/platform/0.1/it"),
    ("/platform/sub_processors/en/", "/sub-processors/platform/0.1/en"),
    ("/dataspace/participation-agreement/0.2/en/", "/participation-agreement/platform/0.2/en"),
    ("/platform", "/"),
    ("/terms/platform", None),
    ("/sub-processors/platform", "/sub-processors"),
])
def test_the_old_paths_redirect_for_good(final, old, new):
    response = _view(final, old)
    if new is None:
        assert response.status_code == 404
    else:
        assert response.json() == {"mode": "final", "status": 301, "redirect": new}


def test_the_files_applications_read_keep_their_paths(final):
    current = final.get("/example-rec/current.json")
    assert current.status_code == 200 and current.json()["owner"] == "example-rec"
    assert final.get("/api/orgs/example-rec/current").json() == current.json()
    assert final.get("/example-rec/history.json").json() == final.get("/api/orgs/example-rec/history").json()
    assert final.get("/platform/current.json").json()["owner"] == "platform"
    assert final.get("/example-rec/consent-texts/1.0/consent-texts.yaml").status_code == 200


def test_only_the_files_applications_read_are_served(final):
    assert final.get("/example-rec/terms-of-use/0.1/it/index.html").status_code == 404
    assert final.get("/example-rec/about.json").status_code == 404
    assert final.get("/%2e%2e/%2e%2e/pyproject.toml.json").status_code == 404
    assert final.get("/api/orgs/no-such-community").status_code == 404


# ── what only a sample host serves ────────────────────────────────────────

def test_a_deployed_host_has_no_catalogue(final):
    assert _view(final, "/catalogue").status_code == 404
    assert final.get("/api/catalogue").status_code == 404
    assert final.get("/index.json").status_code == 404


def test_a_deployed_host_serves_no_signed_agreement(final):
    assert _view(final, "/example-rec/data-processing-agreement/0.1/en/").status_code == 404
    assert final.get("/example-rec/data-processing-agreement/0.1/en.md").status_code == 404


def test_the_sample_catalogue_lists_every_document_and_opens_the_signed_ones(sample):
    pages = _view(sample, "/catalogue").json()["pages"]
    assert {"example-rec/terms-of-use", "example-rec-2/terms-of-use", "example-dso/data-processing-agreement"} <= {
        p["id"] for p in pages}
    view = _view(sample, "/example-dso/data-processing-agreement/0.1/en/").json()
    assert view["view"] == "document" and view["slot"] is None and view["markdown"]
    assert _view(sample, "/").json()["catalogue"] is True


def test_the_health_check(final):
    assert final.get("/healthz").text == "ok\n"
