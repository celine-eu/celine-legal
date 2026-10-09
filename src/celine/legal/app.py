"""The legal host: one generic image, a deployment's data mounted, served from memory.

    LEGAL_DATA=data/example [LEGAL_REVISION=<40-hex commit>] \
        uvicorn --factory celine.legal.app:create_app

It serves two sites that never meet:

- **the stable site, at the root**: the published editions only, as they were frozen
  (``legal-build --publish``). This is what applications link and record acceptances
  against. A slot with no stable version yet answers "not yet available", and is not in
  ``current.json``: an application never links a draft.
- **the draft, at ``/draft/<revision>/``**, when ``LEGAL_REVISION`` is set: the data as it is
  now, rendered for the parties to review, marked on every page as not valid. Its link is
  the access, and names exactly what was reviewed. Nothing outside that prefix links to it,
  and a draft that does not render answers so under its own prefix only: the stable site
  keeps serving.

Configuration, all from the environment:

    LEGAL_DATA          required: the deployment's data directory
    LEGAL_REVISION      the full 40-hex commit of the data: serves the draft at /draft/<revision>/
    LEGAL_RELEASE       vX.Y.Z: pins the release the stable site must be (the newest published)
    LEGAL_OFFERS        the sharing offers; default ``$LEGAL_DATA/sharing-offers.yaml``
    LEGAL_TEMPLATES     the document templates; default the packaged ones
    LEGAL_FEATURE_<X>   overrides one of the data's ``features`` in the draft (``features.py``);
                        a published edition keeps the features it was published with

The stable site stops the process if a frozen edition was edited after publication.

People read pages (``/``, ``/{slot}/{org}``, …; ``site.py`` decides, ``pages.py`` renders).
Applications read files by path: ``/{owner}/current.json``, ``/{owner}/history.json``, every
text ``/{id}/{version}/{lang}.md`` and the consent texts. ``/api/view?path=`` answers what a
page shows, as JSON. Every response carries ``X-Legal-Mode`` (``final`` for the stable
site, ``sample`` for a draft).
"""

from __future__ import annotations

import html
import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

from . import build as legal_build
from .pages import LANGS, Pages, pick_lang
from .site import Request as ViewRequest
from .site import Site

log = logging.getLogger("celine.legal")

_MEDIA = {".json": "application/json", ".md": "text/markdown; charset=utf-8", ".yaml": "text/yaml; charset=utf-8"}
_PAGE = {"Cache-Control": "no-store", "Vary": "Referer, Accept-Language"}
# The pages carry no script; a document's HTML is the deployment's own text.
_CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'")
REVISION = re.compile(r"\A[0-9a-f]{40}\Z")
DRAFT = "/draft"


class ConfigError(SystemExit):
    pass


def _data(environ: Mapping[str, str]) -> Path:
    if not environ.get("LEGAL_DATA"):
        raise ConfigError("LEGAL_DATA is not set: the directory holding register.yaml and parties.yaml")
    data = Path(environ["LEGAL_DATA"]).resolve()
    if not (data / "register.yaml").is_file():
        raise ConfigError(f"LEGAL_DATA={data}: no register.yaml there")
    return data


def load_stable(environ: Mapping[str, str]) -> Site:
    """The stable site: the published editions. Stops if one was edited after publication."""
    data = _data(environ)
    releases = legal_build.releases(data)
    pinned = environ.get("LEGAL_RELEASE")
    if pinned:
        if not legal_build.RELEASE.match(pinned):
            raise ConfigError(f"LEGAL_RELEASE={pinned!r}: a stable release is vX.Y.Z")
        if not releases or releases[-1] != pinned:
            raise ConfigError(f"LEGAL_RELEASE={pinned}: the newest release in the data's editions is "
                              f"{releases[-1] if releases else 'none'}; publish with `legal-build --publish "
                              f"--release {pinned}` first")
    names = {"release": releases[-1]} if releases else {}
    templates = Path(environ["LEGAL_TEMPLATES"]).resolve() if environ.get("LEGAL_TEMPLATES") else legal_build.TEMPLATES
    result, files, problems = legal_build.render(data, legal_build.FINAL, templates=templates, environ=environ,
                                                 label=names)
    if problems:
        raise ConfigError("the published editions cannot be served:\n" + "\n".join(f"  !! {p}" for p in problems))
    site = Site({f.path: f.text for f in files})
    site.label = names
    pending = sorted({f"{o.key}/{s}" for o in site.owners.values() for s in o.pending})
    log.warning("legal host: stable site %s, %d published texts%s", names.get("release", "(nothing published yet)"),
                len(result.files), f"; not yet available: {', '.join(pending)}" if pending else "")
    return site


def load_draft(environ: Mapping[str, str]) -> tuple[Site | None, list[str]]:
    """The draft at /draft/<revision>/, or None when no revision is set. Problems never stop the host."""
    revision = environ.get("LEGAL_REVISION")
    if not revision:
        return None, []
    if not REVISION.match(revision):
        raise ConfigError(f"LEGAL_REVISION={revision!r}: a draft is named by the full 40-hex commit of the "
                          "deployment's data (`git rev-parse HEAD`)")
    data = _data(environ)
    offers = Path(environ["LEGAL_OFFERS"]).resolve() if environ.get("LEGAL_OFFERS") else None
    templates = Path(environ["LEGAL_TEMPLATES"]).resolve() if environ.get("LEGAL_TEMPLATES") else legal_build.TEMPLATES
    names = {"revision": revision}
    result, files, problems = legal_build.render(data, legal_build.SAMPLE, offers, templates, environ, names)
    if problems:
        log.error("legal host: the draft %s… does not render; only its own address says so:\n%s",
                  revision[:8], "\n".join(f"  !! {p}" for p in problems))
        return None, problems
    site = Site({f.path: f.text for f in files})
    site.base, site.label = f"{DRAFT}/{revision}", names
    for entry_id, feature in sorted(result.omitted.items()):
        log.warning("legal host: draft: %s left out, %s is off", entry_id, feature)
    log.warning("legal host: draft %s… at %s/, %d documents; features %s", revision[:8], DRAFT, len(result.files),
                ", ".join(f"{k}={'on' if v else 'off'}" for k, v in sorted(result.features.items())))
    return site, []


