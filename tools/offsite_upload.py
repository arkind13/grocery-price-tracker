#!/usr/bin/env python3
"""Offsite VPS backup uploader (2026-11-18, backup plan A post-Contabo-incident).

Streams one staged backup file from stdin into the Google Drive folder
'offsite-vps-backups' using the SAME service account the grocery sheet
backups already use (core.sheets_client._build_credentials), then prunes
old files of the same class so the Drive quota stays bounded.

Uses ONLY libs already inside the openclaw container (google-auth for the
token + requests for plain HTTPS — no googleapiclient dependency; first
live run 2026-11-18 proved the container has no googleapiclient).

File naming contract (the host-side offsite_backup.sh relies on it):
    offsite-YYYYMMDD-<class>-<label>.tar.gz   class in {small, big}

Usage (host side, driven by /home/ubuntu/scripts/offsite_backup.sh):
    docker exec -i openclaw-core python3 \\
        /app/tasks/ai-tools/grocery-price-tracker/tools/offsite_upload.py \\
        --name offsite-20261118-small-pg.sql.gz --class small --keep-days 14 < file

Restore path (downloads straight to stdout):
    ... offsite_upload.py --name offsite-20261118-small-pg.sql.gz --download > file
"""
import argparse
import datetime
import sys
from urllib.parse import quote

FOLDER_NAME = "offsite-vps-backups"
CHUNK = 16 * 1024 * 1024
API = "https://www.googleapis.com/drive/v3"


def _token():
    sys.path.insert(0, "/app/tasks/ai-tools/grocery-price-tracker")
    from core.sheets_client import _build_credentials, _load_env
    _load_env()
    creds = _build_credentials()
    import requests
    from google.auth.transport.requests import Request
    creds.refresh(Request())
    return creds.token


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def _folder_id(token):
    import requests
    q = quote(
        f"name='{FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' "
        "and trashed=false"
    )
    r = requests.get(
        f"{API}/files?q={q}&fields=files(id,name)&pageSize=5",
        headers=_hdr(token),
        timeout=120,
    )
    r.raise_for_status()
    files = r.json().get("files", [])
    if files:
        return files[0]["id"]
    r = requests.post(
        f"{API}/files",
        headers={**_hdr(token), "Content-Type": "application/json"},
        json={"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"},
        params={"fields": "id"},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["id"]


def _klass(name: str) -> str:
    parts = name.split("-")
    return parts[2] if len(parts) >= 3 else ""


def upload(token, folder_id, name, keep_days):
    import requests

    r = requests.post(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,size",
        headers={**_hdr(token), "Content-Type": "application/json; charset=UTF-8"},
        json={"name": name, "parents": [folder_id]},
        timeout=120,
    )
    r.raise_for_status()
    loc = r.headers["Location"]

    pos = 0
    buf = sys.stdin.buffer.read(CHUNK)
    while buf:
        nxt = sys.stdin.buffer.read(CHUNK)
        if nxt:
            rng = f"bytes {pos}-{pos + len(buf) - 1}/*"
        else:
            rng = f"bytes {pos}-{pos + len(buf) - 1}/{pos + len(buf)}"
        r = requests.put(loc, data=buf, headers={"Content-Range": rng}, timeout=1800)
        if r.status_code not in (200, 201, 308):
            sys.exit(f"upload chunk failed at {pos}: {r.status_code} {r.text[:300]}")
        if r.status_code in (200, 201):
            size = r.json().get("size", "?")
            print(f"uploaded {name} drive_size={size}")
        pos += len(buf)
        buf = nxt
    prune(token, folder_id, name, keep_days)


def prune(token, folder_id, just_uploaded, keep_days):
    import requests

    cutoff = (datetime.date.today() - datetime.timedelta(days=keep_days)).strftime("%Y%m%d")
    want_class = _klass(just_uploaded)
    q = quote(f"'{folder_id}' in parents and trashed=false and name contains 'offsite-'")
    r = requests.get(
        f"{API}/files?q={q}&fields=files(id,name)&pageSize=100",
        headers=_hdr(token),
        timeout=120,
    )
    r.raise_for_status()
    removed = 0
    for f in r.json().get("files", []):
        parts = f["name"].split("-")
        if len(parts) < 3 or f["name"] == just_uploaded:
            continue
        if _klass(f["name"]) == want_class and parts[1] < cutoff:
            d = requests.delete(
                f"{API}/files/{f['id']}", headers=_hdr(token), timeout=120
            )
            if d.status_code in (204, 200):
                removed += 1
    print(f"pruned {removed} old '{want_class}' backups (keep {keep_days}d)")


def download(token, name):
    import requests

    q = quote(f"name='{name}' and trashed=false")
    r = requests.get(
        f"{API}/files?q={q}&fields=files(id,name)&pageSize=1",
        headers=_hdr(token),
        timeout=120,
    )
    r.raise_for_status()
    files = r.json().get("files", [])
    if not files:
        sys.exit(f"not found in Drive folder: {name}")
    fid = files[0]["id"]
    with requests.get(
        f"{API}/files/{fid}", headers=_hdr(token), params={"alt": "media"},
        stream=True, timeout=1800,
    ) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_content(CHUNK):
            sys.stdout.buffer.write(chunk)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True, help="offsite-YYYYMMDD-class-label.tar.gz")
    ap.add_argument("--class", dest="klass", choices=["small", "big"],
                    help="retention class (small=14d, big=3d by convention)")
    ap.add_argument("--keep-days", type=int, default=14)
    ap.add_argument("--download", action="store_true", help="fetch the named file to stdout")
    args = ap.parse_args()

    token = _token()
    if args.download:
        download(token, args.name)
        return
    if not args.klass:
        sys.exit("--class is required unless --download")
    upload(token, _folder_id(token), args.name, args.keep_days)


if __name__ == "__main__":
    main()
