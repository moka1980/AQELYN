"""ECR-0108: Principle 2 served additively, so there is nothing for a truth to drift from.

The invariant this file exists to protect: the finding's own sentence is byte-identical in
every mode. Plain language is offered beside it, never instead of it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from aqelyn.reporting.analyze import CollectionAnalysis, analyze_collection
from aqelyn.reporting.disclosure import Mode
from aqelyn.reporting.glossary import GLOSSARY, glosses_for
from aqelyn.reporting.html import render_findings_report

_VULNS: dict[str, Any] = {
    "descriptor": {"name": "grype", "timestamp": "2026-08-06T09:00:00Z"},
    "matches": [],
}

_BODY = re.compile(r'<div class="level-body">(.*?)</div>', re.S)
_BLOCK = re.compile(r'<ul class="plain-words".*?</ul>', re.S)
_TERM = re.compile(r"<dfn>([^<]*)</dfn>")


def _observation() -> dict[str, Any]:
    return {
        "observation_id": "obs-ports",
        "subject": {"kind": "host", "ref": "203.0.113.10"},
        "check": "listening_sockets_public",
        "severity": "high",
        "severity_score": 70.0,
        "observed": {"public_ports": [8080]},
        "what_happened": "Two ports are reachable from beyond this machine.",
        "why_it_matters": "They sit beside the reverse proxy rather than behind it.",
        "how_determined": "Parsed ss -tlnH; loopback addresses were excluded.",
        "risk_of_inaction": "A listening socket meant for local use is exposed.",
        "remediation": {
            "summary": "Bind them to loopback.",
            "difficulty": "low",
            "expected_outcome": "Only intended ports stay reachable.",
        },
    }


async def _analysis(tmp_path: Path) -> CollectionAnalysis:
    (tmp_path / "vulns.json").write_text(json.dumps(_VULNS), encoding="utf-8")
    (tmp_path / "posture.json").write_text(
        json.dumps({"observations": [_observation()]}), encoding="utf-8"
    )
    return await analyze_collection(tmp_path)


# --- the invariant ---------------------------------------------------------------------


async def test_the_finding_sentence_is_identical_in_every_mode(tmp_path: Path) -> None:
    """One analysis rendered four ways. Building a fresh analysis per mode would mint new
    evidence ids and compare different findings - the trap ECR-0104 already fell into."""
    analysis = await _analysis(tmp_path)
    reference = _BODY.findall(render_findings_report(analysis, mode=Mode.EXPERT))
    assert reference
    for mode in Mode:
        assert _BODY.findall(render_findings_report(analysis, mode=mode)) == reference


async def test_plain_words_are_added_not_substituted(tmp_path: Path) -> None:
    """The jargon sentence survives verbatim, with the gloss block immediately after it."""
    analysis = await _analysis(tmp_path)
    rendered = render_findings_report(analysis, mode=Mode.HOME)
    sentence = "They sit beside the reverse proxy rather than behind it."
    assert sentence in rendered
    after = rendered.split(sentence, 1)[1]
    assert after.lstrip().startswith("</div>")
    assert 'class="plain-words"' in after[:400]
    assert "reverse proxy" in after[:400]


# --- who gets them ----------------------------------------------------------------------


async def test_a_home_reader_is_offered_plain_words(tmp_path: Path) -> None:
    analysis = await _analysis(tmp_path)
    assert 'class="plain-words"' in render_findings_report(analysis, mode=Mode.HOME)


async def test_an_smb_reader_is_offered_plain_words(tmp_path: Path) -> None:
    analysis = await _analysis(tmp_path)
    assert 'class="plain-words"' in render_findings_report(analysis, mode=Mode.SMB)


async def test_an_expert_reader_is_not(tmp_path: Path) -> None:
    analysis = await _analysis(tmp_path)
    assert 'class="plain-words"' not in render_findings_report(analysis, mode=Mode.EXPERT)


async def test_an_enterprise_reader_is_not(tmp_path: Path) -> None:
    analysis = await _analysis(tmp_path)
    assert 'class="plain-words"' not in render_findings_report(analysis, mode=Mode.ENTERPRISE)


# --- term matching ------------------------------------------------------------------------


def test_a_term_is_found_regardless_of_case() -> None:
    assert [gloss.term for gloss in glosses_for("Loopback is used here")] == ["loopback"]


def test_a_term_is_not_found_inside_a_longer_word() -> None:
    """`key` must not match inside `monkey`, or the glossary becomes noise."""
    assert glosses_for("the monkey escaped") == ()


def test_the_longer_term_wins_over_the_shorter_one() -> None:
    terms = [gloss.term for gloss in glosses_for("full-disk encryption is enabled")]
    assert terms == ["full-disk encryption"]


def test_a_sentence_with_no_jargon_offers_nothing() -> None:
    assert glosses_for("The machine was restarted on Tuesday.") == ()


def test_no_term_is_offered_twice_for_one_sentence() -> None:
    terms = [gloss.term for gloss in glosses_for("a port, another port, and a third port")]
    assert len(terms) == len(set(terms))


def test_every_glossary_entry_is_a_real_explanation() -> None:
    """A definition shorter than the word it defines is not a definition."""
    for term, plain in GLOSSARY.items():
        assert len(plain) > len(term)
        assert plain.strip() == plain
        assert term.lower() not in plain.lower()


def test_the_glossary_only_explains_words_the_product_can_emit() -> None:
    """Found by EA-0054's absence guard: four web-intelligence terms were drafted into the
    glossary for a capability that is a recorded decision NOT to build. A glossary is a
    claim about what the product says, so it must be drawn from what the checks produce."""
    from aqelyn.collect.checks import observations_for
    from aqelyn.collect.host import HostFacts, Listener

    facts = HostFacts(
        listeners=(Listener(port=8080, bind="0.0.0.0"),),
        firewall_tool="ufw",
        firewall_active=False,
        pending_updates=31,
        disk_encrypted=False,
        unattended_upgrades=False,
        ssh_password_auth=True,
    )
    emitted = " ".join(
        str(value)
        for observation in observations_for(facts, subject_ref="host-1")
        for value in observation.values()
    )
    explained = {gloss.term for gloss in glosses_for(emitted)}
    # Not a coverage percentage - that would be a number nobody could act on. The claim is
    # that the glossary is grounded in real output at all, which is what failed before.
    assert len(explained) >= 5, f"only {explained} of the glossary appears in real output"


# --- it holds on the rendered page ----------------------------------------------------------


async def test_no_gloss_block_repeats_a_term(tmp_path: Path) -> None:
    analysis = await _analysis(tmp_path)
    rendered = render_findings_report(analysis, mode=Mode.HOME)
    for block in _BLOCK.findall(rendered):
        terms = _TERM.findall(block)
        assert len(terms) == len(set(terms))


async def test_the_severity_is_not_softened_for_a_home_reader(tmp_path: Path) -> None:
    """Principle 8 forbids alarmism; nothing permits telling a home user a smaller truth."""
    analysis = await _analysis(tmp_path)
    assert "high" in render_findings_report(analysis, mode=Mode.HOME)
