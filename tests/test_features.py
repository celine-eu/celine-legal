"""The texts describe the optional features a deployment has, and only those.

Each feature, switched off, takes its passages out of every text that describes it, and the
example still renders whole. The markers are phrases only that feature's passages carry.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from celine.legal import build as legal_build
from celine.legal import features as legal_features

LEGAL = Path(__file__).resolve().parent.parent
EXAMPLE = LEGAL / "data" / "example"
FEATURES = legal_features.catalogue(legal_build.TEMPLATES)

# feature -> (document, lang) -> phrases present when on, absent when off
MARKERS: dict[str, dict[tuple[str, str], list[str]]] = {
    "sms_verification": {
        ("example-rec/app-privacy-notice", "en"): ["one-time code sent by SMS", "Example SMS SAS", "SMS verification codes"],
        ("example-rec/app-privacy-notice", "it"): ["codice inviato via SMS", "Example SMS SAS", "Codici di verifica SMS"],
        ("platform/sub-processors", "en"): ["Example SMS SAS"],
        ("platform/sub-processors", "it"): ["Example SMS SAS"],
        ("example-rec/data-processing-agreement", "en"): ["Example SMS SAS"],
    },
    "document_extraction": {
        # Upload follows the same switch in onboarding (`document_processing_enabled`): off,
        # nothing is uploaded, stored or kept.
        ("example-rec/app-privacy-notice", "en"): ["an artificial intelligence model reads", "if you choose to upload them",
                                                   "The copies you upload are stored encrypted",
                                                   "Copies of the bill and identity document uploaded"],
        ("example-rec/app-privacy-notice", "it"): ["un modello di intelligenza\n  artificiale lo legge", "se scegli di caricarle",
                                                   "Le copie che carichi", "Copie della bolletta"],
        ("platform/sub-processors", "en"): ["reading of bills and identity documents"],
        ("platform/sub-processors", "it"): ["lettura di bollette e documenti d'identità"],
        ("example-rec/data-processing-agreement", "en"): ["by a language model", "the data read from them",
                                                          "copies of an electricity bill",
                                                          "uploaded documents are encrypted per file"],
    },
    "existing_members": {
        ("example-rec/app-privacy-notice", "en"): ["already a member of Example REC", "member register",
                                                   "the register's address decides the area"],
        ("example-rec/app-privacy-notice", "it"): ["già socio di Example REC", "libro dei soci",
                                                   "l'area è decisa dall'indirizzo del libro dei soci"],
    },
    "ai_assistant": {
        ("example-rec/app-privacy-notice", "en"): ["### 2.5 The AI assistant", "assistant conversations"],
        ("example-rec/app-privacy-notice", "it"): ["### 2.5 L'assistente AI", "assistente AI"],
        ("example-rec/terms-of-use", "en"): ["## 6. The AI assistant", "AI assistant", "answers from the assistant"],
        ("example-rec/terms-of-use", "it"): ["## 6. L'assistente AI", "assistente AI", "risposte dell'assistente"],
        ("example-rec-2/terms-of-use", "en"): ["## 6. Assistant based on artificial intelligence", "use the AI assistant",
                                               "answers from the AI assistant"],
        ("example-rec-2/terms-of-use", "it"): ["## 6. Assistente basato su intelligenza artificiale",
                                               "utilizzare l’assistente AI", "risposte dell’assistente AI"],
        ("platform/sub-processors", "en"): ["AI assistant"],
        ("platform/sub-processors", "it"): ["Assistente AI"],
        ("example-rec/data-processing-agreement", "en"): ["AI assistant", "not to provide any to the assistant"],
    },
    "dso_data_exchange": {
        ("example-rec/app-privacy-notice", "en"): ["Sharing your meter readings", "data-sharing choices"],
        ("example-rec/app-privacy-notice", "it"): ["Condivisione dei tuoi dati di misura", "scelte di condivisione"],
        ("example-rec/terms-of-use", "en"): ["sharing of your meter readings"],
        ("example-rec/terms-of-use", "it"): ["condivisione dei tuoi dati di misura"],
        ("example-rec-2/terms-of-use", "en"): ["manage"],
        ("example-rec-2/terms-of-use", "it"): ["gestire"],
        ("platform/sub-processors", "en"): ["dataspace nodes", "grid operators"],
        ("platform/sub-processors", "it"): ["nodi nel dataspace", "gestori di rete"],
        ("example-rec/data-processing-agreement", "en"): ["independent controller of the meter readings",
                                                         "dataspace connector", "dataspace identifier",
                                                         "provenance record"],
    },
}


def _texts(data: Path = EXAMPLE, off: tuple[str, ...] = ()) -> dict[tuple[str, str], str]:
    environ = {f"{legal_features.PREFIX}{name.upper()}": "false" for name in off}
    result = legal_build.build(data, None, environ=environ)
    assert result.problems == []
    assert {n for n, on in result.features.items() if not on} == set(off)
    return {(f.entry_id, f.lang): f.text for f in result.files if f.lang}


ALL_ON = None


def _all_on() -> dict[tuple[str, str], str]:
    global ALL_ON
    ALL_ON = ALL_ON or _texts()
    return ALL_ON


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_a_feature_switched_off_leaves_its_texts_out(feature):
    on, off = _all_on(), _texts(off=(feature,))
    for key, phrases in MARKERS[feature].items():
        for phrase in phrases:
            assert phrase in on[key], (key, phrase)
            assert phrase not in off.get(key, ""), (key, phrase)


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_a_feature_switched_off_changes_no_other_feature_text(feature):
    off = _texts(off=(feature,))
    for other, by_doc in MARKERS.items():
        if other == feature:
            continue
        for key, phrases in by_doc.items():
            if key not in off:
                continue  # a document that exists only for the feature switched off
            # The language model line names both the assistant and the reading of documents:
            # switching one off rewords it, so only the phrases of the one still on must stay.
            for phrase in phrases:
                if feature in ("ai_assistant", "document_extraction") and phrase in (
                        "reading of bills and identity documents", "lettura di bollette e documenti d'identità",
                        "AI assistant", "Assistente AI"):
                    continue
                assert phrase in off[key], (feature, key, phrase)


def test_every_feature_off_still_renders_every_document():
    texts = _texts(off=tuple(FEATURES))
    only_for_dso = {k for k in _all_on() if not k[0].startswith(("platform/sub", "platform/research", "example-rec/app", "example-rec/terms",
                                                                     "example-rec-2/", "example-rec/data-processing"))}
    assert set(texts) == set(_all_on()) - only_for_dso
    assert {k[0] for k in only_for_dso} == {
        "example-rec/data-sharing-privacy-notice", "example-rec/data-sharing-agreement",
        "example-dso/data-processing-agreement", "dataspace/participation-agreement"}
    for key, text in texts.items():
        assert "\n\n\n" not in text, key  # nothing left an empty block behind


def test_the_sections_after_a_removed_one_are_renumbered():
    texts = _texts(off=("ai_assistant",))
    assert "### 2.5 Feedback" in texts[("example-rec/app-privacy-notice", "en")]
    assert "### 2.7 Updates from" in texts[("example-rec/app-privacy-notice", "en")]
    assert "### 2.5 Le segnalazioni" in texts[("example-rec/app-privacy-notice", "it")]
    assert "## 6. Proper use" in texts[("example-rec/terms-of-use", "en")]
    assert "## 13. Contacts" in texts[("example-rec/terms-of-use", "en")]
    assert "## 6. Uso corretto" in texts[("example-rec/terms-of-use", "it")]
    assert "## 13. Contatti" in texts[("example-rec/terms-of-use", "it")]
    # A text that cites its own articles cites them by their new numbers.
    for lang, contacts in (("en", "Art. 14"), ("it", "art. 14")):
        text = texts[("example-rec-2/terms-of-use", lang)]
        assert "## 14. " in text and "## 15. " not in text
        assert f"{contacts}." in text and "15." not in text.replace("\n", " ")


def test_a_list_ending_early_still_ends_with_a_full_stop():
    texts = _texts(off=("dso_data_exchange",))
    assert "- change your notification settings.\n" in texts[("example-rec/app-privacy-notice", "en")]
    assert "- modificare le notifiche.\n" in texts[("example-rec/app-privacy-notice", "it")]


def test_without_sms_the_sms_provider_need_not_be_supplied(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(EXAMPLE, data)
    parties = yaml.safe_load((data / "parties.yaml").read_text())
    del parties["providers"]["sms"]
    (data / "parties.yaml").write_text(yaml.safe_dump(parties, allow_unicode=True))
    environ = {"LEGAL_FEATURE_SMS_VERIFICATION": "false"}
    assert legal_build.build(data, None, environ=environ).problems == []
    assert legal_build.build(data, None).problems != []



def _sending_contracted_by_the_community(tmp_path) -> Path:
    data = tmp_path / "data"
    shutil.copytree(EXAMPLE, data)
    parties = yaml.safe_load((data / "parties.yaml").read_text())
    for key in ("email", "sms"):
        parties["providers"][key]["sub_processor"] = False
    (data / "parties.yaml").write_text(yaml.safe_dump(parties, allow_unicode=True, sort_keys=False))
    return data


def test_a_provider_the_community_contracts_is_not_listed_as_a_sub_processor(tmp_path):
    """Email and SMS sent on the community's own account: the platform's lists leave them out."""
    on = _all_on()
    texts = _texts(_sending_contracted_by_the_community(tmp_path))
    for name in ("Example Mail SA", "Example SMS SAS"):
        for key in (("platform/sub-processors", "it"), ("platform/sub-processors", "en"),
                    ("example-rec-2/data-processing-agreement", "en"),
                    ("example-rec-2/app-privacy-notice", "it"), ("example-rec-2/app-privacy-notice", "en")):
            assert name in on[key], (key, name)
            assert name not in texts[key], (key, name)
    assert "  - Example Cloud Ltd, per l'hosting nell'Unione europea;\n- **Example Maps" in \
        texts[("example-rec-2/app-privacy-notice", "it")]


def test_the_research_notice_is_the_platform_operators_for_the_project():
    on, off = _all_on(), _texts(off=("document_extraction",))
    for lang, phrases in (
            ("it", ["I tuoi dati saranno trattati da Example Platform S.r.l. in Italia",
                    "- progetto di ricerca EXAMPLE, Grant Agreement n. 000000000.", "30 novembre 2027",
                    "dpo@platform.example.org", "attraverso la pagina online di raccolta dei dati."]),
            ("en", ["Your data will be processed by Example Platform S.r.l. in Italy",
                    "- the EXAMPLE research project, Grant Agreement No. 000000000.", "30 November 2027",
                    "dpo@platform.example.org", "through the online data collection page."])):
        text = on[("platform/research-privacy-notice", lang)]
        for phrase in phrases:
            assert phrase in " ".join(text.split()), (lang, phrase)
    assert "- copie di una bolletta elettrica;" in on[("platform/research-privacy-notice", "it")]
    assert "bolletta" not in off[("platform/research-privacy-notice", "it")]
    assert "electricity bill" not in off[("platform/research-privacy-notice", "en")]


def test_the_agreement_no_longer_says_the_processor_has_no_purposes_of_its_own():
    on, off = _all_on(), _texts(off=("dso_data_exchange",))
    with_exchange = on[("example-rec-2/data-processing-agreement", "en")]
    without = off[("example-rec-2/data-processing-agreement", "en")]
    for text in (with_exchange, without):
        assert "does not use personal data processed under this agreement" not in text
        assert "own legal basis and privacy notice" not in text
    assert "## 4. The Processor's own processing\n\nThe Processor is a separate" in with_exchange
    assert "## 5. Confidentiality" in with_exchange and "subject to clause 11." in with_exchange
    assert "own processing" not in without
    assert "## 4. Confidentiality" in without and "## 13. Law and jurisdiction" in without
    assert "subject to clause 10." in without and "## 10. End of the service" in without
    assert "does not use personal data processed under this agreement" in \
        on[("example-rec/data-processing-agreement", "en")]  # 0.1, as published


def test_an_unknown_feature_switch_is_refused():
    values, problems = legal_features.resolve(dict.fromkeys(FEATURES, True),
                                              {"LEGAL_FEATURE_SMS_VERIFICATON": "false"}, FEATURES)
    assert problems and "no such feature" in problems[0]


def test_a_feature_switch_must_say_true_or_false():
    _, problems = legal_features.resolve(dict.fromkeys(FEATURES, True),
                                         {"LEGAL_FEATURE_AI_ASSISTANT": "maybe"}, FEATURES)
    assert problems == ["LEGAL_FEATURE_AI_ASSISTANT='maybe': not true or false"]


def test_an_undeclared_feature_is_refused(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(EXAMPLE, data)
    register = yaml.safe_load((data / "register.yaml").read_text())
    del register["features"]["ai_assistant"]
    (data / "register.yaml").write_text(yaml.safe_dump(register, allow_unicode=True))
    result = legal_build.build(data, None)
    assert result.files == []
    assert "features.ai_assistant: not declared in register.yaml (true or false)" in result.problems


def test_a_document_that_exists_only_for_an_exchange_that_is_off_is_left_out_with_its_slots():
    environ = {f"{legal_features.PREFIX}DSO_DATA_EXCHANGE": "false"}
    result = legal_build.build(EXAMPLE, None, environ=environ)
    assert result.problems == []
    assert result.omitted == {entry: "dso_data_exchange" for entry in (
        "dataspace/participation-agreement", "example-dso/data-processing-agreement",
        "example-rec/consent-texts", "example-rec-2/consent-texts", "example-rec/data-sharing-agreement",
        "example-rec/data-sharing-privacy-notice")}
    files, problems = legal_build.site(result, EXAMPLE, "sample")
    assert problems == []
    current = {f.path: json.loads(f.text) for f in files if f.path.endswith("current.json")}
    assert "data_sharing_notice" not in current["example-rec/current.json"]["slots"]
    assert "participation_agreement" not in current["platform/current.json"]["slots"]
    assert not [f.path for f in files if f.path.startswith(tuple(result.omitted))]


def test_the_features_are_the_templates_to_declare(tmp_path):
    """A template set that describes a new feature declares it beside its texts."""
    import shutil

    templates = tmp_path / "templates"
    shutil.copytree(legal_build.TEMPLATES, templates)
    catalogue = templates / "features.yaml"
    catalogue.write_text(catalogue.read_text() + "\n  smart_meter_pairing:\n    description: a new one\n")
    problems = legal_build.build(EXAMPLE, None, templates).problems
    assert problems == ["features.smart_meter_pairing: not declared in register.yaml (true or false)"]


def test_the_stable_site_announces_only_what_can_exist_here():
    environ = {f"{legal_features.PREFIX}DSO_DATA_EXCHANGE": "false"}
    _, files, problems = legal_build.render(EXAMPLE, "final", environ=environ)
    assert problems == []
    current = {f.path: json.loads(f.text) for f in files if f.path.endswith("current.json")}
    assert current["example-rec/current.json"]["pending"] == ["privacy", "terms"]
    assert current["platform/current.json"]["pending"] == ["research_notice", "sub_processors"]


TRANSFERS = {
    ("example-rec/app-privacy-notice", "en"): ["may access your data from outside the European Economic",
                                               "Example SMS SAS: support access from outside the EEA"],
    ("example-rec/app-privacy-notice", "it"): ["possono accedere ai tuoi dati da fuori dello Spazio",
                                               "Example SMS SAS: accesso del supporto tecnico"],
    ("platform/sub-processors", "en"): ["| Transfers outside the EEA |", "| European Union | None |"],
    ("platform/sub-processors", "it"): ["| Trasferimenti fuori dallo SEE |", "| Unione europea | Nessuno |"],
    ("example-rec/data-processing-agreement", "en"): ["stored and processed in the European Economic Area:",
                                                      "the Controller instructs those transfers",
                                                      "No other transfer outside", "| Transfers outside the EEA |"],
}


def test_a_sub_processors_transfers_are_stated_wherever_it_is_listed():
    on = _all_on()
    for key, phrases in TRANSFERS.items():
        for phrase in phrases:
            assert phrase in on[key], (key, phrase)


def _without_transfers(tmp_path) -> Path:
    data = tmp_path / "data"
    shutil.copytree(EXAMPLE, data)
    parties = yaml.safe_load((data / "parties.yaml").read_text())
    for p in parties["providers"].values():
        p.pop("transfers", None)
    (data / "parties.yaml").write_text(yaml.safe_dump(parties, allow_unicode=True, sort_keys=False))
    return data


def test_with_no_transfers_the_texts_say_the_eea_only(tmp_path):
    texts = _texts(_without_transfers(tmp_path))
    for key, phrases in TRANSFERS.items():
        for phrase in phrases:
            assert phrase not in texts[key], (key, phrase)
    assert "processed in the European Economic Area only:" in texts[("example-rec/data-processing-agreement", "en")]
    assert "| Provider | Service | Where |\n" in texts[("platform/sub-processors", "en")]


def test_a_transfer_goes_with_its_provider(tmp_path):
    """Without SMS, the SMS provider's transfer is not stated either."""
    texts = _texts(off=("sms_verification",))
    for key, phrases in TRANSFERS.items():
        for phrase in phrases:
            assert phrase not in texts[key], (key, phrase)
    # and the texts read exactly as with no provider stating one
    assert texts == _texts(_without_transfers(tmp_path), off=("sms_verification",))


@pytest.mark.parametrize("off", [(), ("ai_assistant",)])
def test_the_clauses_approved_specifically_are_the_articles_by_their_numbers(off):
    """Box 2 names each clause by its heading's number and title, renumbered with them."""
    import re

    texts = _all_on() if not off else _texts(off=off)
    for lang, art in (("it", "art."), ("en", "Art.")):
        text = texts[("example-rec-2/terms-of-use", lang)]
        approval = legal_build.declarations_of(text)["specific_approval"]
        cited = re.findall(rf"{re.escape(art)} (\d+) \(([^)]+)\)", approval["text"])
        assert [int(n) for n, _ in cited] == approval["articles"]
        headings = dict(re.findall(r"^## (\d+)\. (.+)$", text, re.M))
        for number, title in cited:
            assert headings[number].lower() == title.lower(), (lang, number, title)
        assert approval["articles"][-1] == (12 if off else 13)
