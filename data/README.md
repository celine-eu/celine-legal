# data/

A deployment's legal data: which template version each document uses, for whom it is
rendered, who those parties are, which optional features the deployment has, and how far
each document's review has got. The texts are templates in [`../templates/`](../templates/),
and nothing in them names an organisation.

**Only [`example/`](example/) belongs in this repository.** It invents every party, and the
tests render every template with it. A real deployment keeps its data in its own private
repository and mounts it into the legal host (`LEGAL_DATA`); everything else under `data/` is
ignored by git.

## Layout

```text
register.yaml              every document: template and version, the actor it is rendered
                           for, its status, its acceptance (`signature` for agreements
                           between organisations); each community's identity file, grid
                           operator and slots (`recs:`); the platform's slots
                           (`platform_roles:`); the optional features (`features:`)
parties.yaml               every party other than the energy communities: grid operators,
                           the platform operator, the dataspace; the platform's providers,
                           the processing relations, hosting, the funding project
                           (validated by ../templates/schemas/parties.schema.json)
sharing-offers.yaml        the data-sharing offers members consent to (or LEGAL_OFFERS)
recs/<rec>/
    identity.yaml          the community's identity, a snapshot of its rec-registry record
                           (validated by ../templates/schemas/identity.schema.json)
    baseline/              the community's own published documents, captured with sha256
editions/                  written by `legal-build --publish`: every published text, frozen,
                           and index.yaml with when each was published and its sha256
```

A deployment may keep reviewer notes beside its data (`notes/` folders); the renderer does
not read them.

## Conventions

- **A community's identity lives in the rec-registry**, which its operator maintains.
  `recs/<rec>/identity.yaml` is the snapshot the renderer reads, so a registry edit never
  changes a published text by itself. A snapshot that differs from the registry is a new
  edition.
- **Every other party lives in `parties.yaml`.** A template reads these values and never
  invents them.
- **Features are declared, every one** (`features:` in `register.yaml`; which features
  exist is `../templates/features.yaml`'s to say). A deployment that has not decided whether it verifies phone numbers by SMS cannot
  render a privacy notice.
- **The documents are written as they will be published.** A template holds the text and
  front matter, and nothing else: no drafting notes or open questions.
- **Blanks use `[•]`.** A blank is a value nobody has supplied yet, such as a registered
  office or a signatory. It is a data value, never typed into a template. A `final` edition
  must render no `[•]`, and the renderer refuses one that does.
- **Baseline** is a capture of a document someone else owns and publishes (a community's
  statute): the original file, its text, and an entry in `baseline/index.yaml` with its
  source URL, date and sha256. A recapture that changes the hash is a new entry; a baseline
  is never edited.
- **Italian** is the language members read; English is a faithful translation. Agreements
  between organisations are in English.

## Lifecycle

1. **draft**: the register lists the document at `status: draft`. Commit, and the host with
   `LEGAL_REVISION=<commit>` serves that commit at `/draft/<commit>/`, marked as a sample.
   Send the parties the link. The stable site, at the root, says the document is not yet
   available until a release publishes it.
2. **reviewed**: the reviewer records `reviewed:` in `register.yaml`, with name and date.
3. **approved**: each draft page shows the fingerprint to approve, the sha256 the text will
   have once final. Record what the parties approved, `approved_sha256: {it: …, en: …}`
   (`all` for the consent texts), with `approved:` (who, when). Any later change to the
   template, the data or the renderer changes the fingerprint and needs approving again.
4. **final**: every `[•]` supplied, `status: final`.
5. **published**: `legal-build --data <data> --mode final --out <dir> --publish --release
   vX.Y.Z` freezes each final edition into `editions/`, refusing any text that is not the
   approved one, and records its publication time, sha256, release, template, renderer,
   features and data commit. Commit `editions/` to the deployment's repository: it is the
   record of what was published. The host's stable site, at the root, serves it from then
   on; drafts still in the register wait for a later release.

A change to a published document is a new template version (a new folder in
`../templates/documents/<document>/`) and a new entry version in the register. Where
acceptance is recorded, a new version is accepted again; acceptance never carries forward.

## Adding an energy community

1. Put its identity in the rec-registry, and its snapshot in `recs/<rec>/identity.yaml`.
2. Capture its own published documents in `recs/<rec>/baseline/`.
3. Add it under `recs:` in `register.yaml`, with its grid operator (in `parties.yaml` if new)
   and its slots.
4. Add its documents to `register.yaml`: the templates and versions it uses,
   `for: {rec: <rec>}`, starting at `status: draft`. No text is copied.
