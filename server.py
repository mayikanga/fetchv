from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

ROOT = Path(__file__).resolve().parent
DOWNLOADS = Path(
    os.environ.get("FETCHV_DOWNLOAD_DIR")
    or ("/tmp/fetchv-downloads" if os.environ.get("RENDER") else ROOT / "downloads")
)
DOWNLOADS.mkdir(exist_ok=True)
YTDLP = shutil.which("yt-dlp")
COOKIE_FILE = os.environ.get("FETCHV_COOKIE_FILE")
COOKIE_B64 = os.environ.get("FETCHV_COOKIES_B64")
TEMP_COOKIE_FILE = Path(tempfile.gettempdir()) / "fetchv-cookies.txt"
DOWNLOAD_TTL_SECONDS = int(os.environ.get("FETCHV_DOWNLOAD_TTL_SECONDS", "1800"))

app = FastAPI()


class MediaRequest(BaseModel):
    url: HttpUrl
    format_id: str | None = None


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    modal_id = parse_qs(parsed.query).get("modal_id", [None])[0]
    if parsed.netloc.endswith("douyin.com") and modal_id and re.fullmatch(r"\d+", modal_id):
        return f"https://www.douyin.com/video/{modal_id}"
    return url


def active_cookie_file() -> str | None:
    """Return the local cookie file without exposing its contents or path to clients."""
    if COOKIE_FILE and Path(COOKIE_FILE).is_file():
        return COOKIE_FILE
    if not COOKIE_B64:
        return None
    try:
        content = base64.b64decode(COOKIE_B64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Cookie secret is invalid") from exc
    TEMP_COOKIE_FILE.write_bytes(content)
    try:
        TEMP_COOKIE_FILE.chmod(0o600)
    except OSError:
        pass
    return str(TEMP_COOKIE_FILE)


def clean_old_downloads() -> None:
    cutoff = time.time() - DOWNLOAD_TTL_SECONDS
    for item in DOWNLOADS.iterdir():
        try:
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink()
        except OSError:
            continue


def ytdlp_command(url: str) -> list[str]:
    if not YTDLP:
        raise HTTPException(status_code=500, detail="未找到 yt-dlp")
    command = [YTDLP, "--no-playlist"]
    cookie_file = active_cookie_file()
    if cookie_file:
        command.extend(["--cookies", cookie_file])
    command.append(canonical_url(url))
    return command


@app.post("/api/parse")
def parse(payload: MediaRequest):
    clean_old_downloads()
    command = ytdlp_command(str(payload.url))
    command[1:1] = ["--dump-single-json", "--skip-download"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    if result.returncode:
        raise HTTPException(status_code=422, detail=(result.stderr.strip() or result.stdout.strip() or "解析失败")[-800:])
    info = json.loads(result.stdout)
    formats = []
    for item in info.get("formats", []):
        if item.get("vcodec") == "none":
            continue
        note = item.get("format_note") or ""
        if "watermark" in note.lower():
            continue
        formats.append({
            "id": item.get("format_id"),
            "height": item.get("height") or 0,
            "width": item.get("width") or 0,
            "ext": item.get("ext") or "mp4",
            "filesize": item.get("filesize") or item.get("filesize_approx") or 0,
            "watermarked": False,
            "direct": "direct" in note.lower(),
            "bitrate": item.get("tbr") or 0,
        })
    formats.sort(key=lambda item: (item["watermarked"], -item["height"], -item["direct"], -item["filesize"], -item["bitrate"]))
    unique = []
    seen = set()
    for item in formats:
        key = (item["height"], item["ext"], item["watermarked"])
        if key in seen:
            continue
        seen.add(key)
        item["quality"] = f'{item["height"]}p' if item["height"] else "原始质量"
        unique.append(item)
    return {
        "title": info.get("title") or "未命名内容",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("creator") or "",
        "formats": unique[:6],
    }


@app.post("/api/download")
def download(payload: MediaRequest):
    clean_old_downloads()
    job_id = uuid.uuid4().hex
    template = str(DOWNLOADS / f"{job_id}.%(ext)s")
    command = ytdlp_command(str(payload.url))
    command[1:1] = ["-f", payload.format_id or "bv*+ba/b", "--merge-output-format", "mp4", "-o", template]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    if result.returncode:
        raise HTTPException(status_code=422, detail=(result.stderr.strip() or result.stdout.strip() or "下载失败")[-800:])
    files = sorted(DOWNLOADS.glob(f"{job_id}.*"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise HTTPException(status_code=500, detail="下载完成但未找到文件")
    return {"url": f"/api/file/{files[0].name}"}


@app.get("/api/file/{filename}")
def file(filename: str):
    path = DOWNLOADS / Path(filename).name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=path.name)


@app.get("/")
def home():
    return FileResponse(ROOT / "FetchV.html")


app.mount("/", StaticFiles(directory=ROOT, html=True), name="site")
