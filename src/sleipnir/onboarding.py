"""What a fresh install still needs, as data that both surfaces render.

Setup used to be a terminal command covering host control only, so a new
operator still had to discover Ollama, a Whisper model, a Piper voice and the
local-model alias by reading this repository.  Everything a wizard shows --
CLI or GUI -- comes from :func:`probe`, so the two can never disagree about
what is missing or about the command that fixes it.

Two rules this module keeps:

* **No model size is quoted from memory.**  Sizes are read from Ollama's own
  library page at wizard time and reported as unknown when that read fails.
  A guessed download size is what makes a setup wizard lie about whether a
  model will fit.
* **Capacity and pressure are different questions.**  Whether a model *can*
  run is a fact about installed memory; whether it will run well *right now*
  is a fact about free memory.  Both are reported, because judging capacity on
  free memory rules out the machine that is already running the assistant, and
  judging pressure on installed memory promises a smooth first reply on a box
  with thirty browser tabs open.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import tempfile
import subprocess  # nosec B404 - fixed argv probes, never shell
from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Mapping, Sequence

import httpx

from sleipnir import platform

#: Where the local-model family lives. The *family* is a Sleipnir decision --
#: it must be vision-capable, because reading the operator's screen is the
#: assistant's main job. The sizes are not a decision and are fetched live.
#:
#: MEASURED 2026-09-11 on an 8 GiB RTX 5050, and this is why the family is not
#: ``qwen3-vl``: with ``think: false`` -- which the chat, look and tool lanes
#: all use -- ``qwen3-vl:8b`` returned *completely empty content*. Every
#: greeting fell through to the "I'm here." placeholder after 34.8 s, both
#: arithmetic questions exhausted the 40 s reasoning deadline without an
#: answer, and a two-step browser task timed out at 180 s. The same prompts on
#: ``qwen3.5:4b`` answered correctly in 0.57 s, 13.1 s and 41.9 s. ``qwen3.5``
#: reports ``vision`` among its capabilities and does not have the defect.
MODEL_FAMILY = "qwen3.5"

#: Ollama's own registry, the authority on how large a tag is. The rendered
#: library page is not usable for this: it collapses aliased tags into one row,
#: so ``:8b`` -- the tag that is also ``:latest`` -- has no size of its own
#: there and would be reported as unknown.
REGISTRY_URL = "https://registry.ollama.ai/v2/library"

#: The alias the voice lane dispatches to. Created locally from whichever tag
#: the operator picks, so changing models later never touches source.
LOCAL_ALIAS = "jarvis"

#: MEASURED 2026-09-09: 8K context was too brittle for a single vision/tool
#: follow-up -- the frame plus the tool schema plus one result overran it.
LOCAL_CONTEXT_TOKENS = 16_384

#: ``(tier, tag, minimum GiB)``. The floor is the weight plus room for the KV
#: cache at the context above; a model that only just fits will thrash.
#:
#: The low tier is not a consolation prize. MEASURED on the same 8 GiB card,
#: ``qwen3.5:9b`` was correct everywhere but 35-50% slower than the 4b on every
#: task (look 10.7 s vs 9.2 s, arithmetic 17.9 s vs 13.1 s, projectile 34.9 s
#: vs 23.2 s) and took ten steps where the 4b took five. Bigger is a real
#: upgrade only when there is room for it.
MODEL_TIERS: tuple[tuple[str, str, float], ...] = (
    ("low", "4b", 4.5),
    ("moderate", "9b", 8.0),
    ("high", "27b", 20.0),
)

_GIB = 1024**3


@dataclass(frozen=True, slots=True)
class Requirement:
    """One thing a fresh install needs, and the exact command that supplies it."""

    id: str
    label: str
    present: bool
    detail: str = ""
    fix: str = ""
    needs_root: bool = False
    #: True when the wizard resolves this by asking the operator rather than by
    #: running ``fix``. The local model is the only one: which model to install
    #: is a choice about this machine's memory, not a command anyone can write
    #: in advance.
    interactive: bool = False


@dataclass(frozen=True, slots=True)
class Headroom:
    """Free memory the operator actually has for a local model."""

    free_gib: float
    total_gib: float
    device: str
    accelerated: bool

    @property
    def summary(self) -> str:
        return (
            f"{self.free_gib:.1f} GiB free of {self.total_gib:.1f} GiB on {self.device}"
        )


@dataclass(frozen=True, slots=True)
class ModelOption:
    tier: str
    model: str
    minimum_gib: float
    download: str
    fits: bool
    note: str


def _package_manager() -> tuple[str, str] | None:
    """``(name, install template)`` for this host, or ``None`` if unknown."""
    # pacman: ``-Syu`` rather than ``-S``. A partial upgrade against a stale
    # sync database asks mirrors for a filename that has since been rebuilt.
    for manager, template in (
        ("pacman", "pacman -Syu --needed --noconfirm {packages}"),
        ("apt-get", "apt-get install -y {packages}"),
        ("dnf", "dnf install -y {packages}"),
        ("zypper", "zypper install -y {packages}"),
    ):
        if shutil.which(manager):
            return manager, template
    return None


def install_command(*packages: str) -> str:
    """The host's own install line for these packages, or ``""`` if unknown."""
    manager = _package_manager()
    if manager is None:
        return ""
    return manager[1].format(packages=" ".join(packages))


