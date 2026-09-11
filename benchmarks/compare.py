"""Compare benchmark medians after checking workload and output equivalence."""

import argparse
import json
from pathlib import Path


def compare(before: dict, after: dict) -> str:
    for key in (
        "schema",
        "rows",
        "repeats",
        "memory_rows",
        "harness_sha256",
        "python",
        "platform",
        "machine",
    ):
        if before[key] != after[key]:
            raise ValueError(f"incomparable benchmark metadata: {key}")
    if before["results"].keys() != after["results"].keys():
        raise ValueError("incomparable case sets")
    if before["schema"] != "ton.benchmark/v2":
        raise ValueError("expected ton.benchmark/v2 reports")
    lines = [
        "| Case | Setup change | Run change | Setup allocation change | Run allocation change |",
        "|---|---:|---:|---:|---:|",
    ]
    for case, first in before["results"].items():
        second = after["results"][case]
        if first["parameters"] != second["parameters"]:
            raise ValueError(f"incomparable parameters: {case}")
        verify_outputs(case, first, second)
        changes = [
            change(first["timings"][key]["median"], second["timings"][key]["median"])
            for key in ("setup_seconds", "run_seconds")
        ]
        peaks = [
            change(first["memory_sample"][key], second["memory_sample"][key])
            for key in ("setup_peak_bytes", "run_peak_bytes")
        ]
        if not first["samples"][0].get("rows"):
            changes[1] = "—"
        lines.append(f"| {case} | {changes[0]} | {changes[1]} | {peaks[0]} | {peaks[1]} |")
    return "\n".join(lines) + "\n"


def verify_outputs(case, first, second):
    for key in ("rows", "characters", "sha256", "audit_characters", "audit_sha256"):
        expected = first["samples"][0].get(key)
        if any(s.get(key) != expected for s in (*first["samples"], *second["samples"])):
            raise ValueError(f"changed output for {case}: {key}")
        if first["memory_sample"].get(key) != second["memory_sample"].get(key):
            raise ValueError(f"changed memory workload for {case}: {key}")


def change(first: float, second: float) -> str:
    return f"{(second / first - 1) * 100:+.1f}%" if first else "—"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = compare(json.loads(args.before.read_text()), json.loads(args.after.read_text()))
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
