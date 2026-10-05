#!/usr/bin/env python3
"""Hash every frame of all 14 TerraScope collections.

Writes per-collection manifests {filename, drive_id, sha256, size} plus one
SHA-256 root per collection: sha256 over the LF-terminated lines
'<filename> <sha256> <size>' in manifest order. ROOTS.txt carries one line
per collection and a GLOBAL line = sha256 over the 14 root hashes (one per
line '<key> <count> <root>', section order, LF-terminated).

Inventory gate: frame counts must match the aggregated 14-section inventory
(593 frames total) or the job fails before hashing.

Downloads use the Drive download endpoint (proven byte-identical for the
Ancient Datagram AVI). v2 hardening after run 1 was killed by the 90-minute
job timeout mid-hash under Drive throttling:
  - resume: a frame fetched by an earlier run is reused only when its
    <file>.size sidecar records the SAME drive id and the on-disk size
    matches; sidecars are written only after a fully validated download, so
    a killed run can never poison a resume.
  - per-attempt network timeout 60s (was 300s - one hung connection could
    stall a section for half an hour).
  - explicit HTTP status check + Content-Length validation, so truncated
    downloads can no longer hash silently.
  - one serial second-chance pass over failed frames before a section is
    declared INCOMPLETE.
  - per-section status and failure reasons print the moment they happen.
Any frame still failing after retries fails the job:
no silent skips, no partial ROOTS.txt.
"""

import hashlib
import json
import os
import random
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DL = "https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
WORKERS = 4
TRIES = 6
NET_TIMEOUT = 60
EXPECTED = {
    "c1": 12, "c2": 12, "t121": 36, "t122": 47, "t135": 51,
    "t202": 32, "t264": 45, "t26o": 130, "t274": 32, "t27o": 30,
    "si113": 61, "si184": 60, "si71": 6, "si9o": 39,
}


