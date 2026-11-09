"""A fake ComfyUI server (same HTTP API) that fabricates outputs, for testing the AI video mode
without a GPU. Images: solid PNGs; videos: FFmpeg-encoded clips of the requested length."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

from utils.config import find_ffmpeg

ALL_NODES = ["CheckpointLoaderSimple", "LoadImage", "ImageScale", "VAEEncode", "CLIPTextEncode", "KSampler",
             "VAEDecode", "SaveImage", "UNETLoader", "ModelSamplingSD3", "CLIPLoader", "VAELoader",
             "Wan22ImageToVideoLatent", "CreateVideo", "SaveVideo", "LoadVideo", "GetVideoComponents", "LoadAudio",
             "LatentSyncNode"]


class MockComfy:
    def __init__(self, root: Path, nodes: list[str] | None = None):
        self.root = Path(root)
        (self.root / "input").mkdir(parents=True, exist_ok=True)
        (self.root / "output").mkdir(parents=True, exist_ok=True)
        self.nodes = nodes if nodes is not None else ALL_NODES
        self.history: dict[str, dict] = {}
        self.jobs: list[set[str]] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()

    def _make_output(self, wf: dict) -> dict:
        types = {n["class_type"]: (k, n) for k, n in wf.items()}
        self.jobs.append(set(types))
        name = uuid.uuid4().hex[:8]
        if "SaveImage" in types:
            sc = types.get("ImageScale", (None, {"inputs": {"width": 512, "height": 512}}))[1]["inputs"]
            out = self.root / "output" / f"img_{name}.png"
            Image.new("RGB", (int(sc["width"]), int(sc["height"])), (40, 120, 200)).save(out)
            return {types["SaveImage"][0]: {"images": [{"filename": out.name, "subfolder": "", "type": "output"}]}}
        if "LatentSyncNode" in types:
            src = self.root / "input" / types["LoadVideo"][1]["inputs"]["file"]
            out = self.root / "output" / f"lips_{name}.mp4"
            shutil.copy(src, out)
            return {types["SaveVideo"][0]: {"videos": [{"filename": out.name, "subfolder": "", "type": "output"}]}}
        lat = types["Wan22ImageToVideoLatent"][1]["inputs"]
        img = self.root / "input" / types["LoadImage"][1]["inputs"]["image"]
        fps = types["CreateVideo"][1]["inputs"]["fps"]
        out = self.root / "output" / f"clip_{name}.mp4"
        subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-loop", "1", "-i", str(img), "-vf",
                        f"scale={lat['width']}:{lat['height']},format=yuv420p", "-frames:v", str(lat["length"]),
                        "-r", str(fps), "-c:v", "libx264", "-preset", "ultrafast", str(out)], check=True)
        return {types["SaveVideo"][0]: {"videos": [{"filename": out.name, "subfolder": "", "type": "output"}]}}

    def _handler(self):
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj, ctype="application/json", code=200):
                body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlparse(self.path)
                if u.path == "/system_stats":
                    return self._send({"system": {"comfyui_version": "mock"},
                                       "devices": [{"name": "Mock RTX 4090", "vram_total": 24e9}]})
                if u.path == "/object_info":
                    return self._send({n: {} for n in mock.nodes})
                if u.path.startswith("/history/"):
                    pid = u.path.rsplit("/", 1)[1]
                    return self._send({pid: mock.history[pid]} if pid in mock.history else {})
                if u.path == "/view":
                    q = parse_qs(u.query)
                    return self._send((mock.root / q.get("type", ["output"])[0] / q["filename"][0]).read_bytes(),
                                      "application/octet-stream")
                self._send({"error": "not found"}, code=404)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                if self.path == "/upload/image":
                    m = re.search(rb'filename="([^"]+)"\r\nContent-Type: [^\r]+\r\n\r\n', body)
                    fname = m.group(1).decode()
                    data = body[m.end():body.rfind(b"\r\n--", 0, body.rfind(b"name=\"overwrite\""))]
                    (mock.root / "input" / fname).write_bytes(data)
                    return self._send({"name": fname, "subfolder": "", "type": "input"})
                if self.path == "/prompt":
                    wf = json.loads(body)["prompt"]
                    pid = uuid.uuid4().hex
                    outputs = mock._make_output(wf)
                    mock.history[pid] = {"status": {"status_str": "success", "completed": True}, "outputs": outputs}
                    return self._send({"prompt_id": pid, "number": 1, "node_errors": {}})
                if self.path == "/interrupt":
                    return self._send({})
                self._send({"error": "not found"}, code=404)

        return H
