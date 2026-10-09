# Changelog

Versions are released as git tags `vX.Y.Z`; each tag publishes the image
`ghcr.io/celine-eu/celine-legal:vX.Y.Z` (and `:latest`).

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
