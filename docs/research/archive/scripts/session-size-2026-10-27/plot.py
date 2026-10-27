import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
PROJECTS = [("KubeCoder", "#2a78d6"), ("Ansible", "#eb6834"), ("PilotApp", "#1baf7a")]
BIN = 20_000

rows = [r for r in json.load(open("sessions.json"))["rows"] if r["kind"] == "session"]
top = max(r["peak"] for r in rows)
nbins = top // BIN + 1
edges = [i * BIN for i in range(nbins + 1)]


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2})
fig, ax = plt.subplots(figsize=(11, 6), dpi=160)
fig.patch.set_facecolor(SURFACE)
ax.set_facecolor(SURFACE)

bottom = [0] * nbins
for name, color in PROJECTS:
    counts = [0] * nbins
    for r in rows:
        if r["project"] == name:
            counts[r["peak"] // BIN] += 1
    ax.bar([e + BIN / 2 for e in edges[:-1]], counts, width=BIN * 0.9, bottom=bottom,
           color=color, edgecolor=SURFACE, linewidth=1.2,
           label=f"{name}  (n={sum(counts):,})", zorder=3)
    bottom = [b + c for b, c in zip(bottom, counts, strict=True)]

all_peaks = [r["peak"] for r in rows]
for p, lab in ((0.5, "median"), (0.9, "p90")):
    v = pct(all_peaks, p)
    ax.axvline(v, color=INK2, linewidth=1, linestyle=(0, (3, 3)), zorder=2)
    ax.text(v + 3000, max(bottom) * 0.98, f"{lab} {v // 1000}k", color=INK2,
            fontsize=9, va="top")

ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x / 1000:.0f}k"))
ax.set_xticks(range(0, edges[-1] + 1, 50_000))
ax.set_xlim(0, edges[-1])
ax.set_xlabel("Peak context of the session (tokens, the last turn's prompt + output)")
ax.set_ylabel("Sessions per 20k-token bin")
ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color(MUTED)
ax.tick_params(length=0)
fig.suptitle("How large slice sessions get — KubeCoder, Ansible, PilotApp, 2026-08-27 → 2026-10-26",
             x=0.06, ha="left", fontsize=13, fontweight="bold", color=INK)
ax.set_title(f"{len(rows):,} headless loop sessions (writers, reviewers, consults, test, doc, "
             "wrap-up) in 126 slices; sub-agents and orchestrators not counted",
             loc="left", fontsize=9.5, color=INK2)
ax.legend(frameon=False, loc="upper right", bbox_to_anchor=(1.0, 0.86), labelcolor=INK)

# table view
lines = [f"{'':10}{'n':>6}{'p50':>7}{'p90':>7}{'max':>7}"]
for name, _ in PROJECTS + [("All", None)]:
    xs = [r["peak"] for r in rows if name == "All" or r["project"] == name]
    lines.append(f"{name:10}{len(xs):>6}{pct(xs, .5) // 1000:>6}k{pct(xs, .9) // 1000:>6}k"
                 f"{max(xs) // 1000:>6}k")
ax.text(1.0, 0.58, "\n".join(lines), transform=ax.transAxes, ha="right", va="top",
        family="DejaVu Sans Mono", fontsize=8.5, color=INK2)

fig.tight_layout(rect=(0.02, 0, 1, 0.97))
fig.savefig("session-sizes.png", facecolor=SURFACE)
