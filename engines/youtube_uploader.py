"""Upload a finished cartoon to the owner's YouTube channel (YouTube Data API v3).

One-time setup by the channel owner: a free Google Cloud project with the YouTube Data API
enabled and an OAuth client of type "Desktop app"; its JSON file is picked in the Publish page.
Sign-in happens in the browser; the refresh token is saved in ``tokens/youtube.json`` next to
the user settings (never inside a project or video folder). Uploads are private by default.
Quota: an upload costs 1,600 of the default 10,000 daily units (about 6 uploads per day).
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from utils.config import PROJECT_ROOT
from utils.logger import get_logger

log = get_logger("youtube")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_DIR = PROJECT_ROOT / "tokens"
TOKEN_FILE = TOKEN_DIR / "youtube.json"
CLIENT_FILE = TOKEN_DIR / "youtube_client_secret.json"
CATEGORY_FILM_ANIMATION = "1"
CATEGORY_EDUCATION = "27"


class YouTubeError(RuntimeError):
    pass


@dataclass
class VideoMeta:
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    privacy: str = "private"  # private | unlisted | public
    made_for_kids: bool = True
    synthetic: bool = True  # "altered or synthetic content" disclosure (AI voices / generated video)
    category: str = CATEGORY_FILM_ANIMATION
    language: str = "ur"

    def problems(self) -> list[str]:
        out = []
        if not self.title.strip():
            out.append("The title is empty.")
        if len(self.title) > 100:
            out.append(f"The title is {len(self.title)} characters; YouTube allows 100.")
        if "<" in self.title + self.description or ">" in self.title + self.description:
            out.append("YouTube does not allow < or > in the title or description.")
        if len(self.description.encode("utf-8")) > 5000:
            out.append("The description is longer than YouTube's 5000 bytes.")
        if len(",".join(self.tags)) > 500:
            out.append("The tags are longer than YouTube's 500 characters in total.")
        if self.privacy not in ("private", "unlisted", "public"):
            out.append("Unknown privacy setting.")
        return out

    def body(self) -> dict:
        return {"snippet": {"title": self.title.strip(), "description": self.description.strip(),
                            "tags": [t.strip() for t in self.tags if t.strip()], "categoryId": self.category,
                            "defaultLanguage": self.language, "defaultAudioLanguage": self.language},
                "status": {"privacyStatus": self.privacy, "selfDeclaredMadeForKids": self.made_for_kids,
                           "containsSyntheticMedia": self.synthetic, "embeddable": True}}


def libraries_available() -> bool:
    from importlib.util import find_spec  # no import: the Google libraries take seconds to load

    return find_spec("google_auth_oauthlib") is not None and find_spec("googleapiclient") is not None


def has_client() -> bool:
    return CLIENT_FILE.exists()


def is_signed_in() -> bool:
    return TOKEN_FILE.exists()


def set_client_file(path: Path) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "installed" not in data:
        raise YouTubeError("This is not a 'Desktop app' OAuth client file. In Google Cloud create an OAuth client "
                           "of type 'Desktop app' and download its JSON.")
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, CLIENT_FILE)


def sign_out() -> None:
    TOKEN_FILE.unlink(missing_ok=True)


def credentials(interactive: bool = True):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:  # revoked or expired refresh token: sign in again
            log.warning("YouTube token refresh failed: %s", exc)
            creds = None
    if not creds or not creds.valid:
        if not interactive:
            raise YouTubeError("Not signed in to YouTube.")
        if not CLIENT_FILE.exists():
            raise YouTubeError("Choose your Google OAuth client file first (see the setup guide).")
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True, prompt="consent",
                                      success_message="Signed in. You can close this tab and return to the studio.")
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def build_service(creds=None):
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=creds or credentials(), cache_discovery=False)


def upload(video: Path, meta: VideoMeta, thumbnail: Path | None = None,
           progress: Callable[[float, str], None] | None = None, service=None) -> dict:
    """Resumable upload; returns {"id", "url", "thumbnail_set", "note"}."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    issues = meta.problems()
    if issues:
        raise YouTubeError(" ".join(issues))
    video = Path(video)
    if not video.exists():
        raise YouTubeError(f"Video not found: {video}")
    yt = service or build_service()
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=meta.body(), media_body=media)
    response = None
    retries = 0
    try:
        while response is None:
            try:
                status, response = request.next_chunk()
                retries = 0
            except HttpError as exc:
                if exc.resp.status in (500, 502, 503, 504) and retries < 5:
                    retries += 1
                    continue
                raise
            if status and progress:
                progress(status.progress() * 0.95, f"Uploading… {status.progress() * 100:.0f}%")
    except HttpError as exc:
        raise YouTubeError(_explain(exc)) from exc
    vid = response["id"]
    result = {"id": vid, "url": f"https://youtu.be/{vid}", "thumbnail_set": False, "note": ""}
    if thumbnail and Path(thumbnail).exists():
        try:
            thumb_media = MediaFileUpload(str(thumbnail), mimetype="image/jpeg")
            yt.thumbnails().set(videoId=vid, media_body=thumb_media).execute()
            result["thumbnail_set"] = True
        except HttpError as exc:  # custom thumbnails need a phone-verified channel
            result["note"] = "Video uploaded, but YouTube did not accept the custom thumbnail: " + _explain(exc)
    if progress:
        progress(1.0, "Uploaded")
    log.info("Uploaded %s as %s (%s)", video.name, vid, meta.privacy)
    return result


def _explain(exc) -> str:
    try:
        reason = json.loads(exc.content.decode())["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, AttributeError):
        reason = ""
    hints = {"quotaExceeded": "Today's YouTube upload limit is used up; try again tomorrow.",
             "uploadLimitExceeded": "This channel reached its upload limit for now.",
             "forbidden": "This Google account cannot upload to this channel.",
             "youtubeSignupRequired": "This Google account has no YouTube channel yet. Create one on youtube.com.",
             "insufficientPermissions": "Sign in again and allow uploading."}
    return hints.get(reason, f"YouTube error {getattr(exc.resp, 'status', '')}: {reason or exc}")
