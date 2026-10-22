# Legal document templates

The legal documents of an energy-community platform and its dataspace, written as
templates that name no organisation. A deployment supplies the actors as data and renders
its own set, so a replicator gets complete documents without copying or rewording a text.

The templates are written for Italian renewable energy communities: they cite the GDPR,
the Italian supervisory authority and the GSE incentive regime, and they choose Italian
law. A deployment outside that regime needs its own template versions.

## Layout

```text
documents/<document>/<version>/   one template version: <lang>.md.j2 per language, and
                                  links.yaml, the references its page links
consent-texts/<version>/          the words a member reads per data-sharing offer,
                                  generated from the offers (one template per purpose)
features.yaml                     the optional features these templates describe (`features.<name>`)
schemas/                          what a deployment must supply
    identity.schema.json          an organisation a document names
    parties.schema.json           the deployment's parties other than its communities
    current.schema.json           what an application reads: <rec>/current.json
    history.schema.json           every published version per slot: <rec>/history.json
macros/                           shared wording: durations, lists
page/                             the legal host's pages around a text (not part of any text,
                                  so restyling them changes no sha256)
```

The renderer is `celine.legal.build` (`legal-build`, in `../src/`), and the example
deployment the templates are tested against is `../data/example/`.

A published template version is never edited. A change is a new version folder, and a
deployment moves to it in its register.

## What a deployment supplies

`legal-build --data <dir> --mode sample|final --out <dir> [--offers <file>]` (and the legal
host, at startup) reads:

- `<data>/register.yaml`: per document, `template`, `version`, `langs`, `status`, and
  `for: {rec: <key>}` or `{dso: <key>}`; `effective` and `params` where the template reads them
  (terms-of-use 0.2: `liability_cap_eur`, `liability_period`, `conciliation_body`). Under `recs:` it gives each community's
  `identity` file and grid operator `dso`. Under `features:`, every optional feature.
- `<data>/parties.yaml`: `roles` (at least `platform_operator`), `parties`, `providers`,
  `processing`, `hosting`, `project`.
- each community's identity: a snapshot of its registry record.
- the offers members are asked to consent to (`<data>/sharing-offers.yaml`, or `--offers`).

## What a template may read

| Variable | What it is |
|---|---|
| `doc` | `id`, `template`, `version`, `status`, `lang`, `langs`; `effective`, the date the version takes effect (the entry's `effective:`, a blank until set); `params`, the terms a community sets for a template that asks for them (the entry's `params:`) |
| `rec` | the community the document is rendered for (community documents only) |
| `dso` | that community's grid operator, or the one a grid-operator document is for |
| `platform` | the platform operator |
| `parties`, `roles` | every party, and which party plays which role |
| `party_by_alias` | an offer recipient's alias → its party or community |
| `providers`, `processing`, `hosting`, `project` | the platform's providers, the Art. 28 relations, where it runs, the funding project |
| `offers`, `offers_by_id` | the sharing offers |
| `consent_texts` | the community's rendered consent texts (documents that cite them) |
| `features` | the optional features, each `true` or `false` (`features.yaml`) |

**A feature switched off takes its passages out.** Wrap every passage that describes a
feature in `{% if features.<name> %}`, and read a value only that feature needs (the SMS
provider, say) inside the condition, so a deployment without the feature need not supply it.
Where a whole numbered section goes, the sections after it are renumbered, and a list that
ends early still ends with a full stop. With every feature on, the text must read exactly as
before: `tests/test_features.py` renders the example with each feature off and with all off.

## Links between texts

A text refers to other texts ("l'elenco dei sub-responsabili") and to its own articles
("art. 15", "§4"). The legal host links them on the page, without changing the text, so its
sha256 and the fingerprint the parties approve stay the same.

- **Anchors.** Every numbered heading gets one: `## 5. …` is `#sec-5`, `### 2.1 …` is
  `#sec-2-1`, `## Annex 3 — …` (or `Allegato 3`) is `#annex-3`. An application can link an
  article directly: `<terms url>#sec-9`.
- **References.** A template version declares its own in `links.yaml`, beside its
  `<lang>.md.j2`, per language:

  ```yaml
  it:
    - {find: 'elenco dei sub-responsabili della piattaforma', slot: sub_processors}
    - {find: 'art\. (\d+)(?!\d)', anchor: 'sec-{1}'}
    - {find: 'privacy notice for the platform, §6', slot: privacy, anchor: sec-6}
  ```

  `find` is a regular expression over the page's text (a space matches any whitespace, so
  a line break does too; headings and existing links are left alone). `slot` names the
  document referred to: the owner's slot of that name, else the platform's, and when
  neither exists the words stay unlinked. `anchor` is a heading there, or in this text
  when there is no `slot`; `{1}` is the first group, dots written as dashes.
- The slot names the templates refer to: `privacy`, `terms`, `data_sharing_notice`,
  `member_privacy_notice` (the community's own notice for members), `regulations`,
  `statute`, `sub_processors`.

Every `find` must match the example's text (`tests/test_links.py`), so a reference a new
wording drops fails there. Adding a `links.yaml` to a published template version is allowed:
it changes the page, not the text.

## Adding a feature

When an application gains a switch that changes what the texts must say:

1. Add it to `features.yaml`: `description`, `mirrors` (the application setting whose
   effective value it must equal), and `documents` if some templates exist only with it.
2. Wrap every passage that describes it, in every template and language, as above.
3. Declare it in `../data/example/register.yaml` (and in every deployment's register: a
   deployment that has not declared it cannot render).
4. Add its marker phrases to `tests/test_features.py`, and a row to the README's table.
5. A text already published does not change; the deployment publishes a new version.

Rendering is strict: a variable the data does not supply fails the build. A value nobody
has supplied yet is the blank `[•]`, and an edition marked `final` must render none.

## Tests

`tests/test_render_example.py` renders every template for the example deployment in
`data/example/`. It fails on any missing variable and on any example actor name typed into a
template. `tests/test_features.py` renders it with features switched off.
