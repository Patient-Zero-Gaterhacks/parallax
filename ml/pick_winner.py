"""Pick the shipping model from the full run's validation report. Rules fixed before the run:
the full model wins only if, against trial-fix on the same validation panel,
  * whole-page clean flagged (any chunk >= 0.85) is no worse
  * web twin false alarms (0.5) are no worse
  * email holds: attack recall no lower and false alarms no higher (0.5)
  * probe_business stays at 2/20 threats or fewer
Otherwise trial-fix wins.

    python ml/pick_winner.py models/full-run/trial_report.json winner.json
"""
import json
import sys


def n(cell):            # ["30/604", 0.05] -> 30
    return int(cell[0].split("/")[0])


def main():
    rep = json.load(open(sys.argv[1]))
    new, old = rep["VALIDATION: new trial"], rep["VALIDATION: trial-windows"]  # "trial-windows" key = the --compare model
    c85, c50 = "threshold 0.85", "threshold 0.5"
    page = "whole page clean flagged (any chunk >= th)"
    threats = int(rep["probe_business: new trial"].split("/")[0])
    checks = {
        "whole-page clean flagged (0.85) no worse": (n(new[c85][page]) <= n(old[c85][page]), new[c85][page][0], old[c85][page][0]),
        "web twin false alarms (0.5) no worse": (n(new[c50]["web twin false alarms"]) <= n(old[c50]["web twin false alarms"]),
                                                 new[c50]["web twin false alarms"][0], old[c50]["web twin false alarms"][0]),
        "email attack recall (0.5) no lower": (n(new[c50]["email attack recall"]) >= n(old[c50]["email attack recall"]),
                                               new[c50]["email attack recall"][0], old[c50]["email attack recall"][0]),
        "email false alarms (0.5) no higher": (n(new[c50]["email false alarms"]) <= n(old[c50]["email false alarms"]),
                                               new[c50]["email false alarms"][0], old[c50]["email false alarms"][0]),
        "probe_business threats <= 2/20": (threats <= 2, rep["probe_business: new trial"], "-"),
    }
    winner = "full-run" if all(ok for ok, _, _ in checks.values()) else "trial-fix"
    out = {"winner": winner, "checks": {k: {"pass": ok, "full-run": a, "trial-fix": b} for k, (ok, a, b) in checks.items()}}
    json.dump(out, open(sys.argv[2], "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
