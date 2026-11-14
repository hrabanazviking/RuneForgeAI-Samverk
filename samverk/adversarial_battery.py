"""Adversarial battery (S-311).

Roadmap S-311: Adversarial battery -- scanner
 scanner evasion attempts, SARIF fuzzing, signature
spoofing attempts: the suite attacks Samverk and
reports honestly.

Parts I--XV built the defences one slice at a
time and proved each on its own battery: S-289's
published-shape secret patterns, S-290's generic
entropy-and-context detection, S-291's push
scanning over both layers, S-302's SARIF schema
judgement, S-303's SARIF fingerprint dedup, and
S-305's signed-commit verification. This slice is
the first battery whose subject is the *seams
between* those defences, attacked the way an
adversary attacks them:

- **Scanner evasion.** A synthetic shaped token
  (and a synthetic unshaped secret) is mutated --
  split, encoded, homoglyphed, case-shifted,
  punctuation-broken -- and each mutation is
  judged by the real standing layers (`scan_text`,
  `scan_generic`, and S-291's `scan_blob_text`).
  A mutation the layers still catch is `caught`;
  one they do not is `missed`, named in the
  report's honest-gaps list, never smoothed over.
  Encoding a secret (base64, hex, reversal) is a
  real, standing gap of shape-based scanning and
  this battery says so in its own output.
- **SARIF fuzzing.** Mutated SARIF documents --
  wrong types, spoofed levels, missing messages,
  run-count overflow, non-object documents -- are
  judged by S-302's real `sarif_problems`; a
  document the judge refuses is `refused`, one it
  accepts is `accepted` (named, with the reason
  the schema permits it), and any exception is
  `crashed`, which is a defect this battery
  exists to expose. Dedup spoofs are judged by
  S-303's real `extract_findings`: a re-labelled
  duplicate that still collapses is `deduped`; a
  moved finding that must not collapse is judged
  on whether it survived as its own finding.
- **Signature spoofing.** Real Ed25519 SSH
  signatures are framed in-process (the S-305
  battery's SSHSIG framing) and then attacked:
  wrong key, tampered payload, wrong namespace,
  truncated or garbled armour, a signature
  smuggled in the commit *body*, and a valid
  signature hidden behind a bogus first header.
  Each is judged by S-305's real `verify_ssh` /
  `extract_signature`: verification is
  `accepted` only for the unmutated control;
  every spoof must be `rejected`. OpenPGP spoofs
  are covered at the extraction seam only --
  real OpenPGP verification is gpg's, proven by
  S-305's own battery; this battery claims no
  more than it runs.
- **Pure, and honest by construction.** The
  battery stores nothing, audits nothing, and
  needs no migration: it is a judgement over
  synthetic inputs, run on demand. Every verdict
  is computed by calling the real defence, never
  asserted by the attack's author; the published
  counts below are re-measured by the battery's
  own tests, which refuse any drift. 135 events
  stand: 33 auth / 89 repo / 13 admin. Schema
  stands at 128.
"""

from __future__ import annotations

import base64
import hashlib
import struct
from dataclasses import dataclass

from .code_scanning import MAX_RUNS_PER_UPLOAD, sarif_problems
from .code_scanning_alerts import extract_findings
from .commit_signatures import (
    CommitSignatureError, extract_signature, verify_ssh)
from .escaping import escape_html_text
from .generic_secret_detection import scan_generic
from .push_scanning import scan_blob_text
from .secret_scanning import scan_text

FAMILY_EVASION = "scanner_evasion"
FAMILY_SARIF = "sarif_fuzzing"
FAMILY_SIGNATURE = "signature_spoofing"
FAMILIES = (FAMILY_EVASION, FAMILY_SARIF, FAMILY_SIGNATURE)

# The synthetic shaped token every evasion attack
# mutates: ghp_ plus 36 alphanumeric characters,
# assembled to S-289's published shape. No real
# credential appears anywhere in this module.
SYNTHETIC_TOKEN = "ghp_" + "Ab3dEf6hIjKlMnOpQrStUvWxYz0123456789"
# The synthetic unshaped secret for the generic
# layer: forty unmarked high-entropy characters.
SYNTHETIC_SECRET = "xK9mQ2vR7zLp4nW8bT3cF6hJ1sD5gA0e"
# The same class of secret with shell/symbol
# punctuation through it: the generic layer
# tokenises on those characters, so the candidate
# fragments -- a standing, named gap.
SYNTHETIC_SECRET_SYMBOLIC = "xK9$mQ2!vR7#zLp4&nW8*bT3^cF6)hJ1"


