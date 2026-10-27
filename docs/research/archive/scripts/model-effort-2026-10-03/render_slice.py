#!/usr/bin/env python3
"""Render every run-phase transcript (code-writer / code-reviewer, all rounds) of a slice to
rendered/<slice>/P<ph>_<role>_r<n>.txt, plus the review files and the plan's done-records."""
import json, os, sys, subprocess, glob, re, shutil
slice_dir = sys.argv[1].rstrip('/'); label = sys.argv[2]
out = f'/work/scratch/model-read/rendered/{label}'; os.makedirs(out, exist_ok=True)
s = json.load(open(os.path.join(slice_dir, 'state.json')))
rows = [r for r in s['history'] if r.get('role') in ('code-writer', 'code-reviewer')]
total = 0
for r in rows:
    role = 'writer' if r['role'] == 'code-writer' else 'reviewer'
    name = f"P{r['phase']}_{role}_r{r.get('round', 1)}.txt"
    t = r.get('transcript')
    if not t or not os.path.exists(t):
        continue
    txt = subprocess.run(['python3', '/work/scratch/model-read/render.py', t, '--max-result', '350', '--max-text', '2500'], capture_output=True, text=True).stdout
    hdr = f"# {name} — outcome: {r.get('outcome')} — duration {r.get('duration_s')} s\n# summary: {r.get('summary')}\n\n"
    open(os.path.join(out, name), 'w').write(hdr + txt); total += len(txt)
# review files + results
for f in glob.glob(os.path.join(slice_dir, 'phases', 'P*', 'code_review_r*.md')):
    ph = f.split('/')[-2]; shutil.copy(f, os.path.join(out, f"{ph}_{os.path.basename(f)}"))
for f in glob.glob(os.path.join(slice_dir, 'phases', 'P*', 'executor_result_r*.json')):
    ph = f.split('/')[-2]; shutil.copy(f, os.path.join(out, f"{ph}_{os.path.basename(f)}"))
shutil.copy(os.path.join(slice_dir, 'plan.md'), os.path.join(out, 'plan.md'))
if os.path.exists(os.path.join(slice_dir, 'log.txt')):
    shutil.copy(os.path.join(slice_dir, 'log.txt'), os.path.join(out, 'log.txt'))
print(label, len(rows), 'transcripts,', total // 1000, 'KB rendered')
