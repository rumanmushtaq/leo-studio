"""Story idea -> full cartoon script, with a free local AI model on the CPU.

Engine: llama.cpp's ``llama-server`` (MIT, ~25 MB CPU build for Linux/Windows/macOS) running
Qwen3-4B-Instruct-2507 Q4_K_M (Apache-2.0, 2.5 GB, writes Urdu and English). Both are downloaded
once, with the user's consent, into ``tools/llama/`` and ``models/cache/llm/`` and verified by
SHA-256. The server only runs while a script is being written, then exits (frees ~3 GB of RAM).

The model is told the studio's script format, the known characters and the locations; its answer
is checked by the real script parser and sent back with the problems if it does not pass.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from core.character_manager import CharacterRegistry
from core.scene_manager import LOCATIONS, SceneManager
from core.script_parser import ScriptParser
from utils.config import MODEL_CACHE, PROC_KW, PROJECT_ROOT
from utils.logger import get_logger

log = get_logger("writer")

LLAMA_TAG = "b12211"
LLAMA_BUILDS = {  # platform -> (asset, sha256, size)
    "Linux": (f"llama-{LLAMA_TAG}-bin-ubuntu-x64.tar.gz",
              "962924b5431bc1237a9e5d26ba072d37b6fe05f79b495206e7ff6134887624c5", 23109987),
    "Windows": (f"llama-{LLAMA_TAG}-bin-win-cpu-x64.zip",
                "23729000408c6968faf5e322afc99319d3b8c576ba872ef7663d9b89810090f3", 24886431),
    "Darwin": (f"llama-{LLAMA_TAG}-bin-macos-arm64.tar.gz",
               "4da4edb437358d31d55938ad849d262ca31b0e0ffb35e9caedb727a0cd5a8f0f", 16711245),
}
MODEL = ("unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
         "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597", 2497281120)
TOOLS_DIR = PROJECT_ROOT / "tools" / "llama"
LLM_DIR = MODEL_CACHE / "llm"
DOWNLOAD_MB = round((LLAMA_BUILDS.get(platform.system(), LLAMA_BUILDS["Linux"])[2] + MODEL[3]) / 1e6)

FORMAT_RULES = """Write the script in EXACTLY this plain-text format (no markdown, no bold, no numbering other than scene numbers):

Scene 1: <short title naming the place>

Visual:
<one or two English sentences: where we are and what the characters DO, using their English names and simple verbs like walks in, runs away, flies in, waves, points, laughs, works, celebrates>

Narrator:
<one line of narration>

<CharacterName>:
<one line of dialogue>

<CharacterName> (<emotion>):
<one line of dialogue>

