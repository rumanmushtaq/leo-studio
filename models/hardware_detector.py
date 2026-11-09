"""Detect CPU, RAM, GPU, CUDA, disk, Blender and FFmpeg at startup."""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psutil

from utils.config import PROC_KW, PROJECT_ROOT, find_blender, find_ffmpeg, find_ffprobe


@dataclass
class HardwareReport:
    os_name: str
    cpu_model: str
    physical_cores: int
    logical_cores: int
    ram_total_gb: float
    ram_available_gb: float
    gpus: list[str] = field(default_factory=list)
    nvidia_gpu: bool = False
    cuda_available: bool | None = None  # None = not checked (torch not imported)
    disk_free_gb: float = 0.0
    blender_path: str | None = None
    blender_version: str | None = None
    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None
    recommended_quality: str = "standard"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def summary_lines(self) -> list[str]:
        return [
            f"OS: {self.os_name}",
            f"CPU: {self.cpu_model} ({self.physical_cores} cores / {self.logical_cores} threads)",
            f"RAM: {self.ram_total_gb:.1f} GB total, {self.ram_available_gb:.1f} GB free",
            f"GPU: {', '.join(self.gpus) or 'none detected'}"
            + (" (CUDA available)" if self.cuda_available else ""),
            f"Disk free: {self.disk_free_gb:.1f} GB",
            f"Blender: {self.blender_version or 'NOT FOUND'}",
            f"FFmpeg: {'found' if self.ffmpeg_path else 'NOT FOUND'}"
            + ("" if self.ffprobe_path else " (ffprobe missing: using ffmpeg-based probing)"),
        ]


def _cpu_model() -> str:
    if platform.system() == "Windows":
        try:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    if platform.system() == "Linux":
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def _gpus() -> list[str]:
    names: list[str] = []
    if shutil.which("nvidia-smi"):
        res = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                             capture_output=True, text=True, **PROC_KW)
        names += [f"NVIDIA {n.strip()}" for n in res.stdout.splitlines() if n.strip()]
    if platform.system() == "Linux" and shutil.which("lspci"):
        res = subprocess.run(["lspci"], capture_output=True, text=True, **PROC_KW)
        for line in res.stdout.splitlines():
            if re.search(r"VGA|3D controller|Display controller", line):
                desc = line.split(":", 2)[-1].strip()
                if not any(desc in n for n in names):
                    names.append(desc)
    elif platform.system() == "Windows":
        # wmic was removed from Windows 11 24H2; PowerShell CIM works on Windows 10 and 11
        try:
            res = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
                                 capture_output=True, text=True, timeout=30, **PROC_KW)
            names += [n.strip() for n in res.stdout.splitlines() if n.strip() and n.strip() not in names]
        except (OSError, subprocess.TimeoutExpired):
            pass
    return names


def blender_version(path: str | None) -> str | None:
    if not path:
        return None
    try:
        res = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=60, **PROC_KW)
        first = res.stdout.strip().splitlines()[0] if res.stdout.strip() else ""
        return first or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_cuda() -> bool:
    """Import torch only when asked: it costs ~300 MB of RAM."""
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def detect(check_torch: bool = False) -> HardwareReport:
    vm = psutil.virtual_memory()
    blender = find_blender()
    rep = HardwareReport(
        os_name=f"{platform.system()} {platform.release()}"
        + (f" ({_os_pretty()})" if platform.system() == "Linux" else ""),
        cpu_model=_cpu_model(),
        physical_cores=psutil.cpu_count(logical=False) or 1,
        logical_cores=psutil.cpu_count(logical=True) or 1,
        ram_total_gb=vm.total / 1e9,
        ram_available_gb=vm.available / 1e9,
        gpus=_gpus(),
        disk_free_gb=shutil.disk_usage(PROJECT_ROOT).free / 1e9,
        blender_path=blender,
        blender_version=blender_version(blender),
        ffmpeg_path=find_ffmpeg(),
        ffprobe_path=find_ffprobe(),
    )
    rep.nvidia_gpu = any("NVIDIA" in g.upper() for g in rep.gpus)
    if check_torch:
        rep.cuda_available = check_cuda()
    if not rep.blender_path:
        rep.warnings.append("Blender 4.x not found. Install Blender 4.5 LTS (blender.org, or on Windows "
                            "'winget install BlenderFoundation.Blender.LTS.4.5') or set LEO_BLENDER.")
    if not rep.ffmpeg_path:
        rep.warnings.append("FFmpeg not found. Run: pip install imageio-ffmpeg  (or install FFmpeg: "
                            "'sudo apt install ffmpeg' on Linux, 'winget install Gyan.FFmpeg' on Windows)")
    if rep.ram_total_gb < 7.5:
        rep.warnings.append("Less than 8 GB RAM: rendering one scene at a time with low-poly assets.")
    if rep.disk_free_gb < 5:
        rep.warnings.append("Less than 5 GB free disk: rendered frames need ~1-3 GB per episode.")
    rep.recommended_quality = "standard" if (rep.nvidia_gpu or rep.ram_total_gb >= 15) else "preview"
    return rep


def _os_pretty() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return ""


if __name__ == "__main__":
    r = detect(check_torch=os.environ.get("LEO_CHECK_TORCH") == "1")
    print("\n".join(r.summary_lines()))
    for w in r.warnings:
        print("WARNING:", w)
