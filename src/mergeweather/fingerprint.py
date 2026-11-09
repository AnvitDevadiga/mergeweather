"""Failure fingerprints: a stable identity for "the same failure".

A fingerprint combines the outcome class with a normalized signature extracted
from the test output. Volatile details (numbers, hex addresses, temp paths,
timings) are normalized away so the same assertion failing with slightly
different values still matches.
"""

from __future__ import annotations

import hashlib
import re

DEFAULT_SIGNATURE_REGEX = r"(Error|Exception|FAIL|Failed|failed|assert|Traceback|panic)"

_NORMALIZERS = [
    (re.compile(r"0x[0-9a-fA-F]+"), "0x?"),
    (re.compile(r"(/[\w.\-]+)*/mergeweather-[\w]+(/[\w.\-]+)*"), "<path>"),
    (re.compile(r"/(tmp|var|private|work)(/[\w.\-]+)+"), "<path>"),
    (re.compile(r"\d+(\.\d+)?"), "#"),
    (re.compile(r"\s+"), " "),
]


def normalize(line: str) -> str:
    for pat, rep in _NORMALIZERS:
        line = pat.sub(rep, line)
    return line.strip()


def signature(stdout: str, stderr: str, regex: str | None = None, max_lines: int = 5) -> list[str]:
    pat = re.compile(regex or DEFAULT_SIGNATURE_REGEX)
    lines = [l for l in (stdout + "\n" + stderr).splitlines() if pat.search(l)]
    lines = [l for l in lines if not l.strip().startswith("File ")]
    return [normalize(l) for l in lines[-max_lines:]]


def fingerprint(
    outcome: str, exit_code: int | None, stdout: str, stderr: str, regex: str | None = None
) -> tuple[str, list[str]]:
    if outcome == "pass":
        return "pass", []
    if outcome == "timeout":
        return "timeout", []
    if outcome == "error":
        return "infra-error", []
    sig = signature(stdout, stderr, regex)
    material = f"exit={exit_code}\n" + "\n".join(sig)
    return "fail:" + hashlib.sha256(material.encode()).hexdigest()[:12], sig