Rules:
- 5 or 6 scenes; every scene has a Visual block and 2 to 5 dialogue lines; whole story about 12 to 22 lines.
- Speaker labels are the character's English name followed by a colon on its own line; the spoken line goes on the next line.
- Optional emotion in brackets after the name: happy, sad, angry, surprised, scared, confident, laughing.
- Keep each spoken line short (under 15 words). Child-friendly, no violence, a kind lesson at the end.
- Only people and the Narrator speak. Animals never speak and never get a speaker label; mention them only in Visual lines.
- Use simple, everyday words a child knows. Never translate word by word; make sure every word means what you intend.
- Use only these places in scene titles or Visual lines: {places}.
- Prefer these existing characters (their look is already designed): {characters}. You may add one or two new ones.
"""


class WriterError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, sha256: str, size: int, progress: Callable[[float, str], None] | None,
              label: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "LeoStudio"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as out:
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done / max(size, 1), f"Downloading {label}: {done / 1e6:.0f} / {size / 1e6:.0f} MB")
    if _sha256(part) != sha256:
        part.unlink(missing_ok=True)
        raise WriterError(f"Download of {label} was corrupted (checksum mismatch); please try again.")
    part.replace(dest)
    return dest


class ScriptWriter:
    def __init__(self, threads: int | None = None):
        self.threads = threads or max(2, (os.cpu_count() or 4) // 2)
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None

    # -------------------------------------------------------------- install
    @staticmethod
    def server_path() -> Path | None:
        exe = "llama-server.exe" if platform.system() == "Windows" else "llama-server"
        found = sorted(TOOLS_DIR.rglob(exe)) if TOOLS_DIR.exists() else []
        if found:
            return found[0]
        on_path = shutil.which("llama-server")
        return Path(on_path) if on_path else None

    @staticmethod
    def model_path() -> Path:
        return LLM_DIR / MODEL[1]

    def is_installed(self) -> bool:
        return self.server_path() is not None and self.model_path().exists()

    def install(self, progress: Callable[[float, str], None] | None = None) -> None:
        """Download llama.cpp (CPU build) and the Qwen3-4B model; verified by SHA-256."""
        if self.server_path() is None:
            asset, sha, size = LLAMA_BUILDS.get(platform.system(), LLAMA_BUILDS["Linux"])
            archive = _download(f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/{asset}",
                                TOOLS_DIR / asset, sha, size, progress, "AI writer engine")
            target = TOOLS_DIR / LLAMA_TAG
            if asset.endswith(".zip"):
                with zipfile.ZipFile(archive) as z:
                    z.extractall(target)
            else:
                with tarfile.open(archive) as t:
                    t.extractall(target, filter="data")
            archive.unlink()
            exe = self.server_path()
            if exe and platform.system() != "Windows":
                exe.chmod(0o755)
        if not self.model_path().exists():
            repo, fname, sha, size = MODEL
            _download(f"https://huggingface.co/{repo}/resolve/main/{fname}", self.model_path(), sha, size, progress,
                      "story-writing model (Qwen3-4B)")

    # --------------------------------------------------------------- server
    def start(self, timeout: float = 240) -> None:
        exe = self.server_path()
        if exe is None or not self.model_path().exists():
            raise WriterError("The AI story writer is not installed yet.")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        cmd = [str(exe), "-m", str(self.model_path()), "--host", "127.0.0.1", "--port", str(self.port),
               "-c", "4096", "-t", str(self.threads), "--no-webui"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(exe.parent),
                                     **{k: v for k, v in PROC_KW.items() if k == "creationflags"})
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.proc.poll() is not None:
                raise WriterError("The AI writer engine stopped while starting (not enough free memory?).")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=3) as r:
                    if json.loads(r.read()).get("status") == "ok":
                        return
            except (OSError, ValueError):
                pass
            time.sleep(1.0)
        self.stop()
        raise WriterError("The AI writer engine did not start in time.")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def _chat(self, messages: list[dict], max_tokens: int = 1800) -> str:
        body = json.dumps({"messages": messages, "temperature": 0.7, "top_p": 0.9, "max_tokens": max_tokens}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]

    # ---------------------------------------------------------------- write
    @staticmethod
    def prompt(idea: str, language: str) -> list[dict]:
        reg = CharacterRegistry()
        chars = ", ".join(f"{d['name']} ({d.get('appearance', d.get('role', ''))[:70]})"
                          for cid, d in reg.presets.items() if not d.get("voice_only"))
        rules = FORMAT_RULES.format(places=", ".join(p.replace("_", " ") for p in LOCATIONS), characters=chars)
        lang = ("Write all Narrator and character lines in natural, simple Urdu (Urdu script) as spoken in "
                "Pakistani homes, for children (for example: goat = بکری, dog = کتا, school = اسکول). "
                "Keep scene titles, Visual lines and speaker labels in English." if language == "ur" else
                "Write everything in simple English.")
        return [{"role": "system", "content": "You write short children's cartoon episodes for a 3D animation studio. "
                                              + rules + "\n" + lang},
                {"role": "user", "content": f"Story idea: {idea.strip()}\n\nWrite the full script now."}]

    @staticmethod
    def clean(text: str) -> str:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
        text = text.replace("**", "").replace("```", "")
        text = re.sub(r"^#+\s*", "", text, flags=re.M)
        return text.strip() + "\n"

    @staticmethod
    def problems(script: str) -> list[str]:
        parsed = ScriptParser().parse(script)
        issues = list(parsed.report.errors)
        if parsed.report.ok:
            SceneManager(CharacterRegistry()).enrich(parsed)
            if len(parsed.scenes) < 3:
                issues.append(f"only {len(parsed.scenes)} scenes; write 5 or 6")
            lines = parsed.all_dialogue_events()
            if len(lines) < 8:
                issues.append(f"only {len(lines)} dialogue lines; write 12 to 22")
            for s in parsed.scenes:
                if not s.characters:
                    issues.append(f"scene {s.id} has no characters in its Visual line or dialogue")
            issues += [w for w in parsed.report.warnings if "unlabeled" in w][:3]
        return issues

    def write(self, idea: str, language: str = "ur", attempts: int = 3,
              progress: Callable[[float, str], None] | None = None) -> str:
        """Return a script that passes the studio's parser (raises WriterError otherwise)."""
        started = self.proc is None
        if started:
            if progress:
                progress(0.05, "Starting the AI story writer…")
            self.start()
        try:
            messages = self.prompt(idea, language)
            best, best_issues = "", ["no script"]
            for k in range(attempts):
                if progress:
                    progress(0.15 + 0.8 * k / attempts, f"Writing the story (attempt {k + 1})…")
                script = self.clean(self._chat(messages))
                issues = self.problems(script)
                if len(issues) < len(best_issues):
                    best, best_issues = script, issues
                if not issues:
                    return script
                log.info("Script attempt %d needs fixes: %s", k + 1, issues)
                messages += [{"role": "assistant", "content": script},
                             {"role": "user", "content": "Fix these problems and write the whole script again in "
                                                         "the exact format: " + "; ".join(issues[:6])}]
            if best and not any("No dialogue" in i or "empty" in i for i in best_issues):
                return best  # usable; the remaining notes are warnings
            raise WriterError("The AI writer could not produce a valid script: " + "; ".join(best_issues[:4]))
        finally:
            if started:
                self.stop()