def _package_for(manager: str, names: Mapping[str, str], default: str) -> str:
    return names.get(manager, default)


def _system_requirement(
    requirement_id: str,
    label: str,
    binaries: tuple[str, ...],
    packages: Mapping[str, str],
    default_package: str,
) -> Requirement:
    found = next((name for name in binaries if shutil.which(name)), "")
    manager = _package_manager()
    fix = ""
    if not found and manager is not None:
        fix = manager[1].format(
            packages=_package_for(manager[0], packages, default_package)
        )
    return Requirement(
        id=requirement_id,
        label=label,
        present=bool(found),
        detail=shutil.which(found) or "",
        fix=fix,
        needs_root=bool(fix),
    )


def whisper_model_fix(environment: Mapping[str, str] | None = None) -> tuple[str, Path]:
    """The download command for a Whisper model and where it lands.

    The directory is the conventional one the transcriber already searches, not
    a shell variable: a GUI autostart process does not read ``.zshrc``, so a
    model that only an interactive shell can find is a model the wake loop
    cannot use.
    """
    environment = os.environ if environment is None else environment
    data_home = Path(
        environment.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    ) / "whisper-models"
    target = data_home / "ggml-base.en.bin"
    url = (
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
    )
    # XDG_DATA_HOME is inherited process input. It must be a quoted shell word
    # before this displayable command is later passed to ``sh -c`` by setup.
    directory_word = shlex.quote(str(data_home))
    target_word = shlex.quote(str(target))
    url_word = shlex.quote(url)
    return (
        f"mkdir -p {directory_word} && "
        f"curl -L --retry 5 -C - -o {target_word} {url_word}",
        target,
    )


