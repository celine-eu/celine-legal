"""The legal host as people and applications reach it: its pages, its two modes, and what
stops it from starting.

The example deployment, served as a sample (drafts, the full catalogue) and as final
(every edition final and published).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from celine.legal import build as legal_build
from celine.legal.app import create_app
from celine.legal.pages import Pages

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
SAMPLE_WORDS = ("CAMPIONE", "SAMPLE")


def _data(tmp: Path, publish: bool = False, drafts: tuple[str, ...] = ()) -> Path:
    data = tmp / "data"
    shutil.copytree(EXAMPLE, data)
    if drafts:
        register = yaml.safe_load((data / "register.yaml").read_text())
        for entry in register["documents"]:
            if entry["id"] in drafts:
                entry["status"] = "draft"
        (data / "register.yaml").write_text(yaml.safe_dump(register))
    if publish:
        result = legal_build.build(data, None)
        assert result.problems == []
        _publish(result.files, data)
    return data


def _client(data: Path, mode: str, **env: str) -> TestClient:
    base = f"http://testserver{DRAFT}" if mode == "sample" else "http://testserver"
    return TestClient(create_app(_env(mode, data, **env)), base_url=base, follow_redirects=False)


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return _client(_data(tmp_path_factory.mktemp("sample"), drafts=("example-rec/terms-of-use",)), "sample")


@pytest.fixture(scope="module")
def final(tmp_path_factory):
    return _client(_data(tmp_path_factory.mktemp("final"), publish=True), "final")


PAGES = ["/", "/catalogue", "/terms/example-rec", "/privacy", "/example-rec", "/sub-processors", "/no-such-page"]


# ── what stops the host ───────────────────────────────────────────────────


def test_the_root_serves_releases_and_the_draft_only_its_prefix(tmp_path):
    """One host, two sites: the stable one at the root, the draft under its commit."""
    data = _data(tmp_path, publish=True, drafts=("example-rec/terms-of-use",))
    host = TestClient(create_app({"LEGAL_DATA": str(data), "LEGAL_REVISION": REVISION}), follow_redirects=False)
    root = host.get("/example-rec/current.json").json()
    assert root["valid"] is True and "privacy" in root["slots"] and root["pending"] == ["terms"]
    assert host.get("/privacy/example-rec").headers["x-legal-mode"] == "final"
    draft = host.get(f"{DRAFT}/example-rec/current.json").json()
    assert draft["valid"] is False and draft["slots"]["terms"]["status"] == "draft"
    assert host.get(f"{DRAFT}/terms/example-rec").headers["x-legal-mode"] == "sample"


def test_no_data_stops_the_host(tmp_path):
    with pytest.raises(SystemExit, match="LEGAL_DATA"):
        create_app({})
    with pytest.raises(SystemExit, match="no register.yaml"):
        create_app(_env("sample", tmp_path))


def test_the_root_never_serves_a_draft(sample):
    """Nothing is published in this fixture: the root has no text, only "not yet available"."""
    root = TestClient(sample.app, follow_redirects=False)
    page = root.get("/terms/example-rec")
    assert page.status_code == 200 and page.headers["x-legal-mode"] == "final"
    assert "Document not yet available" in root.get("/terms/example-rec?lang=en").text
    assert 'data-mode="sample"' not in page.text and "<article" not in page.text
    current = root.get("/example-rec/current.json").json()
    assert "terms" not in current["slots"] and "terms" in current["pending"]
    assert root.get("/example-rec/terms-of-use/0.1/en.md").status_code == 404
    assert root.get("/example-rec/terms/").headers["location"] == "/terms/example-rec"
    assert "No document has been published yet." in root.get("/?lang=en").text


def test_a_final_host_never_starts_with_an_edited_published_text(tmp_path):
    data = _data(tmp_path, publish=True)
    frozen = data / "editions/platform/sub-processors/0.1/en.md"
    frozen.write_text(frozen.read_text().replace("Example", "Exemplary", 1))
    with pytest.raises(SystemExit, match="recorded at publication"):
        create_app(_env("final", data))


def test_a_draft_that_does_not_render_says_so_under_its_prefix_only(tmp_path):
    data = _data(tmp_path, publish=True)
    host = TestClient(create_app(_env("sample", data, LEGAL_FEATURE_SMS="false")), follow_redirects=False)
    broken = host.get(f"{DRAFT}/")
    assert broken.status_code == 503 and "LEGAL_FEATURE_SMS: no such feature" in broken.text
    assert host.get("/terms/example-rec").status_code == 200  # the stable site keeps serving
    host = TestClient(create_app(_env("sample", data, LEGAL_FEATURE_AI_ASSISTANT="maybe")), follow_redirects=False)
    assert "not true or false" in host.get(f"{DRAFT}/terms/example-rec").text


# ── telling a sample from the texts in force ──────────────────────────────


@pytest.mark.parametrize("path", PAGES)
def test_every_sample_page_says_it_is_not_valid(sample, path):
    response = sample.get(path)
    assert response.headers["x-legal-mode"] == "sample"
    if response.status_code < 300 or response.status_code == 404:
        assert 'data-mode="sample"' in response.text
        assert any(word in response.text for word in SAMPLE_WORDS)


@pytest.mark.parametrize("path", [p for p in PAGES if p != "/catalogue"])
def test_no_final_page_carries_the_sample_banner(final, path):
    response = final.get(path)
    assert response.headers["x-legal-mode"] == "final"
    assert 'data-mode="sample"' not in response.text


def test_what_applications_read_says_whether_it_binds(sample, final):
    assert {k: sample.get("/example-rec/current.json").json()[k] for k in ("mode", "valid")} == {
        "mode": "sample", "valid": False}
    assert {k: final.get("/example-rec/current.json").json()[k] for k in ("mode", "valid")} == {
        "mode": "final", "valid": True}
    assert final.get("/platform/history.json").json()["mode"] == "final"


def test_the_features_the_texts_describe_are_published(tmp_path):
    client = _client(_data(tmp_path), "sample", LEGAL_FEATURE_SMS_VERIFICATION="false")
    features = client.get("/platform/current.json").json()["features"]
    assert features["sms_verification"] is False and features["ai_assistant"] is True


# ── the pages ─────────────────────────────────────────────────────────────


def test_a_document_page_shows_its_text_and_the_hash_of_it(final):
    page = final.get("/terms/example-rec/0.1/en")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert '<html lang="en">' in page.text and "<article" in page.text
    text = final.get("/example-rec/terms-of-use/0.1/en.md")
    assert hashlib.sha256(text.content).hexdigest() in page.text
    assert "published on 1 January 2026" in page.text


def test_a_page_follows_the_language_of_its_document(final):
    assert '<html lang="it">' in final.get("/terms/example-rec").text
    assert '<html lang="en">' in final.get("/terms/example-rec", headers={"accept-language": "en"}).text
    assert "Documenti legali" in final.get("/").text
    assert "Legal documents" in final.get("/?lang=en").text


def test_redirects_are_real_redirects(final):
    response = final.get("/terms", params={"for": "example-rec"})
    assert response.status_code == 302 and response.headers["location"] == "/terms/example-rec"
    assert final.get("/example-rec/terms/").headers["location"] == "/terms/example-rec"
    assert final.get("/example-rec/terms/").status_code == 301


def test_a_missing_page_is_a_404_page(final):
    response = final.get("/no-such-page")
    assert response.status_code == 404 and "Pagina non trovata" in response.text


def test_a_final_landing_lists_the_platform_documents_only(final):
    page = final.get("/").text
    assert 'href="/sub-processors"' in page and 'href="/participation-agreement"' in page
    assert "Example REC" not in page and "/catalogue" not in page


def test_a_final_slot_page_names_no_community(final):
    page = final.get("/privacy").text
    assert "Example REC" not in page and "example-rec" not in page


def test_a_sample_lists_every_document_for_review_signed_agreements_included(sample):
    page = sample.get("/catalogue").text
    assert "/example-dso/data-processing-agreement/0.1/en/" in page and "for signature" in sample.get(
        "/catalogue?lang=en").text
    assert f'href="{DRAFT}/catalogue"' in sample.get("/").text
    assert sample.get("/example-dso/data-processing-agreement/0.1/en/").status_code == 200


def test_a_slot_whose_owner_publishes_nothing_still_answers(tmp_path):
    data = _data(tmp_path)
    register = yaml.safe_load((data / "register.yaml").read_text())
    next(e for e in register["documents"] if e["id"] == "example-rec/statute")["publish"] = "[•]"
    (data / "register.yaml").write_text(yaml.safe_dump(register))
    page = _client(data, "sample").get("/statute/example-rec")
    assert page.status_code == 200
    assert "non è pubblicato online" in page.text and "info@rec.example.org" in page.text


def test_a_page_and_a_file_answer_head(final):
    assert final.head("/terms/example-rec").status_code == 200
    assert final.head("/example-rec/current.json").headers["x-legal-mode"] == "final"


def test_pages_run_no_script_and_are_not_cached(final):
    response = final.get("/terms/example-rec")
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store" and "<script" not in response.text
    assert response.headers["x-robots-tag"] == "noindex"


def test_a_restyled_page_keeps_its_hash(tmp_path, final):
    """The hash is the text's: a change to the page templates changes no sha256."""
    templates = tmp_path / "templates"
    shutil.copytree(legal_build.TEMPLATES, templates)
    base = templates / "page" / "base.html.j2"
    base.write_text(base.read_text().replace("<body>", "<body data-restyled>"))
    view = final.get("/api/view", params={"path": "/terms/example-rec"}).json()
    assert "data-restyled" in Pages("final", templates).view(view, "it")
    assert "data-restyled" not in final.get("/terms/example-rec").text

    def current(templates: Path) -> str:
        files, _ = legal_build.site(legal_build.build(EXAMPLE, None, templates), EXAMPLE, "sample")
        return next(f.text for f in files if f.path == "example-rec/current.json")

    assert current(templates) == current(legal_build.TEMPLATES)


