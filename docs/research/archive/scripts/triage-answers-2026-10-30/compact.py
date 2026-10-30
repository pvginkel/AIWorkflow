import json, sys
runs = json.load(open("runs.json"))
which = sys.argv[1]  # 'skill' or 'cmd'
nums = set(int(x) for x in sys.argv[2].split(",")) if len(sys.argv) > 2 else None
for n, r in enumerate(runs, 1):
    if r["via"] != which or (nums and n not in nums):
        continue
    print(f"\n######## run {n} {r['folder']} {r['start'][:16]} ver={r['ver']} end={r['ender'][:40]}")
    print("ARGS:", r["args"][:500].replace("\n", " "))
    seen_op = False
    for e in r["events"]:
        k = e["k"]
        if k == "op":
            seen_op = True
            print(f"\n>>> OP {e['ts'][:19]}\n{e['text']}\n<<<")
        elif k == "asst":
            w = len(e["text"].split())
            if w >= 120:
                print(f"\n--- A {e['ts'][:19]} ({w} w)\n{e['text']}")
            else:
                print(f"--- a {e['ts'][:19]} ({w} w) {e['text'][:200]!r}")
        elif k == "tool" and e["name"] == "Bash" and "commit" in e.get("cmd", "") and "git" in e.get("cmd", ""):
            print(f"[COMMIT {e['ts'][:19]}]")
        elif k == "tool" and e["name"] == "AskUserQuestion":
            print(f"[ASK {e['ts'][:19]}] {json.dumps(e['input'])[:600]}")
        elif k == "interrupt":
            print(f"[INTERRUPT {e['ts'][:19]}]")
