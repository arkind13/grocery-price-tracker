"""Test harness: run a grocery_price_cli command, log receipt, save full output.

Usage:
  python harness.py run <test-id> <label> [-- args...]
  python harness.py batch <batch-file>   # JSON list of {id,label,args,timeout}
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\User.DESKTOP-R2G441H\Documents\AI related")
PY = ROOT / "anaconda3" / "python.exe" if False else Path(r"C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe")
CLI = ROOT / "grocery_price_cli.py"
LOGDIR = Path(__file__).parent
OUTDIR = LOGDIR / "outputs"
OUTDIR.mkdir(exist_ok=True)
CSV = LOGDIR / "commands_log.csv"


def run_one(tid: str, label: str, args: list, timeout: int = 300) -> dict:
    t0 = time.time()
    cmd = [str(PY), str(CLI)] + args
    env = {"PYTHONIOENCODING": "utf-8", "PATH": ""}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=str(ROOT))
        rc, out, err = p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        rc, out, err = -99, "", f"TIMEOUT after {timeout}s"
    secs = round(time.time() - t0, 1)
    fname = f"{tid}_{label.replace(' ', '_').replace('/', '_')[:60]}.txt"
    for ch in '<>:"|?*':
        fname = fname.replace(ch, "_")
    (OUTDIR / fname).write_text(
        f"$ {' '.join(args)}\n--- rc={rc} secs={secs} ---\n{out}\n[stderr]\n{err}",
        encoding="utf-8")
    row = {"id": tid, "ts": datetime.now().strftime("%H:%M:%S"), "label": label,
           "cmd": " ".join(args), "rc": rc, "secs": secs, "out": fname,
           "headline": (out.strip().splitlines() or [""])[0][:160]}
    with CSV.open("a", encoding="utf-8") as f:
        if f.tell() == 0:
            f.write("id,ts,label,cmd,rc,secs,output_file,headline\n")
        f.write(",".join([row["id"], row["ts"], f'"{label}"',
                          '"' + row["cmd"].replace('"', "'") + '"',
                          str(rc), str(secs), fname,
                          '"' + row["headline"].replace('"', "'") + '"']) + "\n")
    print(f"[{tid}] rc={rc} {secs}s | {label} | {row['headline'][:110]}")
    return row


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "run":
        rest = sys.argv[2:]
        if "--" in rest:
            i = rest.index("--")
            run_one(rest[0], rest[1], rest[i + 1:])
        else:
            print("need: run <id> <label> -- <args>")
    elif mode == "batch":
        for job in json.loads((LOGDIR / sys.argv[2]).read_text(encoding="utf-8")):
            run_one(job["id"], job["label"], job["args"], job.get("timeout", 300))