@dataclass(frozen=True)
class AttackResult:
    """One attack and the defence's real verdict.
    `outcome` is in the family's vocabulary:
    evasion -- caught / missed; SARIF -- refused /
    accepted / crashed / deduped / not_deduped;
    signature -- accepted / rejected / crashed."""
    family: str
    name: str
    target: str
    outcome: str
    detail: str

    def to_dict(self) -> dict:
        return {"family": self.family, "name": self.name,
                "target": self.target, "outcome": self.outcome,
                "detail": self.detail}


@dataclass(frozen=True)
class BatteryReport:
    """The whole battery's honest account."""
    results: tuple

    def counts(self) -> dict:
        out: dict = {}
        for r in self.results:
            key = f"{r.family}:{r.outcome}"
            out[key] = out.get(key, 0) + 1
        return out

    def family_results(self, family: str) -> tuple:
        return tuple(r for r in self.results if r.family == family)

    def honest_gaps(self) -> tuple:
        """Every attack the defences did not stop,
        named: an evasion that was missed, a spoofed
        signature that was accepted, a fuzzed
        document that crashed its judge. Accepted
        SARIF documents are schema-permitted by
        design and are named in their own details,
        not counted as gaps."""
        gaps = []
        for r in self.results:
            if r.outcome in ("missed", "crashed"):
                gaps.append(r)
            elif r.family == FAMILY_SIGNATURE \
                    and r.outcome == "accepted" \
                    and not r.name.startswith("control"):
                gaps.append(r)
        return tuple(gaps)

    def to_dict(self) -> dict:
        return {
            "attacks": [r.to_dict() for r in self.results],
            "counts": self.counts(),
            "honest_gaps": [r.name for r in self.honest_gaps()],
        }


# ---------------------------------------------------------------------
# Family 1 -- scanner evasion
# ---------------------------------------------------------------------

def _pattern_verdict(text: str) -> tuple:
    findings = scan_text(text)
    return ("caught" if findings else "missed"), findings


def _generic_verdict(text: str) -> tuple:
    findings = scan_generic(text)
    return ("caught" if findings else "missed"), findings


def _evasion_attacks() -> tuple:
    """(name, target, text, judge) -- the judge is
    the real layer the attack aims at."""
    tok = SYNTHETIC_TOKEN
    body = tok[4:]
    zw = "\u200b"
    fullwidth = "".join(
        chr(0xFF01 + ord(c) - 0x21) if 0x21 <= ord(c) <= 0x7E
        else c for c in tok)
    return (
        ("control_plain_token", "pattern", f"token = {tok}", "pattern"),
        ("split_across_lines", "pattern",
         "token = " + tok[:20] + "\n" + tok[20:], "pattern"),
        ("split_with_space", "pattern",
         "token = " + tok[:20] + " " + tok[20:], "pattern"),
        ("split_with_html_comment", "pattern",
         "token = " + tok[:14] + "<!-- -->" + tok[14:], "pattern"),
        ("zero_width_inserted", "pattern",
         "token = " + zw.join(tok[i:i + 5] for i in range(0, len(tok), 5)), "pattern"),
        ("base64_encoded", "pattern",
         "token = " + base64.b64encode(tok.encode()).decode(), "pattern"),
        ("hex_encoded", "pattern", "token = " + tok.encode().hex(), "pattern"),
        ("reversed", "pattern", "token = " + tok[::-1], "pattern"),
        ("prefix_case_mutated", "pattern", "token = GHP_" + body, "pattern"),
        ("prefix_underscore_swapped", "pattern", "token = ghp-" + body, "pattern"),
        ("dashes_inserted", "pattern",
         "token = " + "-".join(tok[i:i + 4] for i in range(0, len(tok), 4)), "pattern"),
        ("fullwidth_homoglyphs", "pattern", "token = " + fullwidth, "pattern"),
        ("cyrillic_homoglyph", "pattern",
         "token = ghp_" + "\u0410" + body[1:], "pattern"),
        ("quoted_printable_underscore", "pattern",
         "token = ghp=5F" + body, "pattern"),
        ("control_generic_secret", "generic",
         f'api_secret = "{SYNTHETIC_SECRET}"', "generic"),
        ("generic_in_hash_context", "generic",
         f'commit = "{SYNTHETIC_SECRET}"', "generic"),
        ("generic_marked_example", "generic",
         f'api_secret = "example-{SYNTHETIC_SECRET}"', "generic"),
        ("generic_symbol_fragmented", "generic",
         f'api_secret = "{SYNTHETIC_SECRET_SYMBOLIC}"', "generic"),
        ("generic_split_across_lines", "generic",
         'api_secret = "' + SYNTHETIC_SECRET[:20] + '" + "'
         + SYNTHETIC_SECRET[20:] + '"', "generic"),
        ("combined_push_scan_plain", "combined",
         f"token = {tok}", "combined"),
        ("combined_push_scan_base64", "combined",
         "token = " + base64.b64encode(tok.encode()).decode(), "combined"),
    )


