# CHANGELOG

<!-- version list -->

## v0.4.0 (2026-10-16)

### Features

- Improve general terms
  ([`10b323a`](https://github.com/celine-eu/celine-legal/commit/10b323ab938cf796df4c2f0641eea91479f0cfe3))


## v0.3.0 (2026-10-14)

### Features

- Allow to track last draft revision
  ([`b9445d9`](https://github.com/celine-eu/celine-legal/commit/b9445d9836184a657b7b5d5887bd906ad991ad9c))


## v0.2.0 (2026-10-13)

### Bug Fixes

- Review release and workflow
  ([`a9e6e07`](https://github.com/celine-eu/celine-legal/commit/a9e6e07f262de78f422a5d2ca1941b6eb4fa5f36))

### Chores

- Fix sv templates path
  ([`b4562cd`](https://github.com/celine-eu/celine-legal/commit/b4562cd5b2b6664e442556afee4583de9b73fb8c))

### Features

- Add sms handling
  ([`a9cde09`](https://github.com/celine-eu/celine-legal/commit/a9cde095541835cd5d1f330f143b29235d52b519))


## v0.2.0: notes

The changes released in v0.2.0, in detail (the section above is generated from the commits).

- Feature `existing_members`: the privacy notice describes the applicant's declaration that
  they are already a member, and the community's member register as the source of the POD
  code and supply address that staff complete (onboarding REQ-0024–0026). It mirrors the
  onboarding template's `existing_members.enabled`. A deployment declares it in
  `register.yaml`; a host older than this release refuses data that declares it, and
  `LEGAL_FEATURE_EXISTING_MEMBERS`.
- A provider in `parties.yaml` may state `transfers: {it, en}`: what may leave the EEA, and
  under which safeguard. Where one does, the community data-processing agreement (§8 and
  Annex 3), the sub-processor list and the privacy notice (§5) state it. Where none does,
  the texts are unchanged.

## v0.1.0

First release.

- Actor-free templates for an energy community's legal documents: app privacy notice,
  terms of use, data-sharing privacy notice and agreement, data-processing agreements
  (community, grid operator), sub-processors, dataspace participation agreement, consent
  texts.
- `legal-build`: renders a deployment's data with the templates; `--publish --release`
  freezes the approved final texts into `editions/` with their provenance.
- The legal host, one image: the stable site at the root (published releases only, "not
  yet available" otherwise), the draft at `/draft/<commit>/` for review.
- Optional features (`templates/features.yaml`): SMS verification, document extraction,
  AI assistant, DSO data exchange.
