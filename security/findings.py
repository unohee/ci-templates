#!/usr/bin/env python3
# Created: 2026-11-20
# Purpose: turn the JSON reports of the local scanners (gitleaks, semgrep, osv-scanner) into one
#   ranked finding list, apply the accepting baseline, decide whether the gate fails, and print a
#   human table plus a machine summary. This is the gate half of security/scan.sh, the replacement
#   for GitHub Advanced Security (code scanning, secret scanning) and Code Quality, all dropped for
#   cost on 2026-11-20.
# Dependencies: standard library only.
# Test Status: security/test_findings.py.
#
#   python3 security/findings.py --gitleaks F.json --semgrep F.json --osv F.json \
#       [--baseline security/baseline.json] [--summary F.json] [--root DIR] [--tool NAME]...
#
# Gate policy (one sentence per line, the reasons in security/README.md):
#   secret   every finding blocks; a baseline entry with a reason accepts one.
#   sast     a result blocks at severity ERROR, and at WARNING when the rule declares
#            metadata.confidence: high (an error-only gate let a js/xss-through-dom
#            warning with security-severity 7.8 through; see AUD-3009).
#   deps     every known vulnerability blocks; a baseline entry with a reason accepts one.
# Exit: 0 nothing blocking, 1 at least one blocking finding, 2 a report could not be read.
import argparse
import json
import sys
from datetime import date
from pathlib import Path

TOOLS = ("secret", "sast", "deps", "quality")


class ReportError(Exception):
    """A report could not be read: the gate cannot say clean."""


def rel(path, root):
    """Paths come back absolute from the scanners; print them relative to the scan root."""
    if not path:
        return "?"
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except (ValueError, OSError):
        return str(path)


def load(path, what):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ReportError(f"{what}: {path}: {error}") from error


def gitleaks_findings(path, root):
    """gitleaks json is a flat list of leaks. The secret value is never kept."""
    data = load(path, "gitleaks")
    if not isinstance(data, list):
        raise ReportError(f"gitleaks: {path}: expected a list of findings")
    out = []
    for leak in data:
        out.append(
            {
                "tool": "secret",
                "severity": "error",
                "rule": leak.get("RuleID") or "unknown-rule",
                "path": rel(leak.get("File"), root),
                "line": leak.get("StartLine") or 0,
                # Description, not Secret/Match: a finding report must never carry the
                # secret itself into a CI log or a Slack channel.
                "message": (leak.get("Description") or "").strip(),
                "blocking": True,
            }
        )
    return out


def error_kind(error):
    """A short name for one entry of semgrep's `errors` array.

    `type` is normally a string ("Internal matching error"), but semgrep sets it to the rule's
    value list when the warning came from a pattern: element 0 is the name and the rest is the
    offending source. Printing that whole thing put 15 KB of parse detail into the log on
    de-artifact (79 entries, 2026-11-20), so only the name is kept.
    """
    kind = error.get("type")
    if isinstance(kind, str):
        return kind[:60] or "unnamed"
    if isinstance(kind, (list, tuple)) and kind and isinstance(kind[0], str):
        return kind[0][:60]
    return "unnamed"


def semgrep_findings(path, root):
    """Returns (findings, notes). A fatal error raises; a warning becomes a note.

    semgrep's `errors` array carries both: `level: "error"` is a scan that failed and cannot
    be called clean, while `level: "warn"` is what a rule engine records when it could not
    finish one pattern (an embedded PowerShell block in a workflow, a partial YAML parse).
    Treating the warning as fatal made every de-artifact run exit 2 on 79 such entries
    (2026-11-20); ignoring the error level would let a broken scan pass.
    """
    data = load(path, "semgrep")
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ReportError(f"semgrep: {path}: no results array")
    errors = data.get("errors") or []
    fatal = [e for e in errors if str(e.get("level") or "").lower() == "error"]
    if fatal:
        first = json.dumps(fatal[0])[:200]
        raise ReportError(f"semgrep: {path}: {len(fatal)} fatal error(s), first: {first}")
    notes = []
    if errors:
        kinds = {}
        for error in errors:
            kinds[str(error_kind(error))] = kinds.get(str(error_kind(error)), 0) + 1
        summary = ", ".join(f"{name} x{count}" for name, count in sorted(kinds.items()))
        notes.append(f"semgrep recorded {len(errors)} non-fatal warning(s): {summary}")
    out = []
    for result in data["results"]:
        extra = result.get("extra") or {}
        metadata = extra.get("metadata") or {}
        severity = (extra.get("severity") or "INFO").upper()
        confidence = str(metadata.get("confidence") or "").lower()
        blocking = severity == "ERROR" or (severity == "WARNING" and confidence == "high")
        start = result.get("start") or {}
        out.append(
            {
                "tool": "sast",
                "severity": severity.lower(),
                "rule": result.get("check_id") or "unknown-rule",
                "path": rel(result.get("path"), root),
                "line": start.get("line") or 0,
                "message": (extra.get("message") or "").strip().splitlines()[0][:300]
                if extra.get("message")
                else "",
                "confidence": confidence,
                "blocking": blocking,
            }
        )
    return out, notes


def osv_findings(path, root):
    data = load(path, "osv-scanner")
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ReportError(f"osv-scanner: {path}: no results array")
    out = []
    for entry in data["results"]:
        source = rel((entry.get("source") or {}).get("path"), root)
        for package in entry.get("packages") or []:
            pkg = package.get("package") or {}
            name = pkg.get("name") or "?"
            version = pkg.get("version") or "?"
            for vuln in package.get("vulnerabilities") or []:
                out.append(
                    {
                        "tool": "deps",
                        "severity": "high",
                        "rule": vuln.get("id") or "unknown-vuln",
                        "path": source,
                        "line": 0,
                        "message": f"{name} {version}: {(vuln.get('summary') or '')[:200]}".strip(),
                        "blocking": True,
                    }
                )
    return out


