#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


RENDERER_OUTPUT_NAME = "auteur-renderer"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the packaged renderer bundle for Electron."
    )
    parser.add_argument(
        "--workspace",
        default=str(Path(__file__).resolve().parents[2]),
        help="Repository root directory",
    )
    parser.add_argument(
        "--platform",
        choices=["auto", "windows", "linux", "darwin"],
        default="auto",
        help="Target platform (default: current platform)",
    )
    parser.add_argument(
        "--python-bin",
        default="",
        help="Python executable to run PyInstaller",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default=os.getenv("RENDERER_FFMPEG_BIN", ""),
        help="Override path to ffmpeg binary",
    )
    parser.add_argument(
        "--ffprobe-bin",
        default=os.getenv("RENDERER_FFPROBE_BIN", ""),
        help="Override path to ffprobe binary",
    )
    return parser.parse_args()


def detect_platform(platform_arg: str) -> str:
    if platform_arg != "auto":
        return platform_arg
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def platform_executable(name: str, platform_name: str) -> str:
    if platform_name == "windows":
        return f"{name}.exe"
    return name


def clean_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def resolve_binary(binary_name: str, override: str) -> Path:
    if override:
        candidate = Path(override).expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"Binary not found: {candidate}")
        return _resolve_windows_shim(binary_name, candidate)

    resolved = shutil.which(binary_name)
    if not resolved:
        raise FileNotFoundError(
            f"Could not resolve '{binary_name}' in PATH. Set --{binary_name}-bin instead."
        )
    return _resolve_windows_shim(binary_name, Path(resolved).resolve())


def _resolve_windows_shim(binary_name: str, candidate: Path) -> Path:
    if os.name != "nt":
        return candidate

    candidate_lower = str(candidate).lower().replace("\\", "/")
    if "/chocolatey/bin/" not in candidate_lower:
        return candidate

    package_names = [binary_name]
    if binary_name in {"ffmpeg", "ffprobe"}:
        package_names = ["ffmpeg", binary_name]

    choco_root = candidate.parent.parent
    for package_name in package_names:
        path_candidates = [
            choco_root
            / "lib"
            / package_name
            / "tools"
            / package_name
            / "bin"
            / candidate.name,
            choco_root / "lib" / package_name / "tools" / "bin" / candidate.name,
        ]
        for real_binary in path_candidates:
            if real_binary.exists():
                print(
                    f"Resolved Chocolatey shim for {binary_name}: "
                    f"{candidate} -> {real_binary}"
                )
                return real_binary.resolve()

    raise FileNotFoundError(
        f"Resolved '{binary_name}' to Chocolatey shim at {candidate}, but could not "
        "find the real binary under Chocolatey lib tools directories. "
        f"Set --{binary_name}-bin to the actual executable path."
    )


def copy_binary(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if os.name != "nt":
        destination.chmod(destination.stat().st_mode | 0o755)


def run_pyinstaller(
    python_bin: str,
    render_job_dir: Path,
    entrypoint: Path,
    dist_dir: Path,
    work_dir: Path,
    spec_dir: Path,
) -> None:
    command = [
        python_bin,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        RENDERER_OUTPUT_NAME,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--paths",
        str(render_job_dir),
        "--hidden-import",
        "ffmpeg_renderer",
        "--hidden-import",
        "graphics_generator",
        "--hidden-import",
        "animation_engine",
        str(entrypoint),
    ]

    env = os.environ.copy()
    existing_python_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(render_job_dir)
        if not existing_python_path
        else f"{render_job_dir}{os.pathsep}{existing_python_path}"
    )

    subprocess.run(command, cwd=str(render_job_dir), env=env, check=True)


