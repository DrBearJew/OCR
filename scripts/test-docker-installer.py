#!/usr/bin/env python3
"""Focused stdlib regression for the published-image Docker installer."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-docker.sh"
COMPOSE = ROOT / "deploy" / "docker" / "compose.yml"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def install_mocks(root: Path) -> tuple[Path, Path]:
    bindir = root / "mock-bin"
    bindir.mkdir()
    log_path = root / "calls.jsonl"
    python = sys.executable
    mocks = {
        "docker": f'''#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["MOCK_LOG"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps(["docker", *args]) + "\\n")
if args[:3] == ["compose", "version", "--short"]:
    print(os.environ.get("MOCK_COMPOSE_VERSION", "2.30.0"))
    raise SystemExit(0)
if args == ["info"]:
    raise SystemExit(0)
if args[:2] == ["ps", "-aq"]:
    print(os.environ.get("MOCK_PROJECT_CONTAINER", ""))
    raise SystemExit(0)
if args and args[0] == "ps" and "-q" in args and "label=com.docker.compose.service=metadata" in args:
    try:
        running = open(os.environ["MOCK_DOCKER_STATE"], encoding="utf-8").read() == "metadata"
    except FileNotFoundError:
        running = False
    if running:
        print("mock-metadata-container")
    raise SystemExit(0)
if args and args[0] == "stop":
    open(os.environ["MOCK_DOCKER_STATE"], "w", encoding="utf-8").write("")
    raise SystemExit(0)
if args[:3] == ["volume", "ls", "-q"]:
    print(os.environ.get("MOCK_PROJECT_VOLUME", ""))
    raise SystemExit(0)
if args and args[0] == "inspect":
    if any("working_dir" in arg for arg in args):
        print(os.environ.get("MOCK_PROJECT_DIRECTORY", "foreign-directory"))
    else:
        print(os.environ.get("MOCK_METADATA_HEALTH", "healthy"))
    raise SystemExit(0)
if args and args[0] == "compose":
    managed = (
        "COMPOSE_FILE", "COMPOSE_PROFILES", "DOKOCR_IMAGE_TAG", "DOKOCR_METADATA_ENABLED",
        "DOKOCR_METADATA_RUNTIME", "DOKOCR_METADATA_URL", "DOKOCR_METADATA_MODEL",
        "DOKOCR_METADATA_EXTERNAL_URL", "DOKOCR_METADATA_EXTERNAL_MODEL",
        "DOKOCR_METADATA_GPU_LAYERS", "DOKOCR_METADATA_DEVICES",
    )
    if any(name in os.environ for name in managed):
        print("installer leaked inherited Compose setting", file=sys.stderr)
        raise SystemExit(91)
    state_path = os.environ["MOCK_DOCKER_STATE"]
    if "config" in args:
        raise SystemExit(int(os.environ.get("MOCK_CONFIG_EXIT", "0")))
    if "pull" in args:
        raise SystemExit(int(os.environ.get("MOCK_PULL_EXIT", "0")))
    if "up" in args:
        if "--profile" in args and "metadata" in args:
            with open(state_path, "w", encoding="utf-8") as stream:
                stream.write("metadata")
        exit_code = int(os.environ.get("MOCK_UP_EXIT", "0"))
        if exit_code:
            print(os.environ.get("MOCK_UP_ERROR", "mock start failure"), file=sys.stderr)
        raise SystemExit(exit_code)
    if "ps" in args:
        try:
            running = open(state_path, encoding="utf-8").read() == "metadata"
        except FileNotFoundError:
            running = False
        if running:
            print("mock-metadata-container")
        raise SystemExit(0)
    if "stop" in args and "metadata" in args:
        open(state_path, "w", encoding="utf-8").write("")
        raise SystemExit(0)
raise SystemExit(0)
''',
        "curl": f'''#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["MOCK_LOG"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps(["curl", *args]) + "\\n")
url = args[-1] if args else ""
if url.startswith("https://raw.githubusercontent.com/"):
    name = url.rsplit("/", 1)[-1]
    exit_name = "MOCK_OVERRIDE_DOWNLOAD_EXIT" if name.startswith("compose.metadata-") else "MOCK_DOWNLOAD_EXIT"
    if int(os.environ.get(exit_name, "0")):
        raise SystemExit(int(os.environ[exit_name]))
    sources = {{
        "compose.yml": "MOCK_COMPOSE_SOURCE",
        "compose.metadata-cuda.yml": "MOCK_CUDA_SOURCE",
        "compose.metadata-vulkan.yml": "MOCK_VULKAN_SOURCE",
    }}
    if name not in sources:
        raise SystemExit(2)
    output = args[args.index("--output") + 1]
    with open(output, "w", encoding="utf-8") as stream:
        stream.write(open(os.environ[sources[name]], encoding="utf-8").read())
    raise SystemExit(0)
raise SystemExit(int(os.environ.get("MOCK_READY_EXIT", "0")))
''',
        "openssl": f'''#!{python}
import hashlib, os, sys
args = sys.argv[1:]
if len(args) != 3 or args[:2] != ["rand", "-hex"]:
    raise SystemExit(2)
size = int(args[2])
count_path = os.environ["MOCK_OPENSSL_COUNT"]
try:
    count = int(open(count_path, encoding="utf-8").read()) + 1
except FileNotFoundError:
    count = 1
with open(count_path, "w", encoding="utf-8") as stream:
    stream.write(str(count))
result = ""
while len(result) < size * 2:
    result += hashlib.sha256(str(count).encode()).hexdigest()
print(result[:size * 2])
''',
        "uname": f'''#!{python}
print("x86_64")
''',
        "sleep": f'''#!{python}
raise SystemExit(0)
''',
    }
    for name, content in mocks.items():
        executable = bindir / name
        executable.write_text(content, encoding="utf-8")
        executable.chmod(0o755)
    log_path.touch()
    return bindir, log_path


def read_calls(path: Path) -> list[list[str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def run_installer(script: Path, bindir: Path, log: Path, compose_source: Path, directory: Path,
                  args: list[str] | None = None, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    log.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "PATH": f"{bindir}:{os.environ.get('PATH', '')}",
        "MOCK_LOG": str(log),
        "MOCK_COMPOSE_SOURCE": str(compose_source),
        "MOCK_CUDA_SOURCE": str(ROOT / "deploy" / "docker" / "compose.metadata-cuda.yml"),
        "MOCK_VULKAN_SOURCE": str(ROOT / "deploy" / "docker" / "compose.metadata-vulkan.yml"),
        "MOCK_OPENSSL_COUNT": str(log.parent / "openssl-count"),
        "MOCK_DOCKER_STATE": str(log.parent / "docker-state"),
    })
    for name in (
        "COMPOSE_FILE", "COMPOSE_PROFILES", "COMPOSE_PROJECT_NAME", "COMPOSE_ENV_FILES",
        "COMPOSE_PATH_SEPARATOR", "COMPOSE_DISABLE_ENV_FILE", "DOKOCR_IMAGE_TAG",
        "DOKOCR_METADATA_ENABLED", "DOKOCR_METADATA_RUNTIME", "DOKOCR_METADATA_URL",
        "DOKOCR_METADATA_MODEL", "DOKOCR_METADATA_EXTERNAL_URL", "DOKOCR_METADATA_EXTERNAL_MODEL",
        "DOKOCR_METADATA_GPU_LAYERS", "DOKOCR_METADATA_DEVICES", "CUDA_VISIBLE_DEVICES", "GGML_VK_VISIBLE_DEVICES", "DOKOCR_BIND", "DOKOCR_PORT",
        "DOKOCR_API_PORT", "ADMIN_USERNAME", "ADMIN_PASSWORD", "SECRET_KEY", "POSTGRES_PASSWORD",
    ):
        env.pop(name, None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(script), "--directory", str(directory), *(args or [])],
        cwd=log.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_compose_contract() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    cuda = (ROOT / "deploy" / "docker" / "compose.metadata-cuda.yml").read_text(encoding="utf-8")
    vulkan = (ROOT / "deploy" / "docker" / "compose.metadata-vulkan.yml").read_text(encoding="utf-8")
    check("build:" not in compose, "standalone Compose must not build images")
    check("./" not in compose, "standalone Compose must not bind-mount source paths")
    for image in ("ocr-backend", "ocr-frontend", "ocr-metadata"):
        check(f"ghcr.io/drbearjew/{image}:${{DOKOCR_IMAGE_TAG:-main}}" in compose, f"missing tagged {image} image")
    check("OCR_PROVIDER: ppocrv6" in compose and "PPOCRV6_TIER: medium" in compose, "default must use real PP-OCRv6 medium")
    check("LLM_METADATA_REFINEMENT_ENABLED: ${DOKOCR_METADATA_ENABLED:-false}" in compose, "metadata refinement must be opt-in")
    check("profiles: [metadata]" in compose, "metadata image must stay behind the metadata profile")
    check("QWEN_LLAMACPP_BASE_URL: ${DOKOCR_METADATA_URL:-http://metadata:8080/v1}" in compose, "metadata URL must default to internal service DNS")
    check("QWEN_MODEL_PATH: ${DOKOCR_METADATA_MODEL:-metadata}" in compose, "metadata model alias must be configurable")
    check("DOKOCR_METADATA_COMPUTE: cpu" in compose, "base metadata image must select CPU compute")
    check("http://127.0.0.1:8080/health" in compose, "metadata readiness must use its model-loaded health endpoint")
    check("http://127.0.0.1:8000/ready" in compose, "backend health must use API readiness")
    check("service_completed_successfully" in compose, "API/workers must wait for successful migration")
    check("condition: service_healthy" in compose, "database/API dependencies must be health-gated")
    check("metadata-models:/models" in compose, "base metadata service must use persistent named model storage")
    check("ghcr.io/drbearjew/ocr-metadata-cuda:${DOKOCR_IMAGE_TAG:-main}" in cuda and "DOKOCR_METADATA_COMPUTE: cuda" in cuda, "CUDA override image or compute mode is missing")
    check("driver: nvidia" in cuda and "capabilities: [gpu]" in cuda and "count: all" in cuda, "CUDA override must request every NVIDIA GPU")
    check("ghcr.io/drbearjew/ocr-metadata-vulkan:${DOKOCR_IMAGE_TAG:-main}" in vulkan and "DOKOCR_METADATA_COMPUTE: vulkan" in vulkan, "Vulkan override image or compute mode is missing")
    check("/dev/dri:/dev/dri" in vulkan and "privileged:" not in vulkan, "Vulkan must map /dev/dri without privileged mode")
    check("DOKOCR_METADATA_GPU_LAYERS" in cuda and "DOKOCR_METADATA_DEVICES" in cuda and "DOKOCR_METADATA_GPU_LAYERS" in vulkan and "DOKOCR_METADATA_DEVICES" in vulkan, "GPU tuning variables must pass through for both GPU modes")
    check("host.docker.internal:host-gateway" in compose, "host metadata runtimes need host-gateway mapping")
    check("max-size: 10m" in compose and 'max-file: "3"' in compose, "container logs must be bounded")
    check('"${DOKOCR_BIND:-127.0.0.1}:${DOKOCR_PORT:-3001}:80"' in compose, "frontend must default to loopback binding")
    check('"${DOKOCR_BIND:-127.0.0.1}:${DOKOCR_API_PORT:-8001}:8000"' in compose, "API must default to loopback binding")


def test_optional_real_docker_config() -> str:
    docker = shutil.which("docker")
    if not docker:
        return "Docker Compose config skipped (docker is not installed)"
    version = subprocess.run([docker, "compose", "version", "--short"], text=True, capture_output=True, check=False)
    version_match = re.match(r"^v?([0-9]+)\.", version.stdout.strip())
    if version.returncode or not version_match or int(version_match.group(1)) < 2:
        return "Docker Compose config skipped (Docker Compose v2 or newer is not available)"

    def render(work: Path, overrides: list[Path], profile: bool, settings: dict[str, str]) -> dict:
        env_file = work / ".env"
        values = {
            "COMPOSE_PROJECT_NAME": "dokocr-config-test", "DOKOCR_IMAGE_TAG": "main",
            "DOKOCR_METADATA_ENABLED": "false", "DOKOCR_METADATA_URL": "",
            "DOKOCR_METADATA_MODEL": "", "DOKOCR_BIND": "127.0.0.1",
            "DOKOCR_PORT": "3001", "DOKOCR_API_PORT": "8001",
            "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "a" * 48,
            "SECRET_KEY": "0123456789abcdef" * 4, "POSTGRES_PASSWORD": "b" * 48,
        }
        values.update(settings)
        env_file.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
        args = [docker, "compose", "--project-directory", str(work), "--env-file", str(env_file), "-f", str(COMPOSE)]
        for override in overrides:
            args.extend(["-f", str(override)])
        if profile:
            args.extend(["--profile", "metadata"])
        result = subprocess.run([*args, "config", "--format", "json"], text=True, capture_output=True, check=False)
        check(result.returncode == 0, f"Docker Compose rejected {overrides or ['base']} config:\n{result.stderr}")
        return json.loads(result.stdout)

    with tempfile.TemporaryDirectory(prefix="dokocr-compose-config-") as temporary:
        work = Path(temporary)
        cuda_file = ROOT / "deploy" / "docker" / "compose.metadata-cuda.yml"
        vulkan_file = ROOT / "deploy" / "docker" / "compose.metadata-vulkan.yml"
        default_config = render(work, [], False, {})
        cpu_config = render(work, [], True, {"DOKOCR_METADATA_ENABLED": "true"})
        cuda_config = render(work, [cuda_file], True, {"DOKOCR_METADATA_ENABLED": "true", "DOKOCR_METADATA_GPU_LAYERS": "21", "DOKOCR_METADATA_DEVICES": "CUDA0,CUDA1", "CUDA_VISIBLE_DEVICES": "1,0"})
        vulkan_config = render(work, [vulkan_file], True, {"DOKOCR_METADATA_ENABLED": "true"})
        vulkan_tuned_config = render(work, [vulkan_file], True, {"DOKOCR_METADATA_ENABLED": "true", "DOKOCR_METADATA_GPU_LAYERS": "18", "DOKOCR_METADATA_DEVICES": "Vulkan0", "GGML_VK_VISIBLE_DEVICES": "1"})
        external_url = "http://host.docker.internal:8080/v1"
        external_config = render(work, [], False, {
            "DOKOCR_METADATA_ENABLED": "true", "DOKOCR_METADATA_URL": external_url,
            "DOKOCR_METADATA_MODEL": "served-model",
        })
        check("metadata" not in default_config["services"], "default profile unexpectedly activates local metadata")
        cpu_service = cpu_config["services"]["metadata"]
        check(cpu_service["environment"].get("DOKOCR_METADATA_COMPUTE") == "cpu", "CPU config must retain the CPU compute mode")
        check(cpu_service.get("profiles") == ["metadata"], "local metadata must stay behind the metadata profile")
        check(not cpu_service.get("deploy", {}).get("resources", {}).get("reservations", {}).get("devices"), "CPU config must not request GPU devices")
        cpu_backend_env = cpu_config["services"]["backend"]["environment"]
        check(cpu_backend_env["QWEN_LLAMACPP_BASE_URL"] == "http://metadata:8080/v1" and cpu_backend_env["QWEN_MODEL_PATH"] == "metadata", "internal CPU config must retain the built-in endpoint/model")
        cuda_service = cuda_config["services"]["metadata"]
        check(cuda_service["environment"].get("DOKOCR_METADATA_GPU_LAYERS") == "21" and cuda_service["environment"].get("DOKOCR_METADATA_DEVICES") == "CUDA0,CUDA1", "CUDA tuning values did not pass through")
        for name, service in (("CPU", cpu_service), ("CUDA", cuda_service), ("Vulkan", vulkan_config["services"]["metadata"])):
            check(service["healthcheck"]["test"][:2] == ["CMD", "python3"], f"{name} metadata healthcheck must use the interpreter available in every image")
            check(any(volume.get("source") == "metadata-models" and volume.get("target") == "/models" for volume in service.get("volumes", [])), f"{name} metadata config does not share the named model volume")
        check(cuda_service["environment"].get("DOKOCR_METADATA_COMPUTE") == "cuda" and cuda_service.get("profiles") == ["metadata"], "CUDA config must retain local profile and compute mode")
        check(cuda_service["environment"].get("CUDA_VISIBLE_DEVICES") == "1,0", "CUDA visibility selection did not pass through")
        cuda_devices = cuda_service["deploy"]["resources"]["reservations"]["devices"]
        check(any(device.get("driver") == "nvidia" and "gpu" in device.get("capabilities", []) and device.get("count") in ("all", -1) for device in cuda_devices), "CUDA config lacks all-NVIDIA-GPU reservation")
        vulkan_service = vulkan_config["services"]["metadata"]
        vulkan_tuned_env = vulkan_tuned_config["services"]["metadata"]["environment"]
        check(vulkan_service["environment"].get("DOKOCR_METADATA_GPU_LAYERS") is None and vulkan_service["environment"].get("DOKOCR_METADATA_DEVICES") is None, "unset Vulkan tuning variables must stay unset, not become empty strings")
        check(vulkan_tuned_env.get("DOKOCR_METADATA_GPU_LAYERS") == "18" and vulkan_tuned_env.get("DOKOCR_METADATA_DEVICES") == "Vulkan0", "Vulkan tuning values did not pass through")
        check(vulkan_tuned_env.get("GGML_VK_VISIBLE_DEVICES") == "1", "Vulkan physical GPU selection did not pass through")
        vulkan_devices = vulkan_service.get("devices", [])
        check(any(device.get("source") == "/dev/dri" and device.get("target") == "/dev/dri" for device in vulkan_devices), "Vulkan config lacks the /dev/dri device mapping")
        check(vulkan_service.get("environment", {}).get("DOKOCR_METADATA_COMPUTE") == "vulkan" and not vulkan_service.get("privileged", False), "Vulkan config must use unprivileged Vulkan compute")
        check("metadata" not in external_config["services"], "external config must not activate local metadata service")
        for service in ("backend", "worker"):
            environment = external_config["services"][service]["environment"]
            check(environment["QWEN_LLAMACPP_BASE_URL"] == external_url and environment["QWEN_MODEL_PATH"] == "served-model", f"external metadata settings missing from {service}")
            check("host.docker.internal=host-gateway" in external_config["services"][service].get("extra_hosts", []), f"{service} is missing the host-gateway mapping")
    return "Docker Compose CLI v2+ parsed CPU, CUDA, Vulkan, external, and default configurations; reservations/mounts checked; config only, no hardware or containers"


def main() -> None:
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)
    subprocess.run(["bash", str(INSTALLER), "--help"], check=True, capture_output=True, text=True)
    test_compose_contract()

    with tempfile.TemporaryDirectory(prefix="dokocr-installer-test-") as temporary:
        work = Path(temporary)
        bindir, log = install_mocks(work)
        downloaded = work / "downloaded"
        downloaded.mkdir()
        script = downloaded / "install-docker.sh"
        shutil.copy2(INSTALLER, script)
        install_dir = work / "my install"

        result = run_installer(script, bindir, log, COMPOSE, install_dir)
        check(result.returncode == 0, f"default install failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_IMAGE_TAG"] == "main", "default image tag must be main")
        check(values["DOKOCR_METADATA_ENABLED"] == "false", "metadata must be disabled by default")
        check(values["DOKOCR_METADATA_RUNTIME"] == "cpu" and values["COMPOSE_FILE"] == "compose.yml", "default runtime and Compose file selection are incorrect")
        check(values["DOKOCR_METADATA_URL"] == "" and values["DOKOCR_METADATA_MODEL"] == "", "default effective metadata endpoint must remain internal")
        check(values["DOKOCR_BIND"] == "127.0.0.1" and values["DOKOCR_PORT"] == "3001" and values["DOKOCR_API_PORT"] == "8001", "default ports/bind are incorrect")
        check(values["COMPOSE_PROJECT_NAME"] == "dokocr", "default Compose project must be isolated as dokocr")
        check(len(values["ADMIN_PASSWORD"]) >= 32 and len(set(values["SECRET_KEY"])) >= 12, "generated credentials do not meet production requirements")
        check(len({values["ADMIN_PASSWORD"], values["SECRET_KEY"], values["POSTGRES_PASSWORD"]}) == 3, "generated credentials must be distinct")
        check((install_dir / ".env").stat().st_mode & 0o777 == 0o600, ".env permissions must be 0600")
        check(install_dir.stat().st_mode & 0o777 == 0o700, "install directory permissions must be 0700")
        check((install_dir / ".dokocr-install").read_text(encoding="utf-8").strip() == "dokocr-docker-installer-v1", "install marker is missing")
        check(all(secret not in result.stdout + result.stderr for secret in (values["ADMIN_PASSWORD"], values["SECRET_KEY"], values["POSTGRES_PASSWORD"])), "installer printed a secret")
        events = read_calls(log)
        urls = [event[-1] for event in events if event[0] == "curl" and event[-1].startswith("https://")]
        check(urls == ["https://raw.githubusercontent.com/DrBearJew/OCR/main/deploy/docker/compose.yml"], "download must use only the fixed trusted raw repository URL")
        docker_args = [event[1:] for event in events if event[0] == "docker"]
        compose_actions = [next((arg for arg in args if arg in {"config", "pull", "up", "ps"}), "") for args in docker_args if args and args[0] == "compose"]
        check(compose_actions.index("config") < compose_actions.index("pull") < compose_actions.index("up"), "installer must validate config, pull, then start")
        default_pull = next(args for args in docker_args if args and args[0] == "compose" and "pull" in args)
        default_up = next(args for args in docker_args if args and args[0] == "compose" and "up" in args)
        check("--profile" not in default_pull and "--profile" not in default_up, "default install must not pull or start the optional metadata service")
        check(not any("down" in args for args in docker_args), "installer must never stop/remove persistent data")

        # Existing installer settings and credentials survive a no-argument rerun;
        # .env values are parsed as data and never executed as shell code.
        before_credentials = {key: values[key] for key in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "SECRET_KEY", "POSTGRES_PASSWORD")}
        sentinel = work / "env-was-sourced"
        with (install_dir / ".env").open("a", encoding="utf-8") as stream:
            stream.write(f"CUSTOM_SETTING=preserved\nCOOKIE_SECURE=true\nFRONTEND_ORIGIN=https://ocr.example.test\nEVIL=$(touch {sentinel})\n")
        result = run_installer(script, bindir, log, COMPOSE, install_dir)
        check(result.returncode == 0, f"idempotent rerun failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check({key: values[key] for key in before_credentials} == before_credentials, "credentials changed on rerun")
        check(values["CUSTOM_SETTING"] == "preserved", "unmanaged settings were not preserved")
        check(values["COOKIE_SECURE"] == "true" and values["FRONTEND_ORIGIN"] == "https://ocr.example.test", "HTTPS settings changed on rerun")
        check(not sentinel.exists(), ".env content was executed")

        result = run_installer(
            script, bindir, log, COMPOSE, install_dir,
            ["--metadata", "--image-tag", "release-1", "--bind", "192.168.4.20", "--port", "8080", "--api-port", "8081"],
        )
        check(result.returncode == 0, f"metadata install failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        expected_options = {
            "DOKOCR_METADATA_ENABLED": "true", "DOKOCR_METADATA_RUNTIME": "cpu",
            "DOKOCR_IMAGE_TAG": "release-1", "COMPOSE_FILE": "compose.yml",
            "DOKOCR_BIND": "192.168.4.20", "DOKOCR_PORT": "8080", "DOKOCR_API_PORT": "8081",
            "COMPOSE_PROJECT_NAME": "dokocr", "COMPOSE_PROFILES": "metadata",
        }
        for key, value in expected_options.items():
            check(values[key] == value, f"explicit setting {key} was not stored")
        check({key: values[key] for key in before_credentials} == before_credentials, "metadata option change rotated credentials")
        events = read_calls(log)
        profile_calls = [event[1:] for event in events if event[0] == "docker" and event[1] == "compose" and "version" not in event]
        check(profile_calls and all("--profile" in args and "metadata" in args for args in profile_calls), f"metadata profile was not enabled for all Compose operations: {profile_calls!r}")
        check(any(event[:2] == ["docker", "inspect"] for event in events), "metadata health was not checked")
        check(any(event[-1] == "https://raw.githubusercontent.com/DrBearJew/OCR/release-1/deploy/docker/compose.yml" for event in events if event[0] == "curl"), "selected trusted ref was not used for Compose download")

        result = run_installer(script, bindir, log, COMPOSE, install_dir)
        check(result.returncode == 0, f"metadata-preserving rerun failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check(all(values[key] == value for key, value in expected_options.items()), "rerun did not preserve metadata/tag/network options")
        check({key: values[key] for key in before_credentials} == before_credentials, "metadata rerun changed credentials")

        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--no-metadata", "--image-tag", "main"])
        check(result.returncode == 0, f"explicit metadata disable failed:\n{result.stdout}\n{result.stderr}")
        events = read_calls(log)
        check(any(event[0] == "docker" and event[1] == "stop" for event in events), "disabled metadata service was not stopped")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_METADATA_ENABLED"] == "false" and "COMPOSE_PROFILES" not in values, "explicit metadata disable did not remove the active profile")
        check(values["DOKOCR_METADATA_RUNTIME"] == "cpu" and values["COMPOSE_FILE"] == "compose.yml", "--no-metadata did not retain the selected runtime")
        disabled_compose = [event[1:] for event in events if event[0] == "docker" and event[1] == "compose" and event[2:4] != ["version", "--short"]]
        check(disabled_compose and all("--profile" not in args for args in disabled_compose), "disabled metadata mode must not pass an active profile")
        check(values["DOKOCR_IMAGE_TAG"] == "main", "explicit image tag update was not stored")
        check({key: values[key] for key in before_credentials} == before_credentials, "explicit option update changed credentials")

        # GPU modes stage a trusted same-ref override and retain the shared model volume.
        with (install_dir / ".env").open("a", encoding="utf-8") as stream:
            stream.write("DOKOCR_METADATA_GPU_LAYERS=21\nDOKOCR_METADATA_DEVICES=CUDA0,CUDA1\n")
        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--metadata-runtime", "cuda"])
        check(result.returncode == 0, f"CUDA runtime install failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_METADATA_RUNTIME"] == "cuda" and values["DOKOCR_METADATA_ENABLED"] == "true", "CUDA choice did not enable and persist metadata")
        check(values["COMPOSE_FILE"] == "compose.yml:compose.metadata-cuda.yml" and values["COMPOSE_PROFILES"] == "metadata", "CUDA Compose selection/profile is incorrect")
        check(values["DOKOCR_METADATA_GPU_LAYERS"] == "21" and values["DOKOCR_METADATA_DEVICES"] == "CUDA0,CUDA1", "GPU tuning settings were not preserved")
        check(values["DOKOCR_METADATA_URL"] == "" and values["DOKOCR_METADATA_EXTERNAL_URL"] == "", "local CUDA must not select an external endpoint")
        events = read_calls(log)
        trusted_urls = [event[-1] for event in events if event[0] == "curl" and event[-1].startswith("https://raw.githubusercontent.com/")]
        check(trusted_urls == [
            "https://raw.githubusercontent.com/DrBearJew/OCR/main/deploy/docker/compose.yml",
            "https://raw.githubusercontent.com/DrBearJew/OCR/main/deploy/docker/compose.metadata-cuda.yml",
        ], "CUDA files were not fetched from the same trusted ref")
        cuda_calls = [event[1:] for event in events if event[0] == "docker" and event[1] == "compose" and any(action in event for action in ("config", "pull", "up"))]
        check(cuda_calls and all(args.count("--file") == 2 for args in cuda_calls), "CUDA override was omitted from a Compose operation")
        cuda_start_calls = [args for args in cuda_calls if "pull" in args or "up" in args]
        check(all(any("compose.metadata-cuda.yml" in arg for arg in args) for args in cuda_start_calls), "installed CUDA override was not used for pull/start")
        check(all("--profile" in args and "metadata" in args for args in cuda_calls), "enabled CUDA runtime did not activate only the metadata profile")
        check(any(event[0] == "docker" and event[1] == "inspect" for event in events), "local GPU metadata health was not checked")

        # Saved runtime/file settings beat inherited shell values on rerun.
        inherited = {
            "DOKOCR_METADATA_RUNTIME": "external", "DOKOCR_METADATA_URL": "https://wrong.example/v1",
            "DOKOCR_METADATA_GPU_LAYERS": "99", "COMPOSE_FILE": "compose.yml:wrong.yml",
        }
        result = run_installer(script, bindir, log, COMPOSE, install_dir, extra_env=inherited)
        check(result.returncode == 0, f"CUDA runtime rerun failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_METADATA_RUNTIME"] == "cuda" and values["DOKOCR_METADATA_GPU_LAYERS"] == "21", "inherited shell variables overrode saved installer settings")

        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--metadata"])
        check(result.returncode == 0 and dotenv(install_dir / ".env")["DOKOCR_METADATA_RUNTIME"] == "cuda", "--metadata replaced the saved CUDA runtime")

        # Refusal to fetch or validate a new override leaves all active install files intact.
        before_env = (install_dir / ".env").read_bytes()
        before_compose = (install_dir / "compose.yml").read_bytes()
        before_cuda = (install_dir / "compose.metadata-cuda.yml").read_bytes()
        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--metadata-runtime", "vulkan"], {"MOCK_OVERRIDE_DOWNLOAD_EXIT": "22"})
        check(result.returncode != 0, "failed GPU override download was reported as success")
        check((install_dir / ".env").read_bytes() == before_env and (install_dir / "compose.yml").read_bytes() == before_compose and (install_dir / "compose.metadata-cuda.yml").read_bytes() == before_cuda, "failed override download replaced existing config")
        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--metadata-runtime", "vulkan"], {"MOCK_CONFIG_EXIT": "1"})
        check(result.returncode != 0, "invalid composed override was reported as success")
        check((install_dir / ".env").read_bytes() == before_env and (install_dir / "compose.yml").read_bytes() == before_compose and (install_dir / "compose.metadata-cuda.yml").read_bytes() == before_cuda, "Compose config failure replaced existing files")

        # Both managed GPU override paths reject symlinks before Docker or network actions.
        vulkan_path = install_dir / "compose.metadata-vulkan.yml"
        vulkan_path.symlink_to(install_dir / "compose.yml")
        result = run_installer(script, bindir, log, COMPOSE, install_dir)
        check(result.returncode != 0 and "symbolic link" in result.stderr, "managed override symlink was accepted")
        check(not read_calls(log), "managed override symlink refusal contacted Docker or network")
        vulkan_path.unlink()

        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--metadata-runtime", "vulkan"])
        check(result.returncode == 0, f"Vulkan runtime install failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_METADATA_RUNTIME"] == "vulkan" and values["COMPOSE_FILE"] == "compose.yml:compose.metadata-vulkan.yml", "Vulkan Compose selection is incorrect")
        events = read_calls(log)
        vulkan_urls = [event[-1] for event in events if event[0] == "curl" and event[-1].startswith("https://raw.githubusercontent.com/")]
        check(vulkan_urls == [
            "https://raw.githubusercontent.com/DrBearJew/OCR/main/deploy/docker/compose.yml",
            "https://raw.githubusercontent.com/DrBearJew/OCR/main/deploy/docker/compose.metadata-vulkan.yml",
        ], "Vulkan files were not fetched from the same trusted ref")

        # Switching from a local GPU runtime to external stops, but never pulls, local metadata.
        external_url = "http://host.docker.internal:8080/v1"
        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--metadata-runtime", "external", "--metadata-url", external_url])
        check(result.returncode == 0, f"external runtime install failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_METADATA_RUNTIME"] == "external" and values["DOKOCR_METADATA_ENABLED"] == "true", "external runtime did not enable metadata")
        check(values["DOKOCR_METADATA_URL"] == external_url and values["DOKOCR_METADATA_MODEL"] == "metadata", "external endpoint/default model were not saved")
        check(values["DOKOCR_METADATA_EXTERNAL_URL"] == external_url and values["COMPOSE_FILE"] == "compose.yml", "external transition lost its endpoint or retained a local GPU override")
        check("COMPOSE_PROFILES" not in values, "external mode must not enable the local metadata profile")
        events = read_calls(log)
        external_compose = [event[1:] for event in events if event[0] == "docker" and event[1] == "compose" and event[2:4] != ["version", "--short"]]
        check(external_compose and all("--profile" not in args for args in external_compose), "external mode passed a local metadata profile to Compose")
        check(all("compose.metadata-" not in " ".join(args) for args in external_compose), "external mode retained a local GPU override")
        check(any(event[0] == "docker" and event[1] == "stop" for event in events), "switching to external did not stop the active internal metadata container")
        check(not any(event[0] == "curl" and event[-1] == external_url for event in events), "installer test sent a request to the external metadata endpoint")

        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--metadata-model", "org/served-model"])
        check(result.returncode == 0, f"saved external model update failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_METADATA_MODEL"] == "org/served-model", "external model alias was not persisted")
        result = run_installer(script, bindir, log, COMPOSE, install_dir)
        check(result.returncode == 0, f"external runtime rerun failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_METADATA_RUNTIME"] == "external" and values["DOKOCR_METADATA_URL"] == external_url and values["DOKOCR_METADATA_MODEL"] == "org/served-model", "external selection was not preserved on rerun")

        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--no-metadata"])
        check(result.returncode == 0, f"external metadata disable failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_METADATA_ENABLED"] == "false" and values["DOKOCR_METADATA_RUNTIME"] == "external", "--no-metadata did not retain the selected runtime")
        check(values["DOKOCR_METADATA_URL"] == external_url and values["DOKOCR_METADATA_MODEL"] == "org/served-model" and "COMPOSE_PROFILES" not in values, "--no-metadata lost the external endpoint/model or enabled a local profile")
        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--metadata"])
        check(result.returncode == 0, f"saved external runtime re-enable failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_METADATA_ENABLED"] == "true" and values["DOKOCR_METADATA_URL"] == external_url, "saved external configuration could not be re-enabled")

        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--metadata-runtime", "cpu"])
        check(result.returncode == 0, f"explicit return to CPU metadata failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_METADATA_RUNTIME"] == "cpu" and values["DOKOCR_METADATA_URL"] == "" and values["DOKOCR_METADATA_MODEL"] == "", "internal runtime did not reset effective endpoint/model")
        check(values["DOKOCR_METADATA_EXTERNAL_URL"] == external_url and values["DOKOCR_METADATA_EXTERNAL_MODEL"] == "org/served-model", "switching internal lost the saved external selection")
        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--metadata-runtime", "external"])
        check(result.returncode == 0, f"external endpoint restore failed:\n{result.stdout}\n{result.stderr}")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_METADATA_URL"] == external_url and values["DOKOCR_METADATA_MODEL"] == "org/served-model", "saved external endpoint/model were not restored")
        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--no-metadata"])
        check(result.returncode == 0, f"final metadata disable failed:\n{result.stdout}\n{result.stderr}")

        named_install = work / "named-install"
        result = run_installer(
            script, bindir, log, COMPOSE, named_install, ["--project-name", "dokocr-lab"],
            {"MOCK_COMPOSE_VERSION": "5.1.3"},
        )
        check(result.returncode == 0 and dotenv(named_install / ".env")["COMPOSE_PROJECT_NAME"] == "dokocr-lab", "project name was not configurable for a new install or a newer Compose CLI was rejected")

        # Changing the project name would point at a different named-volume set.
        previous_env = (install_dir / ".env").read_bytes()
        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--project-name", "dokocr-renamed"])
        check(result.returncode != 0, "unsafe project-name change was accepted")
        project_refusal_calls = read_calls(log)
        check((install_dir / ".env").read_bytes() == previous_env, "project-name refusal changed install state")
        check(not any(event[0] == "curl" or (event[0] == "docker" and event[1] == "compose" and "config" in event) for event in project_refusal_calls), "project-name refusal downloaded or reconfigured the install")

        # A second directory cannot adopt an existing project's retained volumes.
        result = run_installer(script, bindir, log, COMPOSE, work / "other-install", extra_env={"MOCK_PROJECT_VOLUME": "dokocr_postgres-data"})
        check(result.returncode != 0 and "already exists" in result.stderr, "new directory adopted another install's project data")
        check(not (work / "other-install" / ".env").exists(), "project collision wrote new credentials")
        previous_env = (install_dir / ".env").read_bytes()
        result = run_installer(script, bindir, log, COMPOSE, install_dir, extra_env={"MOCK_PROJECT_CONTAINER": "foreign-container"})
        check(result.returncode != 0 and "another install directory" in result.stderr, "foreign project container was adopted")
        check((install_dir / ".env").read_bytes() == previous_env, "foreign project refusal changed credentials")

        # Invalid/unowned targets and refs fail before Docker or network actions.
        unowned = work / "unowned"
        unowned.mkdir()
        sentinel_file = unowned / "keep.txt"
        sentinel_file.write_text("do not replace", encoding="utf-8")
        result = run_installer(script, bindir, log, COMPOSE, unowned)
        check(result.returncode != 0 and sentinel_file.read_text(encoding="utf-8") == "do not replace", "unowned directory was overwritten")
        check(not read_calls(log), "unowned-directory refusal contacted Docker or network")

        result = run_installer(script, bindir, log, COMPOSE, work / "invalid-tag", ["--image-tag", "main;touch-pwned"])
        check(result.returncode != 0, "shell-like image tag was accepted")
        check(not read_calls(log), "invalid image tag contacted Docker or network")
        result = run_installer(script, bindir, log, COMPOSE, work / "invalid-port", ["--port", "70000"])
        check(result.returncode != 0 and not read_calls(log), "out-of-range port was accepted or contacted Docker")
        for name, args in (
            ("invalid-runtime", ["--metadata-runtime", "gpu"]),
            ("runtime-disable-conflict", ["--metadata-runtime", "cuda", "--no-metadata"]),
            ("reverse-disable-conflict", ["--no-metadata", "--metadata-runtime", "vulkan"]),
        ):
            result = run_installer(script, bindir, log, COMPOSE, work / name, args)
            check(result.returncode != 0 and not read_calls(log), f"invalid metadata choice was accepted or contacted Docker: {name}")
        for index, args in enumerate((["--metadata", "--metadata-runtime", "vulkan"], ["--metadata-runtime", "vulkan", "--metadata"])):
            combined = work / f"combined-metadata-{index}"
            result = run_installer(script, bindir, log, COMPOSE, combined, args)
            check(result.returncode == 0 and dotenv(combined / ".env")["DOKOCR_METADATA_RUNTIME"] == "vulkan", "metadata enable and runtime selection must combine in either order")
        for index, url in enumerate((
            "ftp://metadata.example/v1", "https://user:pass@metadata.example/v1",
            "https://metadata.example/v1?token=x", "https://metadata.example/v1#fragment",
            "http://metadata.example:65536/v1", "http://metadata.example/$(touch-pwned)",
            "http://metadata.example/a b", "http://metadata.example/v1\nnext",
        )):
            result = run_installer(script, bindir, log, COMPOSE, work / f"invalid-url-{index}", ["--metadata-runtime", "external", "--metadata-url", url])
            check(result.returncode != 0 and not read_calls(log), f"unsafe metadata URL was accepted or contacted Docker: {url!r}")
        result = run_installer(script, bindir, log, COMPOSE, work / "invalid-model", ["--metadata-runtime", "external", "--metadata-url", "http://metadata.example/v1", "--metadata-model", "bad model"])
        check(result.returncode != 0 and not read_calls(log), "unsafe metadata model alias was accepted or contacted Docker")
        ipv6_install = work / "ipv6-url"
        result = run_installer(script, bindir, log, COMPOSE, ipv6_install, ["--metadata-runtime", "external", "--metadata-url", "http://[2001:db8::1]:8080/v1"])
        check(result.returncode == 0 and dotenv(ipv6_install / ".env")["DOKOCR_METADATA_URL"] == "http://[2001:db8::1]:8080/v1", "valid IPv6 metadata URL was rejected")
        check(not any(event[0] == "curl" and event[-1] == "http://[2001:db8::1]:8080/v1" for event in read_calls(log)), "IPv6 metadata test sent an endpoint request")
        result = run_installer(script, bindir, log, COMPOSE, work / "url-without-external", ["--metadata-url", "http://metadata.example/v1"])
        check(result.returncode != 0 and not any(event[0] == "curl" or (event[0] == "docker" and event[1] == "compose" and "config" in event) for event in read_calls(log)), "metadata URL without external runtime was accepted or downloaded config")
        result = run_installer(script, bindir, log, COMPOSE, work / "external-without-url", ["--metadata-runtime", "external"])
        check(result.returncode != 0 and "requires a server URL" in result.stderr and not any(event[0] == "curl" or (event[0] == "docker" and event[1] == "compose" and "config" in event) for event in read_calls(log)), "external runtime without a URL was accepted")

        unsafe_dotenv = work / "unsafe-dotenv"
        result = run_installer(script, bindir, log, COMPOSE, unsafe_dotenv)
        check(result.returncode == 0, f"unsafe-dotenv test setup failed:\n{result.stderr}")
        env_path = unsafe_dotenv / ".env"
        sentinel = work / "dotenv-was-sourced"
        unsafe_value = f"DOKOCR_METADATA_URL=$(touch {sentinel})"
        env_path.write_text(env_path.read_text(encoding="utf-8").replace("DOKOCR_METADATA_URL=\n", unsafe_value + "\n"), encoding="utf-8")
        saved_unsafe_env = env_path.read_bytes()
        result = run_installer(script, bindir, log, COMPOSE, unsafe_dotenv)
        check(result.returncode != 0 and "Metadata URL" in result.stderr, "unsafe .env metadata URL was accepted")
        check(env_path.read_bytes() == saved_unsafe_env and not sentinel.exists(), "unsafe .env value was executed or rewritten")
        check(not any(event[0] == "curl" or (event[0] == "docker" and event[1] == "compose" and "config" in event) for event in read_calls(log)), "unsafe .env metadata URL reached Compose or network")

        unsafe_gpu = work / "unsafe-gpu-env"
        result = run_installer(script, bindir, log, COMPOSE, unsafe_gpu)
        check(result.returncode == 0, f"unsafe-GPU test setup failed:\n{result.stderr}")
        with (unsafe_gpu / ".env").open("a", encoding="utf-8") as stream:
            stream.write("DOKOCR_METADATA_GPU_LAYERS=2147483648\n")
        result = run_installer(script, bindir, log, COMPOSE, unsafe_gpu)
        check(result.returncode != 0 and "integer from 0 to 2147483647" in result.stderr, "out-of-range GPU layer value was accepted")
        check(not any(event[0] == "curl" or (event[0] == "docker" and event[1] == "compose" and "config" in event) for event in read_calls(log)), "invalid GPU tuning value reached Compose or network")

        saved_env = (install_dir / ".env").read_bytes()
        saved_compose = (install_dir / "compose.yml").read_bytes()
        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--image-tag", "missing-ref"], {"MOCK_DOWNLOAD_EXIT": "22"})
        check(result.returncode != 0, "failed Compose download was reported as success")
        check((install_dir / ".env").read_bytes() == saved_env and (install_dir / "compose.yml").read_bytes() == saved_compose, "failed download corrupted existing install files")

        result = run_installer(script, bindir, log, COMPOSE, install_dir, ["--image-tag", "not-published"], {"MOCK_PULL_EXIT": "1"})
        check(result.returncode != 0, "failed image pull was reported as success")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_IMAGE_TAG"] == "not-published", "failed pull did not retain the selected tag for retry")
        check({key: values[key] for key in before_credentials} == before_credentials, "failed pull corrupted credentials")
        check(not any("down" in args for args in [event[1:] for event in read_calls(log) if event[0] == "docker"]), "failed pull triggered destructive cleanup")

        result = run_installer(
            script, bindir, log, COMPOSE, install_dir, ["--port", "3010"],
            {"MOCK_UP_EXIT": "1", "MOCK_UP_ERROR": "port is already allocated"},
        )
        check(result.returncode != 0 and "port is already allocated" in result.stderr, "occupied-port start failure was not reported clearly")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_PORT"] == "3010", "failed start did not retain the selected port for retry")
        check({key: values[key] for key in before_credentials} == before_credentials, "occupied-port failure corrupted credentials")
        check(not any("down" in args for args in [event[1:] for event in read_calls(log) if event[0] == "docker"]), "occupied-port failure triggered destructive cleanup")

    config_result = test_optional_real_docker_config()
    print("Docker installer safety, idempotency, OCR, metadata opt-in, and failure-preservation checks passed")
    print(config_result)


if __name__ == "__main__":
    main()
