import csv, os, sys
d = sys.argv[1]
rows = list(csv.DictReader(open(os.path.join(d, "results/macro_calendar.csv"))))
L = ["| event | reference | date (ET) | time (ET) | UTC | UTC offset |", "|---|---|---|---|---|---:|"]
for r in rows:
    L.append("| %s | %s | %s | %s | %s | %s |" % (r["event"], r["reference"], r["date_et"], r["time_et"], r["utc"], r["utc_offset_h"]))
parts = [open(os.path.join(d, "results", n)).read() for n in ("RESULTS_head.md", "tables.md", "RESULTS_tail.md")]
open(os.path.join(d, "RESULTS.md"), "w").write("".join(parts) + "\n".join(L) + "\n")
print(len(rows))