def run_scanner_evasion_battery() -> tuple:
    results = []
    for name, target, text, judge in _evasion_attacks():
        if judge == "pattern":
            outcome, findings = _pattern_verdict(text)
            detail = (f"pattern layer reported {len(findings)} finding(s)"
                      if findings else
                      "pattern layer reported no finding for the mutated token")
        elif judge == "generic":
            outcome, findings = _generic_verdict(text)
            detail = (f"generic layer reported {len(findings)} finding(s)"
                      if findings else
                      "generic layer reported no finding for the mutated secret")
        else:
            found, _p, _g = scan_blob_text(text)
            outcome = "caught" if found else "missed"
            detail = (f"push-scan seam reported {len(found)} finding(s)"
                      if found else
                      "push-scan seam reported no finding for the mutated token")
        results.append(AttackResult(
            family=FAMILY_EVASION, name=name, target=target,
            outcome=outcome, detail=detail))
    return tuple(results)


# ---------------------------------------------------------------------
# Family 2 -- SARIF fuzzing
# ---------------------------------------------------------------------

def _base_result(**overrides):
    result = {
        "ruleId": "R-1", "level": "error",
        "message": {"text": "something is wrong"},
        "locations": [{"physicalLocation": {
            "artifactLocation": {"uri": "src/app.py"},
            "region": {"startLine": 7, "startColumn": 3}}}],
    }
    result.update(overrides)
    return result


def _base_doc(results=None, **run_overrides):
    run = {"tool": {"driver": {"name": "FuzzTool"}},
           "results": [_base_result()] if results is None else results}
    run.update(run_overrides)
    return {"version": "2.1.0", "runs": [run]}


def _sarif_cases() -> tuple:
    deep = {}
    node = deep
    for _ in range(60):
        node["nest"] = {}
        node = node["nest"]
    no_message = _base_result()
    del no_message["message"]
    empty_message = _base_result(message={})
    moved = _base_result()
    moved["locations"] = [{"physicalLocation": {
        "artifactLocation": {"uri": "src/app.py"},
        "region": {"startLine": 99, "startColumn": 3}}}]
    return (
        ("control_valid_document", "validate", _base_doc()),
        ("version_missing", "validate",
         {"runs": _base_doc()["runs"]}),
        ("version_spoofed_trailing_space", "validate",
         {"version": "2.1.0 ", "runs": _base_doc()["runs"]}),
        ("version_wrong_type", "validate",
         {"version": 2.1, "runs": _base_doc()["runs"]}),
        ("runs_not_an_array", "validate",
         {"version": "2.1.0", "runs": {"tool": {}}}),
        ("runs_empty", "validate", {"version": "2.1.0", "runs": []}),
        ("runs_over_limit", "validate",
         {"version": "2.1.0",
          "runs": [_base_doc()["runs"][0]] * (MAX_RUNS_PER_UPLOAD + 1)}),
        ("level_uppercase_spoof", "validate",
         _base_doc(results=[_base_result(level="ERROR")])),
        ("level_invented_severity", "validate",
         _base_doc(results=[_base_result(level="critical")])),
        ("message_missing", "validate", _base_doc(results=[no_message])),
        ("message_empty_object", "validate",
         _base_doc(results=[empty_message])),
        ("message_id_only", "validate",
         _base_doc(results=[_base_result(message={"id": "m-1"})])),
        ("result_not_an_object", "validate",
         _base_doc(results=["not-a-result"])),
        ("locations_not_an_array", "validate",
         _base_doc(results=[_base_result(locations={"x": 1})])),
        ("tool_name_empty", "validate",
         _base_doc(tool={"driver": {"name": ""}})),
        ("document_is_a_list", "validate", [1, 2, 3]),
        ("document_is_a_string", "validate", "not sarif"),
        ("document_is_none", "validate", None),
        ("deep_nesting_in_properties", "validate",
         _base_doc(properties=deep)),
        ("duplicate_results_dedup", "dedup",
         _base_doc(results=[_base_result(), _base_result()])),
        ("moved_result_not_deduped", "dedup",
         _base_doc(results=[_base_result(), moved])),
        ("partial_fingerprint_spoof", "dedup",
         _base_doc(results=[
             _base_result(partialFingerprints={"primary": "abc"}),
             dict(_base_result(partialFingerprints={"primary": "abc"}),
                  locations=moved["locations"])])),
    )