def get_render_job_python(render_job_dir: Path, python_bin: str) -> str:
    if python_bin:
        return python_bin

    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    venv_python = render_job_dir / ".venv" / scripts_dir / executable
    if venv_python.exists():
        return str(venv_python)

    if os.name == "nt":
        setup_hint = (
            "Create it with 'python -m venv .venv' and install dependencies with "
            "'.venv\\Scripts\\python.exe -m pip install -r requirements.txt pyinstaller'."
        )
    else:
        setup_hint = (
            "Create it with 'python -m venv .venv' and install dependencies with "
            "'./.venv/bin/python -m pip install -r requirements.txt pyinstaller'."
        )

    raise SystemExit(
        f"Render-job virtualenv python not found: {venv_python}. {setup_hint}"
    )


def write_bundle_manifest(bundle_dir: Path, platform_name: str) -> None:
    payload = {
        "platform": platform_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": sorted(path.name for path in bundle_dir.iterdir() if path.is_file()),
    }
    (bundle_dir / "bundle-info.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def validate_bundle_files(bundle_dir: Path, platform_name: str) -> None:
    required_files = [
        platform_executable("renderer", platform_name),
        platform_executable("ffmpeg", platform_name),
        platform_executable("ffprobe", platform_name),
    ]
    for file_name in required_files:
        file_path = bundle_dir / file_name
        if not file_path.exists():
            raise FileNotFoundError(f"Required bundled file is missing: {file_path}")
        if file_path.stat().st_size <= 0:
            raise ValueError(f"Required bundled file is empty: {file_path}")


def main() -> None:
    args = parse_args()
    platform_name = detect_platform(args.platform)

    workspace = Path(args.workspace).resolve()
    desktop_dir = workspace / "desktop"
    render_job_dir = workspace / "render-job"
    entrypoint = render_job_dir / "entrypoint.py"

    if not desktop_dir.exists():
        raise SystemExit(f"Desktop directory not found: {desktop_dir}")
    if not render_job_dir.exists():
        raise SystemExit(f"Render job directory not found: {render_job_dir}")
    if not entrypoint.exists():
        raise SystemExit(f"Renderer entrypoint not found: {entrypoint}")

    python_bin = get_render_job_python(render_job_dir, args.python_bin)

    build_root = desktop_dir / ".renderer-build"
    pyinstaller_dist = build_root / "dist"
    pyinstaller_work = build_root / "work"
    pyinstaller_spec = build_root / "spec"
    bundle_dir = desktop_dir / "render-bundle"

    clean_directory(build_root)
    clean_directory(bundle_dir)

    run_pyinstaller(
        python_bin=python_bin,
        render_job_dir=render_job_dir,
        entrypoint=entrypoint,
        dist_dir=pyinstaller_dist,
        work_dir=pyinstaller_work,
        spec_dir=pyinstaller_spec,
    )

    renderer_binary_name = platform_executable(RENDERER_OUTPUT_NAME, platform_name)
    renderer_output = pyinstaller_dist / renderer_binary_name
    if not renderer_output.exists():
        raise SystemExit(f"Expected renderer binary not found: {renderer_output}")

    bundled_renderer_name = platform_executable("renderer", platform_name)
    copy_binary(renderer_output, bundle_dir / bundled_renderer_name)

    ffmpeg_source = resolve_binary("ffmpeg", args.ffmpeg_bin)
    ffprobe_source = resolve_binary("ffprobe", args.ffprobe_bin)

    copy_binary(
        ffmpeg_source,
        bundle_dir / platform_executable("ffmpeg", platform_name),
    )
    copy_binary(
        ffprobe_source,
        bundle_dir / platform_executable("ffprobe", platform_name),
    )

    validate_bundle_files(bundle_dir, platform_name)

    license_source = render_job_dir / "FFMPEG_LICENSE.txt"
    if license_source.exists():
        copy_binary(license_source, bundle_dir / "FFMPEG_LICENSE.txt")

    write_bundle_manifest(bundle_dir, platform_name)

    print(f"Renderer bundle created at: {bundle_dir}")
    print(f"PyInstaller python: {python_bin}")
    print(f"Renderer binary: {bundled_renderer_name}")
    print(f"ffmpeg source: {ffmpeg_source}")
    print(f"ffprobe source: {ffprobe_source}")


if __name__ == "__main__":
    main()
