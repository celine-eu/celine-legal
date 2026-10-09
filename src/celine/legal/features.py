"""The optional features a deployment switches, which the texts must describe as they are.

A text says what the platform does. A feature a deployment turns off (no SMS check, no
reading of uploaded documents, no assistant, no meter data from the grid operator) must not
be described, and one it turns on must be. So the templates read ``features.<name>``, and
the value comes from the deployment, not from the template.

Which features exist is the templates' to say: ``<templates>/features.yaml``. A template set
that describes a new feature declares it there, beside the texts that read it.

Each feature is declared in the data (``register.yaml``, ``features:``), every one of them,
so a deployment that has not decided cannot render. The environment can override a
declaration, ``LEGAL_FEATURE_<NAME>=true|false``, so one value in a deployment's
configuration can switch both the application and the text that describes it. An
environment variable naming no feature stops the render: a misspelt switch must not leave
a text describing a feature that is off.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml

PREFIX = "LEGAL_FEATURE_"
CATALOGUE = "features.yaml"

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


def catalogue(templates: Path) -> dict[str, dict]:
    """Every feature the templates describe: name -> ``description``, ``mirrors``, ``documents``."""
    path = templates / CATALOGUE
    if not path.is_file():
        return {}
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("features") or {}


def resolve(declared: Mapping | None, environ: Mapping[str, str],
            known: Mapping[str, dict]) -> tuple[dict[str, bool], list[str]]:
    """Every feature's value: the declaration, overridden by the environment. Pure.

    Returns the values and the problems; with any problem the values are not to be used.
    """
    problems: list[str] = []
    declared = dict(declared or {})
    values: dict[str, bool] = {}
    for name in known:
        if name not in declared:
            problems.append(f"features.{name}: not declared in register.yaml (true or false)")
        elif not isinstance(declared[name], bool):
            problems.append(f"features.{name}: {declared[name]!r} is not true or false")
        else:
            values[name] = declared[name]
    problems += [f"features.{name}: no such feature in the templates' {CATALOGUE}" for name in declared
                 if name not in known]
    for key, raw in environ.items():
        if not key.startswith(PREFIX):
            continue
        name = key[len(PREFIX):].lower()
        if name not in known:
            problems.append(f"{key}: no such feature (one of {', '.join(sorted(known))})")
        elif raw.strip().lower() in _TRUE:
            values[name] = True
        elif raw.strip().lower() in _FALSE:
            values[name] = False
        else:
            problems.append(f"{key}={raw!r}: not true or false")
    return values, problems


def omitted(documents: list[dict], values: Mapping[str, bool], known: Mapping[str, dict]) -> dict[str, str]:
    """Register entries whose template exists only with a feature that is off: id -> feature. Pure."""
    requires = {template: name for name, spec in known.items() for template in spec.get("documents") or []}
    left_out = {}
    for entry in documents:
        feature = requires.get(entry.get("template") or "")
        if feature and values.get(feature) is False:
            left_out[entry["id"]] = feature
    return left_out
