"""Regression tests for cross-platform paths and compiler invocation."""

from __future__ import annotations

from pathlib import Path

from app.core import database
from app.core.compiler import CxxCompiler


def test_database_accepts_a_filename_without_a_parent_directory(monkeypatch, tmp_path) -> None:
    """A Windows user may set ``DB_PATH=app.db`` rather than an absolute path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(database, "DB_PATH", "local.db")

    with database.get_db_connection() as connection:
        connection.execute("CREATE TABLE paths (id INTEGER PRIMARY KEY)")

    assert (tmp_path / "local.db").is_file()


def test_msvc_commands_and_executable_suffix_are_supported(tmp_path) -> None:
    compiler = CxxCompiler(command="cl.exe", is_msvc=True)
    source = tmp_path / "source.cpp"
    binary = tmp_path / "program"

    assert compiler.syntax_command(source) == [
        "cl.exe",
        "/nologo",
        "/std:c++17",
        "/Zs",
        "/TP",
        str(source),
    ]
    assert f"/Fe{binary.with_suffix('.exe')}" in compiler.build_command(source, binary)

    binary.with_suffix(".exe").touch()
    assert compiler.executable_path(binary) == binary.with_suffix(".exe")


def test_gnu_compiler_command_keeps_the_requested_output_path(tmp_path) -> None:
    compiler = CxxCompiler(command="g++", is_msvc=False)
    source = Path("source.cpp")
    binary = tmp_path / "program"

    assert compiler.syntax_command(source) == [
        "g++",
        "-fsyntax-only",
        "-std=c++17",
        "-x",
        "c++",
        str(source),
    ]
    assert compiler.build_command(source, binary)[-2:] == [str(binary), str(source)]
