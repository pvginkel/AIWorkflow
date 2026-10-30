"""Hand classification of the operator's in-run turns (primary class) and per-run message facts."""
import json, statistics
from datetime import datetime
runs = json.load(open("runs.json"))
# run -> list of primary classes of in-run operator turns, in order
C = {
 2:["reroute","other","answer","agree-all"], 3:["answer","answer","agree-all"], 5:["answer","agree-all"],
 6:["agree-all"], 7:["answer","answer","agree-all"], 8:["answer"], 9:["answer","agree-all"], 10:["other"],
 11:["agree-all"], 12:["agree-all"], 13:["answer","question-back","answer"], 14:["answer"],
 15:["agree-with-exceptions"], 16:["question-back","reroute"], 17:["answer"], 19:["agree-all"], 20:["answer"],
 21:["answer"], 22:["question-back","agree-all"], 23:["answer","answer","question-back","answer"], 24:["answer"],
 25:["agree-all"], 26:["agree-all"], 27:["other","agree-all"], 28:["answer"], 29:["agree-all"],
 30:["answer","agree-all"], 31:["agree-all"], 32:["answer"], 33:["answer"], 34:["agree-all"],
 35:["answer","question-back","agree-all"], 36:["reroute"], 37:["agree-all"], 38:["answer"],
 39:["alternative-scheme","other"], 40:["question-back","other","other"], 41:["agree-all"], 42:["answer"], 43:["agree-all"],
}
# per run: words, items, slices, questions (hand-checked)
M = {2:(778,14,3,5),3:(687,8,3,6),5:(502,21,2,3),6:(389,8,1,3),7:(903,23,6,6),8:(294,1,1,2),9:(489,1,1,5),
 10:(406,2,1,3),11:(775,2,1,2),12:(329,1,1,1),13:(913,19,6,5),14:(330,1,1,2),15:(632,14,2,5),16:(267,1,1,1),
 17:(373,4,4,1),19:(241,1,1,0),20:(267,1,1,2),21:(592,12,1,4),22:(286,2,1,1),23:(1242,32,3,10),24:(429,6,1,3),
 25:(193,2,2,0),26:(389,2,1,3),27:(666,8,1,5),28:(344,10,1,2),29:(273,1,1,1),30:(341,2,2,1),31:(505,3,1,4),
 32:(373,3,1,2),33:(805,10,9,5),34:(482,2,1,4),35:(395,1,1,5),36:(512,8,2,5),37:(129,1,1,0),38:(602,5,1,5),
 39:(359,6,2,2),40:(214,1,1,1),41:(267,4,1,0),42:(1232,23,9,4),43:(302,3,1,2)}
from collections import Counter
allc = [c for v in C.values() for c in v]
cnt = Counter(allc); N = len(allc)
print("turns", N, "runs", len(C))
for k, v in cnt.most_common(): print(f"  {k:22} {v:3} {100*v/N:4.0f}%")
w = [m[0] for m in M.values()]; it = [m[1] for m in M.values()]; sl = [m[2] for m in M.values()]; q = [m[3] for m in M.values()]
print("words median", statistics.median(w), "max", max(w), "min", min(w), "total", sum(w))
print("items median", statistics.median(it), "total", sum(it), "1-item runs", sum(1 for x in it if x == 1), "<=3", sum(1 for x in it if x <= 3))
print("slices median", statistics.median(sl), "total", sum(sl), "1-slice runs", sum(1 for x in sl if x == 1))
print("questions median", statistics.median(q), "total", sum(q), "zero-Q runs", sum(1 for x in q if x == 0))
# latency message -> first operator turn (hand: run 15 uses the 17:35 answer)
f = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
lat = {}
import re
for n, r in enumerate(runs, 1):
    if n not in M: continue
    evs = r["events"]
    fi = next(i for i, e in enumerate(evs) if e["k"] == "op" and not e["text"].startswith(("/compact", "This session is being")))
    msg = [e for e in evs[:fi] if e["k"] == "asst" and len(e["text"].split()) >= 100][-1]
    if n == 23: msg = [e for e in evs[:fi] if e["k"] == "asst" and len(e["text"].split()) >= 1000][0]
    lat[n] = (f(evs[fi]["ts"]) - f(msg["ts"])).total_seconds() / 60
    if abs(len(msg["text"].split()) - M[n][0]) > 5: print("WARN msg mismatch", n, len(msg["text"].split()), M[n][0])
L = sorted(lat.values())
print("latency min median max", round(L[0], 1), round(statistics.median(L), 1), round(L[-1], 1), "n", len(L))
print("<=5min", sum(1 for x in L if x <= 5), "<=10", sum(1 for x in L if x <= 10), ">30", sum(1 for x in L if x > 30))
print({n: round(v, 1) for n, v in lat.items()})
# words per minute for quick answers
fast = [(n, M[n][0], round(lat[n], 1), round(M[n][0] / max(lat[n], 0.01))) for n in M if M[n][0] / max(lat[n], .01) > 250]
print("faster than 250 wpm:", fast)
json.dump({"classes": C, "message": M, "latency_min": lat}, open("classification.json", "w"), indent=1)