def digest_file(path):
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def fetch(fid, out_path):
    """Return (sha256, size); reuse a validated resume copy when present."""
    sidecar = out_path + ".size"
    if os.path.exists(out_path) and os.path.exists(sidecar):
        try:
            with open(sidecar, encoding="utf-8") as fh:
                parts = fh.read().split()
            if (parts and parts[0] == fid and int(parts[1]) > 0
                    and int(parts[1]) == os.path.getsize(out_path)):
                return digest_file(out_path)
        except (OSError, ValueError, IndexError):
            pass
        for stale in (out_path, sidecar):
            if os.path.exists(stale):
                os.remove(stale)

    url = DL.format(id=fid)
    part = out_path + ".part"
    last = ""
    for attempt in range(1, TRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as res:
                code = getattr(res, "status", 200)
                ctype = res.headers.get("Content-Type", "")
                clen = res.headers.get("Content-Length")
                if code != 200:
                    last = "http %d" % code
                elif "text/html" in ctype:
                    last = "html interstitial"
                else:
                    h = hashlib.sha256()
                    n = 0
                    with open(part, "wb") as fh:
                        while True:
                            chunk = res.read(1 << 20)
                            if not chunk:
                                break
                            h.update(chunk)
                            fh.write(chunk)
                            n += len(chunk)
                    with open(part, "rb") as fh:
                        magic = fh.read(3)
                    bad = None
                    if n == 0:
                        bad = "empty body"
                    elif clen is not None and n != int(clen):
                        bad = "truncated %d of %s bytes" % (n, clen)
                    elif magic != b"\xff\xd8\xff" and magic != b"\x89PNG":
                        bad = "neither jpeg nor png (magic %r)" % magic
                    if bad is None:
                        os.replace(part, out_path)
                        with open(sidecar, "w", encoding="utf-8") as fh:
                            fh.write("%s %d\n" % (fid, n))
                        time.sleep(random.uniform(0.05, 0.45))
                        return h.hexdigest(), n
                    last = bad
        except Exception as exc:
            last = str(exc) or exc.__class__.__name__
        if os.path.exists(part):
            os.remove(part)
        time.sleep(min(60, 5 * attempt))
    raise RuntimeError("%s: %s" % (fid, last))


def main():
    if len(sys.argv) != 3:
        print("usage: manifest_collections.py <ids.json> <out_dir>")
        sys.exit(2)
    ids_path, out_dir = sys.argv[1], sys.argv[2]
    with open(ids_path, encoding="utf-8") as fh:
        data = json.load(fh)
    sections = data["sections"]
    if len(sections) != 14:
        print("expected 14 sections, got %d" % len(sections))
        sys.exit(1)
    total_expected = 0
    for sec in sections:
        want = EXPECTED.get(sec["key"])
        got = len(sec["frames"])
        total_expected += want or 0
        if want is None:
            print("unknown section key: %s" % sec["key"])
            sys.exit(1)
        if got != want:
            print("INVENTORY MISMATCH %s: page has %d frames, aggregated inventory %d"
                  % (sec["key"], got, want))
            sys.exit(1)
    print("inventory gate passed: 14 sections, %d frames" % total_expected, flush=True)
    os.makedirs(out_dir, exist_ok=True)
    tmpdir = os.path.join("/tmp", "tqframes")
    os.makedirs(tmpdir, exist_ok=True)

    roots = []
    failures = []

    for sec in sections:
        frames = sec["frames"]
        results = [None] * len(frames)

        def work(i):
            f = frames[i]
            path = os.path.join(tmpdir, "%s__%s" % (sec["key"], f["filename"]))
            try:
                digest, size = fetch(f["drive_id"], path)
                return i, f["filename"], f["drive_id"], digest, size
            finally:
                if os.path.exists(path + ".part"):
                    os.remove(path + ".part")

        def run_pass(pending, workers):
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(work, i) for i in pending]
                for fut in as_completed(futs):
                    try:
                        i, name, fid, digest, size = fut.result()
                        results[i] = {"filename": name, "drive_id": fid,
                                      "sha256": digest, "size": size}
                    except Exception as exc:
                        failures.append(str(exc))

        run_pass(list(range(len(frames))), WORKERS)
        if any(r is None for r in results):
            pending = [i for i, r in enumerate(results) if r is None]
            print("%s: %d frame(s) failed the parallel pass - one serial retry"
                  % (sec["key"], len(pending)), flush=True)
            run_pass(pending, 1)

        if any(r is None for r in results):
            got = sum(1 for r in results if r)
            print("%s: INCOMPLETE (%d/%d) - no root written"
                  % (sec["key"], got, len(results)), flush=True)
            seen = set()
            for f in failures:
                if f not in seen:
                    seen.add(f)
                    print("  - " + f, flush=True)
                if len(seen) >= 8:
                    break
            continue
        canonical = "".join(
            "%s %s %d\n" % (r["filename"], r["sha256"], r["size"])
            for r in results)
        root = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        manifest = {
            "section": sec["key"],
            "label": sec.get("label", ""),
            "count": len(results),
            "root": root,
            "root_definition": "sha256 over one line per frame: <filename> space <sha256> space <size>, LF-terminated, manifest order",
            "frames": results,
        }
        out_path = os.path.join(out_dir, sec["key"] + ".json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=1)
            fh.write("\n")
        roots.append((sec["key"], sec.get("label", ""), len(results), root))
        print("%s: %d frames root %s" % (sec["key"], len(results), root), flush=True)

    if failures or len(roots) != 14:
        if failures:
            print("FAILURES (%d):" % len(failures))
            for f in sorted(set(failures)):
                print("  - " + f)
        print("ATTENTION INCOMPLETE: roots written %d/14 - ROOTS.txt NOT written, job fails"
              % len(roots))
        sys.exit(1)
    lines = ["%-6s %4d %s  %s" % (k, c, r, l) for k, l, c, r in roots]
    glob = hashlib.sha256(
        ("\n".join("%s %d %s" % (k, c, r) for k, l, c, r in roots) + "\n").encode("utf-8")
    ).hexdigest()
    with open(os.path.join(out_dir, "ROOTS.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
        fh.write("GLOBAL  sha256 over the 14 lines '<key> <count> <root>' above, section order = %s\n" % glob)
    print("ALL GREEN: 14 sections, %d frames, GLOBAL %s" % (sum(c for k, l, c, r in roots), glob), flush=True)


if __name__ == "__main__":
    main()