def alias_installed(alias: str = LOCAL_ALIAS) -> bool:
    """Whether the local voice alias already exists in Ollama.

    Asked of Ollama every time rather than recorded in a settings file: the
    same rule as task status, for the same reason. Derived state on disk is
    what turns "the operator deleted the model" into a repair routine instead
    of an ordinary read.
    """
    if not shutil.which("ollama"):
        return False
    try:
        result = subprocess.run(  # nosec B603 - fixed argv, no shell
            ["ollama", "list"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return any(
        line.split(":", 1)[0].split()[0] == alias
        for line in result.stdout.splitlines()[1:]
        if line.strip()
    )


def _input_requirement() -> Requirement:
    """Whether the assistant can type and click, however this platform does it.

    ``ydotool`` is the Linux answer, not the question. Windows injects through
    SendInput with nothing to install, so searching PATH for a binary reports a
    present capability as missing -- and offers no package, because none exists.
    """
    try:
        from sleipnir.capabilities.computer import probe as _probe

        found = _probe()
    except Exception:  # noqa: BLE001 - a probe that cannot run means "absent"
        found = None
    if found is not None and found.input_injection:
        return Requirement(
            id="ydotool",
            label="Input control (lets the assistant type and click for you)",
            present=True,
            detail="SendInput" if platform.IS_WINDOWS else "ydotool",
        )
    return _system_requirement(
        "ydotool",
        "ydotool (lets the assistant type and click for you)",
        ("ydotool",),
        {},
        "ydotool",
    )


def _screenshot_requirement() -> Requirement:
    """Ask the desktop backend what it would actually invoke to capture a screen.

    Returns "present" whenever the backend names a tool -- an installed binary
    on Linux, the built-in GDI path on Windows -- and falls back to the Linux
    package suggestion only when there is genuinely nothing to use.
    """
    tool = ""
    try:
        from sleipnir.capabilities.computer import probe as _probe

        tool = _probe().screenshot_tool or ""
    except Exception:  # noqa: BLE001 - a probe that cannot run means "absent"
        tool = ""
    if tool:
        return Requirement(
            id="screenshot",
            label="Screenshot tool (lets the assistant see the screen)",
            present=True,
            detail=tool,
            fix="",
        )
    return _system_requirement(
        "screenshot",
        "Screenshot tool (lets the assistant see the screen)",
        ("grim", "spectacle", "gnome-screenshot"),
        {},
        "grim",
    )


def probe(environment: Mapping[str, str] | None = None) -> list[Requirement]:
    """Everything a new install is missing, in the order it should be fixed."""
    environment = os.environ if environment is None else environment
    from sleipnir.voice.providers import piper_setup
    from sleipnir.voice.transcription import resolve_whisper_model

    items: list[Requirement] = []

    ollama = shutil.which("ollama")
    items.append(
        Requirement(
            id="ollama",
            label="Ollama (runs the local assistant model)",
            present=bool(ollama),
            detail=ollama or "",
            # Ollama's own installer; it elevates internally for the service
            # unit, which is why it is flagged as a privileged step.
            fix="" if ollama else "curl -fsSL https://ollama.com/install.sh | sh",
            needs_root=not ollama,
        )
    )

    items.append(
        _system_requirement(
            "imagemagick",
            "ImageMagick (downscales the screen frame)",
            ("magick", "convert"),
            {"apt-get": "imagemagick", "dnf": "ImageMagick"},
            "imagemagick",
        )
    )
    # Not a binary search: some platforms ship screen capture in the backend
    # itself (Windows draws through GDI), and looking only for `grim` there
    # reports "missing" for a capability that is present -- with no package to
    # suggest, because there is nothing to install. `doctor` already asks the
    # backend this question; the wizard asks the same one so the two agree.
    items.append(_screenshot_requirement())
    whisper = _system_requirement(
        "whisper",
        "whisper.cpp (transcribes your speech on this machine)",
        ("whisper-cli", "whisper-cpp"),
        {"apt-get": "whisper.cpp", "dnf": "whisper-cpp"},
        "whisper.cpp",
    )
    if not whisper.present and not whisper.fix:
        # No package manager here, which is not the same as no way to install
        # it: the project publishes a Windows build. Saying "missing" with a
        # blank fix is what turns a wizard back into an afternoon.
        whisper = replace(
            whisper,
            fix=(
                "Download whisper-bin-x64.zip from "
                "https://github.com/ggml-org/whisper.cpp/releases and put "
                "whisper-cli.exe on PATH"
            ),
        )
    items.append(whisper)

    model = resolve_whisper_model(environment)
    command, target = whisper_model_fix(environment)
    items.append(
        Requirement(
            id="whisper-model",
            label="Speech model (about 150 MB, downloaded once)",
            present=model is not None,
            detail=str(model or target),
            fix="" if model else command,
        )
    )

    voice = piper_setup(dict(environment))
    items.append(
        Requirement(
            id="piper",
            label="Piper voice (what the assistant speaks with)",
            present=voice is not None,
            detail="" if voice is None else "installed",
            # Deliberately not a PATH lookup: Arch's `extra/piper` is an
            # unrelated gaming-mouse configurator that would satisfy a
            # `which piper` and then fail to synthesise anything.
            fix=""
            if voice
            else "sleipnir setup --voice  # installs Piper into ~/.local/opt/piper",
        )
    )

    items.append(_input_requirement())
    # /dev/uinput is how Linux grants input injection. Windows reaches
    # SendInput without a device node, so there is nothing to permit and the
    # wizard should not invent a step.
    writable = platform.IS_WINDOWS or os.access("/dev/uinput", os.W_OK)
    items.append(
        Requirement(
            id="uinput",
            label="Input device permission",
            present=writable,
            fix="" if writable else "sleipnir setup --yes",
            needs_root=not writable,
        )
    )
    items.append(
        Requirement(
            id="local-model",
            label="Local assistant model",
            present=alias_installed(),
            detail=LOCAL_ALIAS,
            interactive=True,
        )
    )
    return items


def _nvidia_headroom() -> Headroom | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        # Fixed argv, no shell: this string never reaches an interpreter.
        result = subprocess.run(  # nosec B603
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    parts = [piece.strip() for piece in line.split(",")]
    if len(parts) != 3:
        return None
    try:
        total, free = float(parts[1]), float(parts[2])
    except ValueError:
        return None
    return Headroom(free / 1024, total / 1024, parts[0], accelerated=True)


def _amd_headroom() -> Headroom | None:
    for device in sorted(Path("/sys/class/drm").glob("card*/device")):
        total_file = device / "mem_info_vram_total"
        used_file = device / "mem_info_vram_used"
        if not total_file.is_file():
            continue
        try:
            total = int(total_file.read_text().strip())
            used = int(used_file.read_text().strip()) if used_file.is_file() else 0
        except (OSError, ValueError):
            continue
        if total <= 0:
            continue
        return Headroom((total - used) / _GIB, total / _GIB, "AMD GPU", accelerated=True)
    return None


def _system_headroom() -> Headroom:
    """Free system RAM, the fallback when there is no usable GPU.

    ``MemAvailable`` rather than ``MemFree``: the kernel's own estimate of what
    a new allocation can actually claim, which is the number the operator's
    current browser tabs have already reduced.
    """
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            number = rest.strip().split(" ", 1)[0]
            if number.isdigit():
                values[key] = int(number)
    except OSError:
        return Headroom(0.0, 0.0, "unknown", accelerated=False)
    total = values.get("MemTotal", 0) * 1024
    available = values.get("MemAvailable", values.get("MemFree", 0)) * 1024
    return Headroom(available / _GIB, total / _GIB, "system RAM", accelerated=False)


def headroom() -> Headroom:
    """What is free for a model right now, GPU first."""
    return _nvidia_headroom() or _amd_headroom() or _system_headroom()


async def _tag_size(
    tag: str, *, client: httpx.AsyncClient
) -> str:
    """Download size of one tag, read from its registry manifest.

    Sizes are the sum of the manifest's layers, which is what ``ollama pull``
    transfers. An unreachable registry answers ``unknown`` rather than a
    remembered number: a wizard that guesses a download size is a wizard that
    lies about whether the model will fit.
    """
    try:
        response = await client.get(
            f"{REGISTRY_URL}/{MODEL_FAMILY}/manifests/{tag}",
            headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
        )
        response.raise_for_status()
        layers = response.json()["layers"]
        total = sum(int(layer["size"]) for layer in layers)
    except Exception:  # noqa: BLE001 - an unreachable registry is not a setup failure
        return "unknown"
    if total <= 0:
        return "unknown"
    return f"{total / 1e9:.1f}GB"


async def model_options(
    available: Headroom | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[ModelOption]:
    """The three headroom tiers, with live download sizes and a fit verdict.

    The fit verdict never depends on the size lookup: it compares this
    machine's memory against the tier's own floor, which is a property of the
    tier and is known offline.
    """
    available = headroom() if available is None else available
    async with httpx.AsyncClient(transport=transport, timeout=20) as client:
        sizes = await asyncio.gather(
            *(_tag_size(tag, client=client) for _, tag, _ in MODEL_TIERS)
        )

    options: list[ModelOption] = []
    for (tier, tag, minimum), download in zip(MODEL_TIERS, sizes, strict=True):
        # Capacity is judged against total memory, not what is free this
        # second: loading a new model unloads the old one, so free memory
        # measured while the current assistant is resident would rule out the
        # very machine that is already running it. Free memory is still
        # reported, because it is what decides whether the operator should
        # close something before the first reply.
        fits = available.total_gib >= minimum
        pressure = (
            ""
            if available.free_gib >= minimum
            else f" Only {available.free_gib:.1f} GiB is free right now, so close what you can first."
        )
        if fits and available.accelerated:
            note = f"Runs on your GPU.{pressure}"
        elif fits:
            note = f"Runs on the CPU; expect several seconds per reply.{pressure}"
        else:
            note = (
                f"Needs about {minimum:.1f} GiB; this machine has "
                f"{available.total_gib:.1f} GiB on {available.device}."
            )
        options.append(
            ModelOption(
                tier=tier,
                model=f"{MODEL_FAMILY}:{tag}",
                minimum_gib=minimum,
                download=download,
                fits=fits,
                note=note,
            )
        )
    return options


def alias_modelfile(model: str) -> str:
    """The local alias definition the voice lane dispatches to."""
    return f"FROM {model}\nPARAMETER num_ctx {LOCAL_CONTEXT_TOKENS}\n"


__all__ = [
    "Headroom", "LOCAL_ALIAS", "LOCAL_CONTEXT_TOKENS", "MODEL_FAMILY",
    "MODEL_TIERS", "ModelOption", "Requirement", "alias_modelfile", "headroom",
    "StepResult", "apply_root_steps", "apply_user_steps", "install_command",
    "REGISTRY_URL", "model_options", "probe", "pull_model", "root_batch",
    "whisper_model_fix",
]


# --- applying the plan ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepResult:
    id: str
    ok: bool
    detail: str


def root_batch(requirements: Sequence[Requirement]) -> str:
    """Every privileged fix as one shell script, or ``""`` if there are none.

    One script rather than one call per package because ``sudo -A`` spawns its
    askpass helper fresh for every prompt: six separate installs is six
    pinentry dialogs, which is most of what made setup feel like an afternoon.
    ``set -e`` so a failed package stops the batch instead of reporting success
    for the ones after it.
    """
    fixes = [item.fix for item in requirements if not item.present and item.needs_root and item.fix]
    if not fixes:
        return ""
    return "set -e\n" + "\n".join(fixes) + "\n"


async def _run(command: str, *, timeout: float = 1800.0) -> StepResult | str:
    process = await asyncio.create_subprocess_exec(
        "sh",
        "-c",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return "timed out"
    if process.returncode != 0:
        return output.decode("utf-8", "replace").strip()[-480:] or f"exit {process.returncode}"
    return ""


async def apply_user_steps(requirements: Sequence[Requirement]) -> list[StepResult]:
    """Run every unprivileged fix. Downloads, never installs."""
    results: list[StepResult] = []
    for item in requirements:
        if item.present or item.needs_root or not item.fix or item.fix.startswith("sleipnir "):
            continue
        failure = await _run(item.fix)
        results.append(StepResult(item.id, not failure, failure or "installed"))
    return results


async def apply_root_steps(requirements: Sequence[Requirement]) -> StepResult | None:
    """Run the whole privileged batch behind a single credential prompt.

    Routed through ``sleipnir sudo`` rather than plain ``sudo``: neither a tool
    subprocess nor the desktop host has a TTY, so bare sudo fails with "a
    terminal is required" at the worst possible moment.
    """
    script = root_batch(requirements)
    if not script:
        return None
    failure = await _run(f"sleipnir sudo -- sh -c {shlex.quote(script)}")
    return StepResult("system-packages", not failure, failure or "installed")


async def pull_model(model: str, *, alias: str = LOCAL_ALIAS) -> StepResult:
    """Download the chosen model and give it the alias the voice lane uses.

    The alias carries the context size rather than the operator's shell or a
    hand-written Modelfile, which is the step a new user had no way to know
    about: without it the model loads at its default context and a single
    vision/tool follow-up overruns it.
    """
    if not re.fullmatch(r"[\w.:/-]{1,120}", model):
        raise ValueError(f"refusing to pull an implausible model name {model!r}")
    if failure := await _run(f"ollama pull {shlex.quote(model)}", timeout=7200.0):
        return StepResult("model", False, failure)
    with tempfile.TemporaryDirectory(prefix="sleipnir-alias-") as root:
        modelfile = Path(root) / "Modelfile"
        modelfile.write_text(alias_modelfile(model), encoding="utf-8")
        failure = await _run(
            f"ollama create {shlex.quote(alias)} -f {shlex.quote(str(modelfile))}"
        )
    return StepResult("model", not failure, failure or f"{alias} ready ({model})")
