#!/usr/bin/env python3
"""Offsite VPS backup uploader (2026-11-18, backup plan A post-Contabo-incident).

Streams one staged backup file from stdin into the Google Drive folder
'offsite-vps-backups' using the SAME service account the grocery sheet
backups already use (core.sheets_client._build_credentials), then prunes
old files of the same class so the Drive quota stays bounded.

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

FOLDER_NAME = "offsite-vps-backups"


def _service():
    sys.path.insert(0, "/app/tasks/ai-tools/grocery-price-tracker")
    from core.sheets_client import _build_credentials, _load_env
    from googleapiclient.discovery import build
    _load_env()
    return build("drive", "v3", credentials=_build_credentials(), cache_discovery=False)


def _folder_id(svc):
    q = (
        f"name='{FOLDER_NAME}' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    found = svc.files().list(q=q, fields="files(id,name)", pageSize=5).execute()
    files = found.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}
    return svc.files().create(body=meta, fields="id").execute()["id"]


def _klass(name: str) -> str:
    parts = name.split("-")
    return parts[2] if len(parts) >= 3 else ""


def upload(svc, folder_id, name, keep_days):
    from googleapiclient.http import MediaIoBaseUpload

    media = MediaIoBaseUpload(
        sys.stdin.buffer,
        mimetype="application/gzip",
        resumable=True,
        chunksize=16 * 1024 * 1024,
    )
    meta = {"name": name, "parents": [folder_id]}
    request = svc.files().create(body=meta, media_body=media, fields="id,size")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"progress {int(status.progress() * 100)}%", file=sys.stderr, flush=True)
    print(f"uploaded {name} drive_size={response.get('size')}")
    prune(svc, folder_id, name, keep_days)


def prune(svc, folder_id, just_uploaded, keep_days):
    cutoff = (datetime.date.today() - datetime.timedelta(days=keep_days)).strftime("%Y%m%d")
    want_class = _klass(just_uploaded)
    res = svc.files().list(
        q=f"'{folder_id}' in parents and trashed=false and name contains 'offsite-'",
        fields="files(id,name)",
        pageSize=100,
    ).execute()
    removed = 0
    for f in res.get("files", []):
        stamp = f["name"].split("-")
        if len(stamp) < 3 or f["name"] == just_uploaded:
            continue
        if _klass(f["name"]) == want_class and stamp[1] < cutoff:
            svc.files().delete(fileId=f["id"]).execute()
            removed += 1
    print(f"pruned {removed} old '{want_class}' backups (keep {keep_days}d)")


def download(svc, name):
    res = svc.files().list(
        q=f"name='{name}' and trashed=false", fields="files(id,name)", pageSize=1
    ).execute()
    files = res.get("files", [])
    if not files:
        sys.exit(f"not found in Drive folder: {name}")
    data = svc.files().get_media(fileId=files[0]["id"]).execute()
    sys.stdout.buffer.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True, help="offsite-YYYYMMDD-class-label.tar.gz")
    ap.add_argument("--class", dest="klass", choices=["small", "big"],
                    help="retention class (small=14d, big=3d by convention)")
    ap.add_argument("--keep-days", type=int, default=14)
    ap.add_argument("--download", action="store_true", help="fetch the named file to stdout")
    args = ap.parse_args()

    svc = _service()
    if args.download:
        download(svc, args.name)
        return
    if not args.klass:
        sys.exit("--class is required unless --download")
    upload(svc, _folder_id(svc), args.name, args.keep_days)


if __name__ == "__main__":
    main()