def run_sarif_fuzz_battery() -> tuple:
    results = []
    for name, kind, document in _sarif_cases():
        try:
            if kind == "dedup":
                found = extract_findings(document)
                if name == "moved_result_not_deduped":
                    outcome = "not_deduped" if len(found) == 2 else "deduped"
                    detail = (f"extract_findings kept {len(found)} distinct "
                              "finding(s) for two locations of one rule")
                else:
                    outcome = "deduped" if len(found) == 1 else "not_deduped"
                    detail = (f"extract_findings collapsed the pair to "
                              f"{len(found)} finding(s)")
                results.append(AttackResult(
                    family=FAMILY_SARIF, name=name, target="dedup",
                    outcome=outcome, detail=detail))
                continue
            problems = sarif_problems(document)
            outcome = "refused" if problems else "accepted"
            detail = ("judge named: " + "; ".join(problems[:3])
                      if problems else
                      "judge accepted the document (schema-permitted shape)")
        except Exception as exc:  # a crash is a finding, not a pass
            outcome = "crashed"
            detail = f"judge raised {type(exc).__name__}: {exc}"
        results.append(AttackResult(
            family=FAMILY_SARIF, name=name, target="sarif_schema",
            outcome=outcome, detail=detail))
    return tuple(results)


# ---------------------------------------------------------------------
# Family 3 -- signature spoofing
# ---------------------------------------------------------------------

def _ssh_string(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def _make_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)
    private = Ed25519PrivateKey.generate()
    raw_pub = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    blob = _ssh_string(b"ssh-ed25519") + _ssh_string(raw_pub)
    return private, blob


def _signed_data(namespace: str, hash_algo: str, payload: bytes) -> bytes:
    digest = hashlib.new(
        "sha512" if hash_algo == "sha512" else "sha256",
        payload).digest()
    return (b"SSHSIG" + _ssh_string(namespace.encode())
            + _ssh_string(b"") + _ssh_string(hash_algo.encode())
            + _ssh_string(digest))


def _sign(private, key_blob: bytes, payload: bytes,
          namespace: str = "git") -> str:
    """One real SSH signature armour over *payload*."""
    signature = private.sign(_signed_data(namespace, "sha256", payload))
    sig_blob = _ssh_string(b"ssh-ed25519") + _ssh_string(signature)
    blob = (b"SSHSIG" + struct.pack(">I", 1)
            + _ssh_string(key_blob) + _ssh_string(namespace.encode())
            + _ssh_string(b"") + _ssh_string(b"sha256")
            + _ssh_string(sig_blob))
    b64 = base64.b64encode(blob).decode()
    lines = [b64[i:i + 70] for i in range(0, len(b64), 70)]
    return ("-----BEGIN SSH SIGNATURE-----\n" + "\n".join(lines)
            + "\n-----END SSH SIGNATURE-----")


def _verify(payload: bytes, armour: str, key_blob: bytes) -> str:
    try:
        ok = verify_ssh(payload, armour, key_blob)
    except CommitSignatureError:
        return "rejected"
    except Exception:
        return "crashed"
    return "accepted" if ok else "rejected"


def _raw_commit(payload: bytes, armour: str,
                header: str = "gpgsig") -> bytes:
    head, _, message = payload.partition(b"\n\n")
    folded = armour.replace("\n", "\n ")
    return head + f"\n{header} {folded}".encode() + b"\n\n" + message


_PAYLOAD = (b"tree 0000000000000000000000000000000000000000\n"
            b"author Alice <alice@example.test> 1700000000 +0000\n"
            b"committer Alice <alice@example.test> 1700000000 +0000\n"
            b"\nhonest work\n")


