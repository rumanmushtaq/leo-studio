"""Minimal client for a ComfyUI server (local or on another PC on the network).

Uses only the standard library. API used (ComfyUI's built-in HTTP API):
  GET  /system_stats             - reachability, GPU name / VRAM
  GET  /object_info              - which node types are installed
  POST /upload/image             - upload an input file (images, videos and audio all go here)
  POST /prompt                   - queue a workflow (API format) -> prompt_id
  GET  /history/<prompt_id>      - outputs once finished
  GET  /view?filename=&subfolder=&type= - download an output file
  POST /interrupt                - stop the running job (cancel)
"""
from __future__ import annotations

import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Callable

from utils.logger import get_logger

log = get_logger("comfy")


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        if not self.base.startswith(("http://", "https://")):
            self.base = "http://" + self.base
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex
        self._object_info: dict | None = None

    # ------------------------------------------------------------------ http
    def _request(self, method: str, path: str, data: bytes | None = None, headers: dict | None = None,
                 timeout: float | None = None) -> bytes:
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:800]
            raise ComfyError(f"ComfyUI {method} {path} failed: HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ComfyError(f"Cannot reach ComfyUI at {self.base} ({exc}). Is the server running and "
                             f"started with --listen when used from another PC?") from exc

    def _json(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        raw = self._request(method, path, data, {"Content-Type": "application/json"} if data else None)
        return json.loads(raw.decode("utf-8")) if raw else {}

    # ------------------------------------------------------------------- api
    def system_stats(self) -> dict:
        return self._json("GET", "/system_stats")

    def describe(self) -> str:
        """One-line summary for the GUI 'Test connection' button."""
        st = self.system_stats()
        devs = st.get("devices", [])
        if devs:
            d = devs[0]
            vram = d.get("vram_total", 0) / 1e9
            return f"Connected: {d.get('name', 'GPU')} ({vram:.0f} GB VRAM), ComfyUI {st.get('system', {}).get('comfyui_version', '')}".strip()
        return "Connected (no GPU reported)"

    def object_info(self) -> dict:
        if self._object_info is None:
            self._object_info = self._json("GET", "/object_info")
        return self._object_info

    def missing_nodes(self, workflow: dict) -> list[str]:
        """Node types used by a workflow that this server does not have installed."""
        installed = self.object_info()
        return sorted({n["class_type"] for n in workflow.values() if n.get("class_type") not in installed})

    def upload(self, path: Path, overwrite: bool = True) -> str:
        """Upload a file into ComfyUI's input folder; returns the name to reference in workflows."""
        path = Path(path)
        boundary = uuid.uuid4().hex
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = b"".join([
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n".encode(), path.read_bytes(), b"\r\n",
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\n"
            f"{'true' if overwrite else 'false'}\r\n--{boundary}--\r\n".encode(),
        ])
        raw = self._request("POST", "/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"},
                            timeout=300)
        res = json.loads(raw.decode("utf-8"))
        name = res.get("name", path.name)
        return f"{res['subfolder']}/{name}" if res.get("subfolder") else name

    def queue(self, workflow: dict) -> str:
        missing = self.missing_nodes(workflow)
        if missing:
            raise ComfyError("ComfyUI server is missing node types: " + ", ".join(missing) +
                             ". Install the custom nodes listed in assets/comfy_workflows/README.md.")
        res = self._json("POST", "/prompt", {"prompt": workflow, "client_id": self.client_id})
        if res.get("node_errors"):
            raise ComfyError(f"Workflow rejected: {json.dumps(res['node_errors'])[:600]}")
        return res["prompt_id"]

    def wait(self, prompt_id: str, timeout: float = 3600, poll: float = 2.0,
             cancel_check: Callable[[], bool] | None = None) -> dict:
        """Block until the job finishes; returns its 'outputs' dict."""
        t0 = time.monotonic()
        while True:
            if cancel_check and cancel_check():
                self.interrupt()
                raise ComfyError("cancelled")
            hist = self._json("GET", f"/history/{prompt_id}")
            entry = hist.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    msgs = [m for m in status.get("messages", []) if m and m[0] == "execution_error"]
                    detail = msgs[-1][1].get("exception_message", "") if msgs else ""
                    raise ComfyError(f"ComfyUI job failed: {detail}"[:800])
                if entry.get("outputs") is not None and status.get("completed", True):
                    return entry["outputs"]
            if time.monotonic() - t0 > timeout:
                raise ComfyError(f"ComfyUI job {prompt_id} timed out after {timeout:.0f} s")
            time.sleep(poll)

    def interrupt(self) -> None:
        try:
            self._request("POST", "/interrupt", b"")
        except ComfyError:
            pass

    def download(self, file_info: dict, dest: Path) -> Path:
        q = urllib.parse.urlencode({"filename": file_info["filename"], "subfolder": file_info.get("subfolder", ""),
                                    "type": file_info.get("type", "output")})
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self._request("GET", f"/view?{q}", timeout=600))
        return dest

    @staticmethod
    def output_files(outputs: dict) -> list[dict]:
        """All files a finished job produced (images, videos, gifs, audio)."""
        files = []
        for node_out in outputs.values():
            for key in ("videos", "gifs", "images", "audio"):
                for f in node_out.get(key, []) or []:
                    if isinstance(f, dict) and f.get("filename"):
                        files.append(f)
        return files

    def run(self, workflow: dict, dest_dir: Path, stem: str, cancel_check=None, timeout: float = 3600) -> Path:
        """Queue, wait, download the first output file. Retries once on transient failure."""
        last: Exception | None = None
        for attempt in range(2):
            try:
                pid = self.queue(workflow)
                outputs = self.wait(pid, timeout=timeout, cancel_check=cancel_check)
                files = self.output_files(outputs)
                if not files:
                    raise ComfyError("ComfyUI job produced no output file")
                f = files[0]
                return self.download(f, Path(dest_dir) / f"{stem}{Path(f['filename']).suffix}")
            except ComfyError as exc:
                if "cancelled" in str(exc) or "missing node" in str(exc) or "rejected" in str(exc):
                    raise
                last = exc
                log.warning("ComfyUI attempt %d failed: %s", attempt + 1, exc)
        raise last  # type: ignore[misc]
