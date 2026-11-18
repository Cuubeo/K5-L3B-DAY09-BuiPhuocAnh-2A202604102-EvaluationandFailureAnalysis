"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    pm = pr.get("manifest") or {}
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]

    # 1. metric values must be finite numbers (NaN < min is False: a naive gate lets it through)
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (NaN/inf)")
    for m in spec.get("metrics", []):
        if m["id"] in graded and (pr.get("metrics") or {}).get(m["id"]) is None and m.get("blocking"):
            problems.append(f"blocking metric {m['id']} missing from the report")

    # 2. evaluator crashes and missing per-row values
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s): {pr['evaluator_failures'][0]}")
    rows = pr.get("rows") or []
    for mid in graded:
        missing = [f"{r.get('item_id')}@{r.get('seed')}" for r in rows if _not_a_value(r.get(mid))]
        if missing:
            problems.append(f"metric {mid}: {len(missing)} row(s) with no value (e.g. {missing[0]})")

    # 3. row count and (item, seed) coverage: no dropped, duplicated or cherry-picked rows
    want_n = int(pm.get("items") or 0) * len(pm.get("seeds") or [])
    if len(rows) != want_n:
        problems.append(f"{len(rows)} rows, manifest says {pm.get('items')} items x {len(pm.get('seeds') or [])} seeds = {want_n}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    if len(set(keys)) != len(keys):
        problems.append(f"{len(keys) - len(set(keys))} duplicated (item, seed) row(s)")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if set(keys) != base_keys:
        only_pr, only_base = len(set(keys) - base_keys), len(base_keys - set(keys))
        problems.append(f"(item, seed) set differs from baseline: {only_base} missing, {only_pr} extra")
    bm = base.get("manifest") or {}
    if sorted(pm.get("seeds") or []) != sorted(bm.get("seeds") or []):
        problems.append(f"seeds {pm.get('seeds')} differ from baseline seeds {bm.get('seeds')}")
    if pm.get("items") != bm.get("items"):
        problems.append(f"item count {pm.get('items')} differs from baseline {bm.get('items')}")

    # 4. reported metrics must be what the rows say (hand-edited / recomputed-on-a-subset numbers)
    for mid in graded:
        vals = [r[mid] for r in rows if mid in r and not _not_a_value(r[mid])]
        rep = (pr.get("metrics") or {}).get(mid)
        if not vals or not isinstance(rep, (int, float)) or not math.isfinite(rep):
            continue
        safety = any(m["id"] == mid and m.get("kind") == "safety" for m in spec.get("metrics", []))
        want = sum(map(bool, vals)) if safety else sum(map(bool, vals)) / len(vals)
        if abs(float(rep) - want) > 1e-3:
            problems.append(f"metric {mid} reported {rep} but its rows give {round(want, 4)}")

    # 5. slice tags must match the baseline's (relabelling an item out of a slice hides it)
    tags = lambda rep: {r.get("item_id"): sorted(r.get("slices") or []) for r in rep.get("rows") or []}
    pt, bt = tags(pr), tags(base)
    moved = sorted(i for i in pt.keys() & bt.keys() if pt[i] != bt[i])
    if moved:
        problems.append(f"slice tags differ from baseline on {len(moved)} item(s), e.g. {moved[0]}: {bt[moved[0]]} -> {pt[moved[0]]}")

    # 6. ratchet: same eval-set version => thresholds may only get stricter
    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def _not_a_value(v) -> bool:
    return v is None or (isinstance(v, float) and not math.isfinite(v))


def _looser(th: dict, base_th: dict) -> list[str]:
    out = []
    for k in ("max", "max_increase"):
        if k in base_th and (k not in th or th[k] > base_th[k]):
            out.append(f"{k} {base_th[k]} -> {th.get(k, 'removed')}")
    if "min" in base_th and ("min" not in th or th["min"] < base_th["min"]):
        out.append(f"min {base_th['min']} -> {th.get('min', 'removed')}")
    if base_th.get("no_significant_drop") and not th.get("no_significant_drop"):
        out.append("no_significant_drop removed")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []                         # a new eval-set version starts a new baseline
    problems = []
    cur = {m["id"]: m for m in spec.get("metrics", [])}
    for bm in base_spec.get("metrics", []):
        m = cur.get(bm["id"])
        if m is None:
            problems.append(f"ratchet: metric {bm['id']} removed")
            continue
        if bm.get("blocking") and not m.get("blocking"):
            problems.append(f"ratchet: metric {bm['id']} no longer blocking")
        problems += [f"ratchet: metric {bm['id']} {x}" for x in _looser(m.get("threshold") or {}, bm.get("threshold") or {})]
    key = lambda s: (s.get("name"), s.get("metric"))
    cur_s = {key(s): s for s in spec.get("slices") or []}
    for bs in base_spec.get("slices") or []:
        s = cur_s.get(key(bs))
        name = f"slice {bs.get('name')}/{bs.get('metric')}"
        if s is None:
            problems.append(f"ratchet: {name} removed")
            continue
        if bs.get("blocking", True) and not s.get("blocking", True):
            problems.append(f"ratchet: {name} no longer blocking")
        problems += [f"ratchet: {name} {x}" for x in _looser(s, bs)]
    if spec.get("seeds") != base_spec.get("seeds"):
        problems.append(f"ratchet: seeds changed {base_spec.get('seeds')} -> {spec.get('seeds')}")
    for k in ("eval_set", "labels", "adversarial_pack"):
        if base_spec.get(k) != spec.get(k):
            problems.append(f"ratchet: {k} changed {base_spec.get(k)} -> {spec.get(k)}")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, mid = s["name"], s["metric"]
        sid = f"slice:{name}/{mid}"
        a = per_item(pr, mid, slice_name=name)
        verdict, note = "ok", ""
        val = round(sum(a.values()) / len(a), 4) if a else None
        if val is None:
            verdict = "missing"           # an empty slice cannot vouch for anything
        elif "min" in s and val < s["min"]:
            verdict = "fail"
        if s.get("no_significant_drop") and a:
            b = per_item(base, mid, slice_name=name)
            keys = sorted(set(a) & set(b))
            if keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        blocking = s.get("blocking", True)
        if verdict != "ok" and blocking:
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if blocking else "warn")
        th = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