# ── drafts at their commit, releases by version ───────────────────────────


@pytest.mark.parametrize("env, message", [
    ({"LEGAL_REVISION": "0123abc"}, "40-hex"),
    ({"LEGAL_REVISION": "v1.0.0"}, "40-hex"),
    ({"LEGAL_RELEASE": "1.0.0"}, "vX.Y.Z"),
    ({"LEGAL_RELEASE": "v1.0"}, "vX.Y.Z"),
])
def test_a_draft_needs_its_commit_and_a_release_its_version(env, message):
    with pytest.raises(SystemExit, match=message):
        create_app({"LEGAL_DATA": str(EXAMPLE), **env})


def test_a_final_host_serves_the_newest_published_release_only(tmp_path):
    data = _data(tmp_path, publish=True)
    with pytest.raises(SystemExit, match="newest release in the data's editions is v1.0.0"):
        create_app(_env("final", data, LEGAL_RELEASE="v1.1.0"))
    assert _client(data, "final").get("/platform/current.json").json()["release"] == RELEASE


def test_a_draft_answers_only_under_its_commit(sample):
    outside = TestClient(sample.app, follow_redirects=False)
    for path in ["/draft", "/draft/", f"/draft/{'f' * 40}/", f"/draft/{REVISION[:8]}/", f"/draft/{REVISION}x/"]:
        response = outside.get(path)
        assert response.status_code == 404 and response.text == "Not Found", path
    assert outside.get("/catalogue").status_code == 404  # the review catalogue is the draft's
    assert outside.get(f"{DRAFT}/catalogue").status_code == 200
    assert outside.get("/healthz").status_code == 200