def site_app(site: Site, mode: str) -> FastAPI:
    """One site's pages and files. ``site.base`` is the prefix its readers reach it under."""
    base = site.base
    pages = Pages(mode, base=base, label=site.label)
    app = FastAPI(title="celine-legal", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Legal-Mode"] = mode
        response.headers["X-Robots-Tag"] = "noindex"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Content-Security-Policy"] = _CSP
        return response

    def _referer(value: str | None) -> str | None:
        """A Referer from inside the draft, as the site knows its own paths (without the prefix)."""
        if not value or not base:
            return value
        parts = urlsplit(value)
        if parts.path == base or parts.path.startswith(base + "/"):
            return urlunsplit(parts._replace(path=parts.path[len(base):] or "/"))
        return value

    def _owner(key: str):
        owner = site.organisation(key) or (site.platform if key == "platform" else None)
        if owner is None:
            raise HTTPException(404)
        return owner

    def _view(request: Request, path: str):
        query = {k: v for k, v in request.query_params.items() if k != "path"}
        return site.view(ViewRequest(
            path=path,
            query=query,
            referer=_referer(request.headers.get("referer")),
            host=request.headers.get("x-forwarded-host") or request.headers.get("host"),
            accept_language=request.headers.get("accept-language"),
        ))

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok\n"

    @app.get("/api/view")
    def view(request: Request, path: str = "/") -> JSONResponse:
        result = _view(request, path)
        if result.status == 404:
            raise HTTPException(404)
        return JSONResponse({"mode": mode, **result.as_json()}, headers=_PAGE)

    @app.get("/api/platform")
    def platform() -> dict:
        owner = _owner("platform")
        return {"organisation": owner.about, "slots": owner.slots}

    @app.get("/api/orgs/{key}")
    def organisation(key: str) -> dict:
        owner = _owner(key)
        return {"organisation": owner.about, "slots": owner.slots}

    @app.get("/api/orgs/{key}/current")
    def current(key: str) -> dict:
        return _owner(key).current

    @app.get("/api/orgs/{key}/history")
    def history(key: str) -> dict:
        return _owner(key).history

    @app.get("/api/catalogue")
    def catalogue() -> dict:
        if site.catalogue is None:
            raise HTTPException(404)
        return site.catalogue

    @app.api_route("/{path:path}", methods=["GET", "HEAD"])
    def page_or_file(request: Request, path: str) -> Response:
        suffix = Path(path).suffix
        if suffix in _MEDIA:
            # The files applications read by path: JSON, rendered texts, consent texts.
            name = Path(path).name
            if name.startswith(".") or name == "about.json":
                raise HTTPException(404)
            text = site.text(path)
            if text is None:
                raise HTTPException(404)
            return Response(text.encode("utf-8"), media_type=_MEDIA[suffix])
        lang = pick_lang(request.query_params.get("lang"), request.headers.get("accept-language"))
        result = _view(request, "/" + path)
        if result.redirect:
            target = base + result.redirect if result.redirect.startswith("/") else result.redirect
            return RedirectResponse(target, status_code=result.status, headers=_PAGE)
        if result.status == 404 or result.view is None:
            return HTMLResponse(pages.error(404, lang), status_code=404, headers=_PAGE)
        if result.view.get("view") == "document" and result.view.get("lang") in LANGS:
            lang = result.view["lang"]
        return HTMLResponse(pages.view(result.view, lang), headers=_PAGE)

    return app


async def _plain(send, status: int, body: bytes, kind: bytes = b"text/plain; charset=utf-8") -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", kind), (b"x-robots-tag", b"noindex"), (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})


class Host:
    """The stable site at the root; the draft under its prefix, and nowhere else.

    Any other ``/draft/…`` path is a bare 404 that says nothing of what the host holds.
    """

    def __init__(self, stable, draft, draft_base: str | None, draft_problems: list[str]):
        self.stable, self.draft, self.draft_base, self.draft_problems = stable, draft, draft_base, draft_problems

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]
            if path == DRAFT or path.startswith(DRAFT + "/"):
                base = self.draft_base
                if not base or (path != base and not path.startswith(base + "/")):
                    await _plain(send, 404, b"Not Found")
                    return
                if self.draft is None:
                    # The draft at this revision does not render: say so here, to its reviewers only.
                    body = "<!doctype html><meta charset=utf-8><title>Draft not available</title>" \
                           "<h1>This draft does not render</h1><ul>" + \
                           "".join(f"<li>{html.escape(p)}</li>" for p in self.draft_problems) + "</ul>"
                    await _plain(send, 503, body.encode("utf-8"), b"text/html; charset=utf-8")
                    return
                inner = path[len(base):] or "/"
                scope = {**scope, "path": inner, "raw_path": inner.encode()}
                await self.draft(scope, receive, send)
                return
        await self.stable(scope, receive, send)


def create_app(environ: Mapping[str, str] | None = None):
    environ = os.environ if environ is None else environ
    stable = load_stable(environ)
    draft, problems = load_draft(environ)
    revision = environ.get("LEGAL_REVISION")
    return Host(site_app(stable, legal_build.FINAL),
                site_app(draft, legal_build.SAMPLE) if draft else None,
                f"{DRAFT}/{revision}" if revision else None, problems)