def run_signature_spoof_battery() -> tuple:
    alice_priv, alice_blob = _make_key()
    mallory_priv, mallory_blob = _make_key()
    good = _sign(alice_priv, alice_blob, _PAYLOAD)
    cases = []
    def add(name, outcome, detail):
        cases.append(AttackResult(
            family=FAMILY_SIGNATURE, name=name,
            target="ssh_commit_signature", outcome=outcome,
            detail=detail))
    add("control_valid_signature", _verify(_PAYLOAD, good, alice_blob),
        "the unmutated control: a real signature under its own key")
    add("wrong_key_spoof",
        _verify(_PAYLOAD, _sign(mallory_priv, mallory_blob, _PAYLOAD),
                alice_blob),
        "a real signature, but under an attacker's key, judged against the victim's registered key")
    add("tampered_payload", _verify(_PAYLOAD + b"evil\n", good, alice_blob),
        "the honest signature replayed over a tampered payload")
    add("wrong_namespace",
        _verify(_PAYLOAD, _sign(alice_priv, alice_blob, _PAYLOAD,
                                 namespace="file"), alice_blob),
        "a signature framed for another namespace, replayed as a git signature")
    add("truncated_armour", _verify(_PAYLOAD, good[:len(good) // 2], alice_blob),
        "the armour cut in half")
    garbled = ("-----BEGIN SSH SIGNATURE-----\n!!!not-base64!!!\n"
               "-----END SSH SIGNATURE-----")
    add("garbled_base64_armour", _verify(_PAYLOAD, garbled, alice_blob),
        "armour whose body is not base64 at all")
    no_end = good.replace("-----END SSH SIGNATURE-----", "")
    add("missing_end_marker", _verify(_PAYLOAD, no_end, alice_blob),
        "armour with its END marker stripped")
    # Extraction-seam spoofs.
    body_only = _PAYLOAD + good.encode() + b"\n"
    ext = extract_signature(body_only)
    add("signature_in_message_body",
        "rejected" if not ext.header else "accepted",
        "a signature carried in the commit message body, where no header speaks")
    bogus_first = _raw_commit(_PAYLOAD, garbled).replace(
        b"\n\n", ("\ngpgsig " + good.replace("\n", "\n ")).encode() + b"\n\n", 1)
    ext2 = extract_signature(bogus_first)
    add("valid_signature_behind_bogus_header",
        _verify(ext2.payload, ext2.armour, alice_blob) if ext2.armour else "rejected",
        "a bogus first gpgsig header shadows the valid second one; only the first header speaks")
    tampered_raw = _raw_commit(_PAYLOAD, good).replace(b"honest work", b"forged work!")
    ext3 = extract_signature(tampered_raw)
    add("message_tampered_after_signing",
        _verify(ext3.payload, ext3.armour, alice_blob) if ext3.armour else "rejected",
        "the signed commit with its message rewritten after signing")
    upper_raw = _raw_commit(_PAYLOAD, good, header="GPGSIG")
    ext4 = extract_signature(upper_raw)
    add("control_uppercase_header_name",
        _verify(ext4.payload, ext4.armour, alice_blob) if ext4.armour else "rejected",
        "header names are case-insensitive in git; the valid signature still verifies -- accepted because the signature is real, not because the case hid anything")
    return tuple(cases)


# ---------------------------------------------------------------------
# The whole battery + its page face
# ---------------------------------------------------------------------

# Published counts, re-measured by the battery's
# tests: any drift turns the build red.
PUBLISHED_ATTACK_COUNT = 54


def run_full_battery() -> BatteryReport:
    return BatteryReport(results=(
        run_scanner_evasion_battery()
        + run_sarif_fuzz_battery()
        + run_signature_spoof_battery()))


def render_adversarial_battery_page(report: BatteryReport,
                                    title: str = "Adversarial battery") -> str:
    counts = report.counts()
    rows = []
    for r in report.results:
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td>"
            "<td>{}</td></tr>".format(
                escape_html_text(r.family), escape_html_text(r.name),
                escape_html_text(r.target), escape_html_text(r.outcome),
                escape_html_text(r.detail)))
    gaps = report.honest_gaps()
    gap_items = "".join(
        f"<li>{escape_html_text(g.name)} -- {escape_html_text(g.detail)}</li>"
        for g in gaps) or "<li>none</li>"
    summary = "; ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    return (
        f"<h1>{escape_html_text(title)}</h1>"
        f"<p>{escape_html_text(summary)}</p>"
        f"<h2>Honest gaps</h2><ul>{gap_items}</ul>"
        f"<table>{''.join(rows)}</table>")
