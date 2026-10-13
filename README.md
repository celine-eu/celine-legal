# celine-legal

The legal documents of an energy-community platform, and the host that serves them:

- **templates** that name no organisation: privacy notices, terms of use, data-processing
  and data-sharing agreements, the sub-processor list, consent texts;
- a **renderer** that fills them in from a deployment's own data;
- the **legal host**, one generic image: mount a deployment's data and it serves the
  published documents to people (pages) and to applications (`current.json`, the texts and
  their sha256), and, at a separate secret address, the draft under review.

The templates are written for Italian renewable energy communities (GDPR, the Italian
supervisory authority, the GSE incentive regime, Italian law). Every name, address and
provider comes from the deployment's data; the example deployment in
[`data/example/`](data/example/) invents them all.

## Primer

```sh
uv sync && task test              # the tests
task run                          # the host over the example: stable site at http://127.0.0.1:8080/,
                                  # draft at http://127.0.0.1:8080/draft/<commit>/
task render MODE=sample DATA=…    # check a deployment's data: render its draft into build/sample/
legal-build --data … --mode final --out … --publish --release vX.Y.Z   # publish approved texts
```

| You want to | Read |
|---|---|
| run the image for a deployment | [Run it](#run-it) |
| understand drafts, releases, approval | [The stable site and the draft](#the-stable-site-and-the-draft) |
| switch what the texts describe | [Optional features](#optional-features) |
| lay out a deployment's data | [`data/README.md`](data/README.md) |
| write or change a template | [`templates/README.md`](templates/README.md) |
| work on this repository, release it | [Development](#development), [Releasing](#releasing) |

## Run it

```sh
# the example: nothing published yet, and its draft
docker run -p 8080:8080 -e LEGAL_DATA=/app/data/example -e LEGAL_REVISION=$(printf '%040d' 0) \
  ghcr.io/celine-eu/celine-legal
# → http://localhost:8080/                       the stable site ("not yet available")
# → http://localhost:8080/draft/0000000000000000000000000000000000000000/   the draft

# a deployment: its data mounted read-only, its draft named by the data's commit
docker run -p 8080:8080 -e LEGAL_REVISION=$(git -C my-legal-data rev-parse HEAD) \
  -v "$PWD/my-legal-data:/data:ro" ghcr.io/celine-eu/celine-legal
```

Everything is laid out once, at startup, in memory; the container writes nothing and runs
with a read-only root filesystem.

| Variable | |
|---|---|
| `LEGAL_DATA` | the deployment's data directory (image default `/data`) |
| `LEGAL_REVISION` | the full 40-hex commit of the data: serves the draft at `/draft/<commit>/`. Unset, no draft |
| `LEGAL_RELEASE` | `vX.Y.Z`: pins the stable site to that release; the host refuses to start if it is not the newest published |
| `LEGAL_OFFERS` | the sharing offers members consent to; default `$LEGAL_DATA/sharing-offers.yaml` |
| `LEGAL_TEMPLATES` | the document templates; default the packaged ones |
| `LEGAL_FEATURE_<NAME>` | `true`/`false`: overrides one of the data's `features` in the draft (below) |

## The stable site and the draft

One host serves two sites that never meet.

| | the stable site | the draft |
|---|---|---|
| served at | the root | `/draft/<commit>/` only; any other `/draft/…` is a bare 404 |
| what it serves | the published editions only, as frozen; per slot the newest published version | the data as it is now, rendered: drafts included, every document for review (`/catalogue`), agreements for signature included |
| a slot with nothing published | a page: *Document not yet available*; not in `current.json` (`pending`) | the draft text |
| every page | the release | a banner: *SAMPLE — texts under review, not valid*, and the commit |
| `current.json` | `"mode": "final", "valid": true, "release": …` | `"mode": "sample", "valid": false, "revision": …` |
| every response | `X-Legal-Mode: final` | `X-Legal-Mode: sample` |
| one organisation's documents beside another's | never | in `/catalogue`, for review |
| when something is wrong | a published text edited after publication stops the host | the draft's address answers what does not render; the stable site keeps serving |

**Applications link the stable site only** (`LEGAL_BASE_URL` = the host's root), and record
acceptances against it. A draft never reaches an application: it is not in the root's
`current.json`, and a slot with nothing published yet says so instead of showing a text that
nobody approved. Until a first release, every slot is "not yet available".

**The draft's link is its access.** The commit of a private data repository cannot be
guessed, so the parties reviewing a draft get its link and nobody else finds it. The link
also names exactly what they reviewed: a new commit is a new draft at a new address. Pages
are never indexed. A draft that needs more than that sits behind the ingress's own
authentication.

**From draft to release:**

1. Each draft page shows, besides its text's sha256, the **fingerprint to approve**: the
   sha256 the text will have once final (a final text differs from its draft in its front
   matter and signature blocks). The parties approve those fingerprints.
2. Record them in the register, `approved_sha256: {it: …, en: …}` (`all` for the consent
   texts), and set `status: final`.
3. `legal-build --data … --mode final --out … --publish --release vX.Y.Z` freezes every new
   final, approved text into `editions/`. It refuses a text whose sha256 is not the approved
   one, so what is published is what was approved; and it records how each edition was
   made: the release, the renderer's version, the template and version, the features, the
   data's commit. Drafts in the register are left for a later release.
4. Commit `editions/` and restart the host on it: the stable site now serves the release.

A published text is never rendered again: the stable site serves the frozen copy, so a later
template, code or data change cannot alter a version someone accepted. A change to it is a
new version, drafted, approved and published in a new release.

## Optional features

A text must describe what the platform does, no more and no less. The features the
templates describe are listed in [`templates/features.yaml`](templates/features.yaml); each
one is declared in the data's `register.yaml` (`features:`) and can be overridden with
`LEGAL_FEATURE_<NAME>`. Feed the same value to the application and to the legal host, and
the text cannot describe a feature the deployment switched off. Adding a feature is a change
to `features.yaml` and to the templates that describe it
([`templates/README.md`](templates/README.md), "Adding a feature").

| Feature | What it means | The application setting it mirrors | What changes in the texts |
|---|---|---|---|
| `sms_verification` | the phone number is verified with a code sent by SMS | onboarding `phone_verification_enabled`: `SMS_PROVIDER` a dev provider, or `brevo` with `DPA_SMS_SIGNED` | the verification, the SMS provider, the retention of codes |
| `document_extraction` | the member uploads a bill or identity document, and a language model reads it and fills in the application | onboarding `document_processing_enabled`: `EXTRACTION_ENABLED` with `LLM_BASE_URL` and `LLM_VISION_MODEL` (upload follows the same switch) | the upload, its storage and retention, the automated reading, the language-model sub-processor line |
| `existing_members` | an applicant may declare they are already a member; staff complete the POD code (and the supply address, where the template defers it) from the community's member register | the onboarding template's `existing_members.enabled`. Per template, while the feature is per deployment: on if any community's template enables it | the declaration and the register as the source of the POD and address, in the privacy notice's application section and area check |
| `ai_assistant` | the community app has an AI assistant | the assistant deployed and linked | the assistant sections of the privacy notice and the terms, retention, rights, the language-model line |
| `dso_data_exchange` | meter readings are obtained from the grid operator through the dataspace | onboarding `DATASPACE_ENABLED` and celine-webapp `data_sharing_ready` (`DATA_SHARING_ENABLED` with `ONBOARDING_API_URL`), both on | the meter-reading sharing mentions, the dataspace in the REC data-processing agreement. With it off, the documents that exist only for the exchange (consent texts, data-sharing notice and agreement, DSO data-processing agreement, participation agreement) are left out, with their slots, and the host logs which |

Every feature must be declared; an undeclared one, a `LEGAL_FEATURE_*` naming no feature,
or a value that is not true or false stops the draft. The draft's `current.json` publishes
the values its texts were rendered with; a published edition records its own.

## What people and applications read

People's addresses put the slot first, `_` written `-`:

```text
/                              the platform's documents, plus the reader's organisation's
/<org>                         one organisation's documents and the platform's
/<slot>/<org>                  e.g. /terms/example-rec: the current version
/<slot>/<org>/<version>[/<lang>]
/<slot>                        no organisation in the path: ?for=<org>, then the Referer
                               (a page of this host, or the organisation's own website),
                               then a page that names no organisation
/catalogue                     every document under review (sample only)
```

Language: `?lang=`, then the browser's, then the document's first.

Applications read files by path: `/<owner>/current.json` (each slot's current version, the
text's path and sha256, `published_at`; see
[`templates/schemas/current.schema.json`](templates/schemas/current.schema.json)),
`/<owner>/history.json` (every published version, so an acceptance recorded with a date
maps to one version), `/<id>/<version>/<lang>.md` (the text), and a community's consent
texts. The sha256 is the text's, not the page's: restyling a page changes nothing a reader
accepted. The applications link `<host>/<rec>/<slot>/`, which redirects for good to
`/<slot>/<rec>`.

## A deployment's data

Keep it in the deployment's own, private repository, and mount it. This repository holds
the example only (`data/` is ignored but for `data/example/`). See
[`data/README.md`](data/README.md) for the layout, the conventions and the review lifecycle,
and [`templates/README.md`](templates/README.md) for writing a template.

Check a deployment's data without running the host:

```sh
legal-build --data ./my-legal-data --mode sample --out ./site
legal-build --data ./my-legal-data --mode final --out ./site --publish --release v1.0.0
```

## What stops it

The host does not start:
- without `LEGAL_DATA`, or with a `LEGAL_REVISION` that is not a full commit, or a
  `LEGAL_RELEASE` that is not `vX.Y.Z` or not the newest published;
- if a published text was edited after publication.

The draft does not render, and its address says why:
- a data file that does not match its schema (`templates/schemas/`);
- a feature not declared, or a switch naming none;
- a value a template needs and the data does not supply;
- a `final` document still showing the blank `[•]`;
- a published version that no longer renders the same (the change needs a new version).

`--publish` refuses without `--release`, and a text that is not the approved one.

## Development

| Task | What it does |
|---|---|
| `task test` | the tests (`uv run pytest`) |
| `task run [DATA=…] [REVISION=…] [RELEASE=…]` | the host on :8080, reloading on change; `DATA` defaults to the example, `REVISION` to the data's commit |
| `task render MODE=sample\|final [DATA=…]` | the draft or the stable site laid out into `build/<MODE>/`, with what it refused or left out |
| `task image` | builds the image as CI does and smoke-tests it on the example |
| `task check:private-names` | no tracked file names a private organisation (below) |
| `task release` | a semantic release from the conventional commits since the last tag, pushed (below) |

`check:private-names` reads the names that must never appear here from a file outside git
(`.private-names`, ignored, or `$LEGAL_PRIVATE_NAMES`); CI reads the repository secret
`LEGAL_PRIVATE_NAMES`. The templates' own test already refuses any example value typed into
a template.

## Releasing

```sh
task release
```

As in the other CELINE services, [python-semantic-release](https://python-semantic-release.readthedocs.io/)
reads the conventional commits since the last tag (`feat:` a minor, `fix:`/`perf:`/`up:` a
patch, `BREAKING CHANGE` a major, a minor while on 0.x), sets the version in `pyproject.toml` and `uv.lock`, adds
its section to `CHANGELOG.md`, commits, tags `vX.Y.Z` and pushes; the pushed tag starts the
release workflow.

**GitHub workflows** (`.github/workflows/`):

| Workflow | Runs on | Does |
|---|---|---|
| `ci.yaml` | every pull request, every push to `main` | the tests; the example laid out as a draft and as a stable site; the private-name check (with the `LEGAL_PRIVATE_NAMES` secret, skipped without) |
| `release.yaml` | a push to `main`, a tag | the tests; on a tag, checks the tag is `v` + the project's version; builds the image, smoke-tests it (no data refused; the draft and the stable site answer), pushes `ghcr.io/celine-eu/celine-legal:<tag>` and `:latest` (a tag) or `:dev` (`main`) |

A deployment pins a released tag (`vX.Y.Z`), never `latest` or `dev`.

## License

Apache-2.0.
