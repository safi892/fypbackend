"""Portable discovery and invocation helpers for C++ compilers."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CxxCompiler:
    """A C++ compiler that can be invoked with either GNU or MSVC flags."""

    command: str
    is_msvc: bool

    def syntax_command(self, source: Path) -> list[str]:
        """Build a C++17 syntax-check command for ``source``."""
        if self.is_msvc:
            return [self.command, "/nologo", "/std:c++17", "/Zs", "/TP", str(source)]
        return [self.command, "-fsyntax-only", "-std=c++17", "-x", "c++", str(source)]

    def build_command(self, source: Path, binary: Path) -> list[str]:
        """Build an optimized C++17 executable from ``source``."""
        if self.is_msvc:
            return [
                self.command,
                "/nologo",
                "/std:c++17",
                "/O2",
                "/EHsc",
                "/TP",
                str(source),
                f"/Fe{binary.with_suffix('.exe')}",
            ]
        return [self.command, "-std=c++17", "-O2", "-o", str(binary), str(source)]

    def executable_path(self, binary: Path) -> Path | None:
        """Return the emitted program path, accounting for Windows' ``.exe`` suffix."""
        candidates = (
            (binary.with_suffix(".exe"), binary) if self.is_msvc or os.name == "nt" else (binary,)
        )
        return next((candidate for candidate in candidates if candidate.is_file()), None)


def find_cxx_compiler() -> CxxCompiler | None:
    """Find a C++17 compiler on macOS, Linux, or Windows."""
    candidates = [os.getenv("CXX"), "c++", "g++", "clang++", "cl.exe", "cl"]
    for candidate in candidates:
        if not candidate:
            continue
        command = shutil.which(candidate)
        if command is None:
            continue
        name = Path(command).name.lower()
        return CxxCompiler(command=command, is_msvc=name in {"cl", "cl.exe"})
    return None
