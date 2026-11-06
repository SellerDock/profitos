import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import settings

router = APIRouter(prefix="/app", tags=["app-download"])


def _dist_dir() -> Path:
    return Path(settings.APK_DIST_DIR)


def _read_manifest() -> dict:
    manifest_path = _dist_dir() / "manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(404, {"published": False})
    return json.loads(manifest_path.read_text())


@router.get("/manifest")
def get_manifest():
    return _read_manifest()


@router.api_route("/download", methods=["GET", "HEAD"])
def download_apk():
    manifest = _read_manifest()
    filename = manifest.get("filename")
    if not filename or "/" in filename or "\\" in filename:
        raise HTTPException(404, {"published": False})

    apk_path = _dist_dir() / filename
    if not apk_path.is_file():
        raise HTTPException(404, {"published": False})

    return FileResponse(
        path=apk_path,
        media_type="application/vnd.android.package-archive",
        filename=filename,
    )
