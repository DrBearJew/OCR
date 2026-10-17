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
    if int(os.environ.get("MOCK_DOWNLOAD_EXIT", "0")):
        raise SystemExit(int(os.environ["MOCK_DOWNLOAD_EXIT"]))
    output = args[args.index("--output") + 1]
    with open(output, "w", encoding="utf-8") as stream:
        stream.write(open(os.environ["MOCK_COMPOSE_SOURCE"], encoding="utf-8").read())
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
        "MOCK_OPENSSL_COUNT": str(log.parent / "openssl-count"),
        "MOCK_DOCKER_STATE": str(log.parent / "docker-state"),
    })
    for name in (
        "COMPOSE_FILE", "COMPOSE_PROFILES", "COMPOSE_PROJECT_NAME", "COMPOSE_ENV_FILES",
        "COMPOSE_PATH_SEPARATOR", "COMPOSE_DISABLE_ENV_FILE", "DOKOCR_IMAGE_TAG",
        "DOKOCR_METADATA_ENABLED", "DOKOCR_BIND", "DOKOCR_PORT", "DOKOCR_API_PORT",
        "ADMIN_USERNAME", "ADMIN_PASSWORD", "SECRET_KEY", "POSTGRES_PASSWORD",
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
    check("build:" not in compose, "standalone Compose must not build images")
    check("./" not in compose, "standalone Compose must not bind-mount source paths")
    for image in ("ocr-backend", "ocr-frontend", "ocr-metadata"):
        check(f"ghcr.io/drbearjew/{image}:${{DOKOCR_IMAGE_TAG:-main}}" in compose, f"missing tagged {image} image")
    check("OCR_PROVIDER: ppocrv6" in compose and "PPOCRV6_TIER: medium" in compose, "default must use real PP-OCRv6 medium")
    check("LLM_METADATA_REFINEMENT_ENABLED: ${DOKOCR_METADATA_ENABLED:-false}" in compose, "metadata refinement must be opt-in")
    check("profiles: [metadata]" in compose, "metadata image must stay behind the metadata profile")
    check("QWEN_LLAMACPP_BASE_URL: http://metadata:8080/v1" in compose, "metadata URL must use internal service DNS")
    check("http://127.0.0.1:8080/health" in compose, "metadata readiness must use its model-loaded health endpoint")
    check("http://127.0.0.1:8000/ready" in compose, "backend health must use API readiness")
    check("service_completed_successfully" in compose, "API/workers must wait for successful migration")
    check("condition: service_healthy" in compose, "database/API dependencies must be health-gated")
    check("metadata-models:/models" in compose, "metadata models must use persistent named storage")
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
    with tempfile.TemporaryDirectory(prefix="dokocr-compose-config-") as temporary:
        work = Path(temporary)
        env_file = work / ".env"
        env_file.write_text(
            "COMPOSE_PROJECT_NAME=dokocr-config-test\n"
            "DOKOCR_IMAGE_TAG=main\nDOKOCR_METADATA_ENABLED=false\n"
            "DOKOCR_BIND=127.0.0.1\nDOKOCR_PORT=3001\nDOKOCR_API_PORT=8001\n"
            "ADMIN_USERNAME=admin\nADMIN_PASSWORD=" + "a" * 48 + "\n"
            "SECRET_KEY=" + "0123456789abcdef" * 4 + "\n"
            "POSTGRES_PASSWORD=" + "b" * 48 + "\n",
            encoding="utf-8",
        )
        base = [docker, "compose", "--project-directory", str(work), "--env-file", str(env_file), "-f", str(COMPOSE)]
        environment = os.environ.copy()
        for name in (
            "COMPOSE_FILE", "COMPOSE_PROFILES", "COMPOSE_PROJECT_NAME", "COMPOSE_ENV_FILES",
            "COMPOSE_PATH_SEPARATOR", "COMPOSE_DISABLE_ENV_FILE", "DOKOCR_IMAGE_TAG",
            "DOKOCR_METADATA_ENABLED", "DOKOCR_BIND", "DOKOCR_PORT", "DOKOCR_API_PORT",
            "ADMIN_USERNAME", "ADMIN_PASSWORD", "SECRET_KEY", "POSTGRES_PASSWORD",
        ):
            environment.pop(name, None)
        subprocess.run([*base, "config", "--quiet"], env=environment, check=True, capture_output=True, text=True)
        subprocess.run([*base, "--profile", "metadata", "config", "--quiet"], env=environment, check=True, capture_output=True, text=True)
    return "Docker Compose CLI v2+ parsed default and metadata-profile configurations (config only; no containers started)"


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
            "DOKOCR_METADATA_ENABLED": "true", "DOKOCR_IMAGE_TAG": "release-1",
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
        check(any(event[0] == "docker" and "stop" in event and "metadata" in event for event in events), "disabled metadata service was not stopped")
        values = dotenv(install_dir / ".env")
        check(values["DOKOCR_METADATA_ENABLED"] == "false" and "COMPOSE_PROFILES" not in values, "explicit metadata disable did not remove the active profile")
        check(values["DOKOCR_IMAGE_TAG"] == "main", "explicit image tag update was not stored")
        check({key: values[key] for key in before_credentials} == before_credentials, "explicit option update changed credentials")

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