def test_without_a_revision_there_is_no_draft(final):
    assert final.get(f"{DRAFT}/").status_code == 404


def test_a_draft_keeps_its_readers_inside_it(sample):
    response = sample.get("/terms", params={"for": "example-rec"})
    assert response.headers["location"] == f"{DRAFT}/terms/example-rec"
    page = sample.get("/example-rec").text
    assert f'href="{DRAFT}/terms/example-rec"' in page and 'href="/terms' not in page
    referer = f"http://testserver{DRAFT}/privacy/example-rec"
    assert sample.get("/terms", headers={"referer": referer}).headers["location"] == f"{DRAFT}/terms/example-rec"
    assert sample.get("/example-rec/current.json").json()["revision"] == REVISION


def test_a_draft_page_shows_the_fingerprint_to_approve(sample):
    page = sample.get("/terms/example-rec/0.1/en").text  # a draft in this fixture
    assert "data-approval" in page
    approval = sample.get("/example-rec/current.json").json()["slots"]["terms"]["approval_sha256"]["en"]
    assert approval in page and approval != sample.get("/example-rec/current.json").json()["slots"]["terms"]["sha256"]["en"]
    assert "data-approval" not in sample.get("/privacy/example-rec/0.1/en").text  # final: nothing to approve


def test_every_page_names_what_it_serves(sample, final):
    assert f"<span data-revision>{REVISION[:8]}</span>" in sample.get("/").text
    assert f"Release {RELEASE}" in final.get("/?lang=en").text and "data-release" not in sample.get("/").text


def test_the_root_does_not_announce_what_cannot_exist_here(tmp_path):
    host = TestClient(create_app({"LEGAL_DATA": str(_data(tmp_path)), "LEGAL_FEATURE_DSO_DATA_EXCHANGE": "false"}))
    assert "data_sharing_notice" not in host.get("/example-rec/current.json").json()["pending"]
    assert host.get("/data-sharing-notice/example-rec").status_code == 404