def baseline_keys(entries):
    """A baseline entry matches one finding exactly: tool, rule, path and line."""
    keys = {}
    for entry in entries or []:
        key = (entry.get("tool"), entry.get("rule"), entry.get("path"), entry.get("line") or 0)
        keys[key] = entry.get("reason") or "(no reason recorded)"
    return keys


def apply_baseline(findings, accepted):
    for finding in findings:
        key = (finding["tool"], finding["rule"], finding["path"], finding["line"] or 0)
        if key in accepted:
            finding["blocking"] = False
            finding["accepted"] = accepted[key]
    return findings


def load_baseline(path):
    if not path:
        return {}
    try:
        data = load(path, "baseline")
    except ReportError:
        # A missing baseline is a normal first run; an unreadable one is not, but the
        # caller passes the resolved path, so a missing file means "nothing accepted yet".
        if not Path(path).exists():
            return {}
        raise
    if isinstance(data, list):
        return baseline_keys(data)
    if isinstance(data, dict):
        return baseline_keys(data.get("accepted"))
    raise ReportError(f"baseline: {path}: expected an object with an 'accepted' list")


def render(findings, root):
    blocking = [f for f in findings if f["blocking"]]
    accepted = [f for f in findings if f.get("accepted")]
    informational = [f for f in findings if not f["blocking"] and not f.get("accepted")]
    for label, group in (("BLOCKING", blocking), ("accepted", accepted), ("reported", informational)):
        if not group:
            continue
        print(f"\n{label} ({len(group)})")
        for finding in sorted(group, key=lambda f: (f["tool"], f["path"], f["line"])):
            where = f"{finding['path']}:{finding['line']}" if finding["line"] else finding["path"]
            note = f"  [accepted: {finding['accepted']}]" if finding.get("accepted") else ""
            print(f"  {finding['tool']:<8} {finding['rule']:<40} {where}{note}")
            if finding["message"]:
                print(f"           {finding['message'][:160]}")
    print(
        f"\nfindings: {len(findings)} total, {len(blocking)} blocking, "
        f"{len(accepted)} accepted, {len(informational)} reported-only"
    )
    return blocking


def write_baseline(path, findings, reason, today):
    """Record the current blocking findings as accepted, with the given reason.

    This exists because a repository that never ran these scanners has a first run full of
    pre-existing findings, and a gate that blocks all of them on day one is switched off
    within a week. The reason is required and lands next to every entry, so the pull request
    that adds the file says what it is accepting and why.

    A finding path is kept relative to the scan root. An absolute one can never match a later
    run (the export directory changes every time), and it means the caller passed a root that
    is not where the scanners reported from: refusing is cheaper than a baseline that silently
    accepts nothing. scan.sh passes the right root when it is asked to write one.
    """
    accepted = sorted(
        (
            {
                "tool": f["tool"],
                "rule": f["rule"],
                "path": f["path"],
                "line": f["line"] or 0,
                "reason": reason,
                "added": today,
            }
            for f in findings
            if f["blocking"]
        ),
        key=lambda e: (e["tool"], e["path"], e["line"], e["rule"]),
    )
    absolute = sorted({entry["path"] for entry in accepted if entry["path"].startswith("/")})
    if absolute:
        raise ReportError(
            f"baseline: refusing to record the absolute path {absolute[0]}. Pass --root the "
            "directory the scanners reported from (scan.sh exports the tree and passes it), "
            "otherwise no entry can match a later run."
        )
    Path(path).write_text(
        json.dumps({"accepted": accepted}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"baseline: wrote {len(accepted)} accepted finding(s) to {path}")
    return accepted


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rank and gate the local scanner reports.")
    parser.add_argument("--gitleaks")
    parser.add_argument("--semgrep")
    parser.add_argument("--osv")
    parser.add_argument("--baseline")
    parser.add_argument("--summary")
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--write-baseline",
        metavar="FILE",
        help="record today's blocking findings as accepted; needs --baseline-reason",
    )
    parser.add_argument("--baseline-reason", help="why these findings are accepted")
    parser.add_argument("--today", default="", help="date recorded with a new baseline entry")
    args = parser.parse_args(argv)
    if args.write_baseline and not args.baseline_reason:
        print("findings: --write-baseline needs --baseline-reason", file=sys.stderr)
        return 2

    notes = []
    try:
        findings = []
        if args.gitleaks:
            findings += gitleaks_findings(args.gitleaks, args.root)
        if args.semgrep:
            sast, notes = semgrep_findings(args.semgrep, args.root)
            findings += sast
        if args.osv:
            findings += osv_findings(args.osv, args.root)
        findings = apply_baseline(findings, load_baseline(args.baseline))
    except ReportError as error:
        print(f"findings: {error}", file=sys.stderr)
        return 2

    for note in notes:
        print(f"note: {note}")

    if args.write_baseline:
        try:
            write_baseline(
                args.write_baseline,
                findings,
                args.baseline_reason,
                args.today or date.today().isoformat(),
            )
        except ReportError as error:
            print(f"findings: {error}", file=sys.stderr)
            return 2

    blocking = render(findings, args.root)

    if args.summary:
        counts = {tool: 0 for tool in TOOLS}
        blocks = {tool: 0 for tool in TOOLS}
        for finding in findings:
            counts[finding["tool"]] += 1
            if finding["blocking"]:
                blocks[finding["tool"]] += 1
        summary = {
            "total": len(findings),
            "blocking": len(blocking),
            "by_tool": counts,
            "blocking_by_tool": blocks,
            "findings": findings,
        }
        Path(args.summary).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"summary: {args.summary}")

    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
