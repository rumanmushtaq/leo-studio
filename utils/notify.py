"""Desktop notification when a long job finishes (Linux, Windows, macOS; best effort)."""
from __future__ import annotations

import platform
import shutil
import subprocess

from utils.config import PROC_KW


def notify(title: str, message: str, icon: str | None = None) -> bool:
    system = platform.system()
    try:
        if system == "Linux" and shutil.which("notify-send"):
            cmd = ["notify-send", "-a", "Leo 3D AI Cartoon Studio", title, message]
            if icon:
                cmd[1:1] = ["-i", icon]
            subprocess.Popen(cmd, **PROC_KW)
            return True
        if system == "Windows":
            ps = ("Add-Type -AssemblyName System.Windows.Forms; $n = New-Object System.Windows.Forms.NotifyIcon; "
                  "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
                  f"$n.ShowBalloonTip(10000, '{title.replace(chr(39), '')}', '{message.replace(chr(39), '')}', "
                  "'Info'); Start-Sleep -Seconds 11; $n.Dispose()")
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], **PROC_KW)
            return True
        if system == "Darwin":
            subprocess.Popen(["osascript", "-e", f'display notification "{message}" with title "{title}"'])
            return True
    except OSError:
        pass
    return False
