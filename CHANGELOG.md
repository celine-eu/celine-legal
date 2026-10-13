# Changelog

Versions are released as git tags `vX.Y.Z`; each tag publishes the image
`ghcr.io/celine-eu/celine-legal:vX.Y.Z` (and `:latest`).

## Unreleased

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

## 0.1.0

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
