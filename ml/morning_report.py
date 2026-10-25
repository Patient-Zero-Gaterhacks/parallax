"""Write /workspace/morning_report.md from the overnight run's outputs.

    python ml/morning_report.py <state dir> <full-run report json> <report.md> [log]
"""
import json
import re
import sys
from pathlib import Path


def load(p):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return None


def table(title, models, rows_by_model, th):
    keys = list(next(iter(rows_by_model.values()))[th].keys())
    lines = [f"**{title} ({th})**", "", "| | " + " | ".join(models) + " |", "|---|" + "---|" * len(models)]
    for k in keys:
        cells = []
        for m in models:
            v = rows_by_model[m].get(th, {}).get(k)
            cells.append(v[0] if isinstance(v, list) else ("-" if v is None else str(v)))
        lines.append(f"| {k} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def dict_md(d, depth=0):
    out = []
    for k, v in d.items():
        if isinstance(v, dict):
            out.append("  " * depth + f"- **{k}**")
            out += dict_md(v, depth + 1)
        else:
            out.append("  " * depth + f"- {k}: {v}")
    return out


def main():
    state, rep_path, md_path = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    rep, win, off = load(rep_path), load(state / "winner.json"), load(state / "official.json")
    status = (state / "training_status").read_text().strip() if (state / "training_status").exists() else "unknown"
    steps = [l.split() for l in (state / "steps.txt").read_text().splitlines()] if (state / "steps.txt").exists() else []
    md = ["# Overnight run: morning report", ""]

    md += ["## Winner", ""]
    if status != "ok":
        md += [f"**Training did not finish ({status}). trial-fix is the shipping model.** No official tests were run "
               "(the plan stops on a training crash). See the error in /workspace/overnight.log.", ""]
    elif win:
        md += [f"**{win['winner']}** ships.", "", "| rule (decided before the run) | pass | full-run | trial-fix |", "|---|---|---|---|"]
        md += [f"| {k} | {'yes' if c['pass'] else 'NO'} | {c['full-run']} | {c['trial-fix']} |" for k, c in win["checks"].items()]
        md += [""]
    else:
        md += ["Winner could not be decided (pick_winner failed); trial-fix ships by default.", ""]

    if rep and status == "ok":
        md += ["## Validation (same panel as trial-fix; development decisions only)", ""]
        models = {"full-run": "VALIDATION: new trial", "trial-fix": "VALIDATION: trial-windows", "V2": "VALIDATION: V2"}
        rows = {m: rep[k] for m, k in models.items() if k in rep}
        for th in ("threshold 0.5", "threshold 0.85"):
            md += [table("Validation", list(rows), rows, th), ""]
        for m, k in models.items():
            if k in rep:
                md += [f"- {m}: attack minus twin score {rep[k]['attack minus twin score']}; "
                       f"attacked minus clean page {rep[k]['attacked page minus clean page score']}"]
        md += [f"- probe_business: full-run {rep.get('probe_business: new trial')}, trial-fix "
               f"{rep.get('probe_business: trial-windows')}, V2 {rep.get('probe_business: V2')}",
               f"- save/reload parity (full-run): {rep.get('save/reload parity (20 val examples)')}",
               f"- CPU timing (full-run): {rep.get('CPU time (pod CPU, 8 threads, product TransformerDetector, saved dtype)')}",
               f"- validation panel identical to trial-fix's: {rep.get('validation panel identical to the trial' + chr(39) + 's', 'not checked')}",
               f"- full-run validation setup: {rep.get('full-run validation')}",
               f"- represented pairs (train): {json.dumps({k: v for k, v in rep.get('represented pairs (train)', {}).items() if k != 'by placement'})}",
               f"- final training counts: {rep.get('final training counts')}",
               f"- training: {rep.get('training')}", ""]

    md += ["## Official test (run once, winner + V2 only)", ""]
    if off:
        md += [f"Model: `{off['model']}`. Page rule: {off['page rule']}." + (" **SELF-CHECK ONLY, not real results.**" if off.get("self_check") else ""), ""]
        for section in ("set sizes", "BrowseSafe++ test: excluded / unrepresented", "BrowseSafe++ test (page mode)",
                        "AgentDojo", "BIPIA test", "hand-written set"):
            if section in off:
                md += [f"### {section}", ""] + dict_md(off[section]) + [""]
        for f, title in (("eval_pipeline.txt", "Existing hand-written pipeline table (ml/eval_pipeline.py)"),
                         ("eval_external.txt", "Existing AgentDojo pipeline table (ml/eval_external.py)")):
            if (state / f).exists():
                md += [f"### {title}", "", "```", (state / f).read_text().strip()[-6000:], "```", ""]
    else:
        md += ["Not run." + (" (training did not finish)" if status != "ok" else " Check overnight.log."), ""]

    md += ["## Runtimes", "", "| step | exit code | minutes |", "|---|---|---|"]
    md += [f"| {s[0]} | {s[1]} | {int(s[2]) / 60:.1f} |" for s in steps if len(s) == 3]
    md += [""]

    md += ["## Failures and things that looked off", ""]
    log_path = Path(sys.argv[4] if len(sys.argv) > 4 else "/workspace/overnight.log")
    log = log_path.read_text(errors="replace") if log_path.exists() else ""
    issues = [f"- step `{s[0]}` exited with code {s[1]}" for s in steps if len(s) == 3 and s[1] != "0"]
    issues += [f"- log: `{l.strip()[:200]}`" for l in log.splitlines()
               if re.search(r"Traceback|Error|MISMATCH|nan|out of memory", l) and "UserWarning" not in l][:15]
    if rep and rep.get("training") and rep["training"].get("rows seen", 0) < rep["training"].get("rows available", 0) - 32:
        issues.append(f"- training stopped before a full pass: {rep['training']}")
    md += issues or ["- nothing flagged automatically"]
    Path(md_path).write_text("\n".join(md) + "\n")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
