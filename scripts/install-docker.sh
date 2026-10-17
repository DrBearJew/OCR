#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

INSTALL_DIR_INPUT="$PWD/dokocr"
IMAGE_TAG_ARG=""
BIND_ARG=""
PORT_ARG=""
API_PORT_ARG=""
PROJECT_ARG=""
METADATA_ARG=""
DIRECTORY_ARG_SET=false

usage() {
  cat <<'USAGE'
Install Dok OCR from published Docker images.

Usage: bash install-docker.sh [options]

Options:
  --directory DIR    Install files here (default: ./dokocr)
  --metadata         Enable optional LFM2.5 metadata refinement (large model download)
  --no-metadata      Disable optional metadata refinement on an existing install
  --image-tag TAG    Use this trusted repository ref/image tag (default: main)
  --bind IPv4        Host address for the web/API ports (default: 127.0.0.1)
  --port PORT        Frontend host port (default: 3001)
  --api-port PORT    Backend API host port (default: 8001)
  --project-name NAME Compose project name (default: dokocr)
  -h, --help         Show this help

The installer requires Docker Engine, Docker Compose v2, curl, OpenSSL, and an
x86_64 host. It does not install system packages or use sudo.
USAGE
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

while (($#)); do
  case "$1" in
    --directory)
      (($# >= 2)) || fail "--directory requires a value"
      [[ -n "$2" ]] || fail "--directory cannot be empty"
      [[ "$DIRECTORY_ARG_SET" == false ]] || fail "--directory may be specified only once"
      INSTALL_DIR_INPUT=$2
      DIRECTORY_ARG_SET=true
      shift 2
      ;;
    --metadata)
      [[ -z "$METADATA_ARG" || "$METADATA_ARG" == true ]] || fail "--metadata and --no-metadata cannot be combined"
      METADATA_ARG=true
      shift
      ;;
    --no-metadata)
      [[ -z "$METADATA_ARG" || "$METADATA_ARG" == false ]] || fail "--metadata and --no-metadata cannot be combined"
      METADATA_ARG=false
      shift
      ;;
    --image-tag)
      (($# >= 2)) || fail "--image-tag requires a value"
      [[ -n "$2" ]] || fail "--image-tag cannot be empty"
      [[ -z "$IMAGE_TAG_ARG" ]] || fail "--image-tag may be specified only once"
      IMAGE_TAG_ARG=$2
      shift 2
      ;;
    --bind)
      (($# >= 2)) || fail "--bind requires a value"
      [[ -n "$2" ]] || fail "--bind cannot be empty"
      [[ -z "$BIND_ARG" ]] || fail "--bind may be specified only once"
      BIND_ARG=$2
      shift 2
      ;;
    --port)
      (($# >= 2)) || fail "--port requires a value"
      [[ -n "$2" ]] || fail "--port cannot be empty"
      [[ -z "$PORT_ARG" ]] || fail "--port may be specified only once"
      PORT_ARG=$2
      shift 2
      ;;
    --api-port)
      (($# >= 2)) || fail "--api-port requires a value"
      [[ -n "$2" ]] || fail "--api-port cannot be empty"
      [[ -z "$API_PORT_ARG" ]] || fail "--api-port may be specified only once"
      API_PORT_ARG=$2
      shift 2
      ;;
    --project-name)
      (($# >= 2)) || fail "--project-name requires a value"
      [[ -n "$2" ]] || fail "--project-name cannot be empty"
      [[ -z "$PROJECT_ARG" ]] || fail "--project-name may be specified only once"
      PROJECT_ARG=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      (($# == 0)) || fail "Unexpected positional arguments: $*"
      ;;
    *)
      fail "Unknown option: $1 (use --help for usage)"
      ;;
  esac
done

validate_image_tag() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] || fail "Invalid image tag/ref: use 1-128 letters, digits, dots, underscores, or hyphens; it must start with a letter or digit"
}

validate_bind() {
  local value=$1 part
  local -a octets
  [[ "$value" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || fail "--bind must be an IPv4 address (use 0.0.0.0 only when you intend LAN exposure)"
  IFS=. read -r -a octets <<< "$value"
  for part in "${octets[@]}"; do
    [[ "$part" =~ ^(0|[1-9][0-9]{0,2})$ ]] || fail "Invalid IPv4 address: $value"
    ((10#$part <= 255)) || fail "Invalid IPv4 address: $value"
  done
}

validate_port() {
  local value=$1 label=$2 number
  [[ "$value" =~ ^[0-9]{1,5}$ ]] || fail "$label must be a decimal port from 1 to 65535"
  number=$((10#$value))
  ((number >= 1 && number <= 65535)) || fail "$label must be a decimal port from 1 to 65535"
  printf '%s' "$number"
}

validate_project() {
  [[ "$1" =~ ^[a-z0-9][a-z0-9_-]{0,62}$ ]] || fail "Project name must start with a lowercase letter or digit and contain only lowercase letters, digits, '_' or '-' (max 63 characters)"
}

if [[ -n "$IMAGE_TAG_ARG" ]]; then validate_image_tag "$IMAGE_TAG_ARG"; fi
if [[ -n "$BIND_ARG" ]]; then validate_bind "$BIND_ARG"; fi
if [[ -n "$PORT_ARG" ]]; then PORT_ARG=$(validate_port "$PORT_ARG" "--port"); fi
if [[ -n "$API_PORT_ARG" ]]; then API_PORT_ARG=$(validate_port "$API_PORT_ARG" "--api-port"); fi
if [[ -n "$PROJECT_ARG" ]]; then validate_project "$PROJECT_ARG"; fi

# Refuse to adopt or overwrite a directory unless it is empty or carries our marker.
INSTALL_DIR_INPUT=${INSTALL_DIR_INPUT%/}
[[ -n "$INSTALL_DIR_INPUT" ]] || INSTALL_DIR_INPUT=/
if [[ -L "$INSTALL_DIR_INPUT" ]]; then fail "Install directory must not be a symbolic link: $INSTALL_DIR_INPUT"; fi
if [[ -e "$INSTALL_DIR_INPUT" && ! -d "$INSTALL_DIR_INPUT" ]]; then fail "Install path is not a directory: $INSTALL_DIR_INPUT"; fi

MARKER_NAME=.dokocr-install
MARKER_CONTENT=dokocr-docker-installer-v1
if [[ -d "$INSTALL_DIR_INPUT" ]]; then
  if [[ -L "$INSTALL_DIR_INPUT/$MARKER_NAME" ]]; then fail "Install marker must not be a symbolic link"; fi
  if [[ -e "$INSTALL_DIR_INPUT/$MARKER_NAME" ]]; then
    [[ -f "$INSTALL_DIR_INPUT/$MARKER_NAME" ]] || fail "Invalid install marker: $INSTALL_DIR_INPUT/$MARKER_NAME"
    marker_value=$(<"$INSTALL_DIR_INPUT/$MARKER_NAME")
    [[ "$marker_value" == "$MARKER_CONTENT" ]] || fail "Unrecognized install marker in $INSTALL_DIR_INPUT"
    for managed_file in .env compose.yml; do
      if [[ -L "$INSTALL_DIR_INPUT/$managed_file" ]]; then fail "Managed install file must not be a symbolic link: $INSTALL_DIR_INPUT/$managed_file"; fi
      if [[ -e "$INSTALL_DIR_INPUT/$managed_file" && ! -f "$INSTALL_DIR_INPUT/$managed_file" ]]; then fail "Managed install path is not a regular file: $INSTALL_DIR_INPUT/$managed_file"; fi
    done
  else
    shopt -s dotglob nullglob
    existing_entries=("$INSTALL_DIR_INPUT"/*)
    shopt -u dotglob nullglob
    ((${#existing_entries[@]} == 0)) || fail "Install directory is not empty and has no Dok OCR installer marker: $INSTALL_DIR_INPUT"
  fi
fi

need_command docker
need_command curl
need_command uname
need_command mktemp
need_command chmod
need_command mv
need_command cp
need_command sleep

host_arch=$(uname -m)
[[ "$host_arch" == x86_64 || "$host_arch" == amd64 ]] || fail "Published images support x86_64/amd64; detected $host_arch"
compose_version=$(docker compose version --short 2>/dev/null) || fail "Docker Compose v2 or newer is required (docker compose version failed)"
compose_major=${compose_version#v}
compose_major=${compose_major%%.*}
if [[ ! "$compose_major" =~ ^[0-9]+$ ]] || ((10#$compose_major < 2)); then
  fail "Docker Compose v2 or newer is required; detected version '$compose_version'"
fi
docker info >/dev/null 2>&1 || fail "Docker Engine is not reachable; start Docker and retry"

if [[ ! -d "$INSTALL_DIR_INPUT" ]]; then mkdir -p -- "$INSTALL_DIR_INPUT"; fi
INSTALL_DIR=$(cd -P -- "$INSTALL_DIR_INPUT" && pwd)
[[ "$INSTALL_DIR" != / ]] || fail "Refusing to install into the filesystem root"
chmod 700 -- "$INSTALL_DIR"
ENV_FILE=$INSTALL_DIR/.env
COMPOSE_YAML_PATH=$INSTALL_DIR/compose.yml
MARKER_FILE=$INSTALL_DIR/$MARKER_NAME

if [[ -e "$ENV_FILE" ]]; then chmod 600 -- "$ENV_FILE"; fi

ENV_VALUE=""
lookup_env_value() {
  local wanted=$1 line count=0
  ENV_VALUE=""
  [[ -f "$ENV_FILE" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      "$wanted="*)
        ENV_VALUE=${line#*=}
        count=$((count + 1))
        ;;
    esac
  done < "$ENV_FILE"
  ((count <= 1)) || fail "Duplicate $wanted entries in $ENV_FILE; resolve them before retrying"
}

lookup_env_value DOKOCR_IMAGE_TAG; SAVED_IMAGE_TAG=$ENV_VALUE
lookup_env_value DOKOCR_METADATA_ENABLED; SAVED_METADATA=$ENV_VALUE
lookup_env_value DOKOCR_BIND; SAVED_BIND=$ENV_VALUE
lookup_env_value DOKOCR_PORT; SAVED_PORT=$ENV_VALUE
lookup_env_value DOKOCR_API_PORT; SAVED_API_PORT=$ENV_VALUE
lookup_env_value COMPOSE_PROJECT_NAME; SAVED_PROJECT=$ENV_VALUE
lookup_env_value ADMIN_USERNAME; SAVED_ADMIN_USERNAME=$ENV_VALUE
lookup_env_value ADMIN_PASSWORD; SAVED_ADMIN_PASSWORD=$ENV_VALUE
lookup_env_value SECRET_KEY; SAVED_SECRET_KEY=$ENV_VALUE
lookup_env_value POSTGRES_PASSWORD; SAVED_POSTGRES_PASSWORD=$ENV_VALUE

if [[ -n "$SAVED_PROJECT" && -n "$PROJECT_ARG" && "$PROJECT_ARG" != "$SAVED_PROJECT" ]]; then
  fail "Changing COMPOSE_PROJECT_NAME would select different named volumes; use another install directory or migrate volumes explicitly"
fi

IMAGE_TAG=${IMAGE_TAG_ARG:-${SAVED_IMAGE_TAG:-main}}
METADATA_ENABLED=${METADATA_ARG:-${SAVED_METADATA:-false}}
BIND=${BIND_ARG:-${SAVED_BIND:-127.0.0.1}}
PORT=${PORT_ARG:-${SAVED_PORT:-3001}}
API_PORT=${API_PORT_ARG:-${SAVED_API_PORT:-8001}}
PROJECT_NAME=${PROJECT_ARG:-${SAVED_PROJECT:-dokocr}}
ADMIN_USERNAME=${SAVED_ADMIN_USERNAME:-admin}
ADMIN_PASSWORD=${SAVED_ADMIN_PASSWORD:-}
SECRET_KEY=${SAVED_SECRET_KEY:-}
POSTGRES_PASSWORD=${SAVED_POSTGRES_PASSWORD:-}

validate_image_tag "$IMAGE_TAG"
[[ "$METADATA_ENABLED" == true || "$METADATA_ENABLED" == false ]] || fail "DOKOCR_METADATA_ENABLED in $ENV_FILE must be true or false"
validate_bind "$BIND"
PORT=$(validate_port "$PORT" "DOKOCR_PORT")
API_PORT=$(validate_port "$API_PORT" "DOKOCR_API_PORT")
[[ "$PORT" != "$API_PORT" ]] || fail "Frontend and API host ports must be different"
validate_project "$PROJECT_NAME"

# A new directory must never take over another install's project-scoped data.
project_containers=$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT_NAME") || fail "Could not inspect existing Docker project"
if [[ ! -f "$MARKER_FILE" ]]; then
  project_volumes=$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT_NAME") || fail "Could not inspect existing Docker volumes"
  project_networks=$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT_NAME") || fail "Could not inspect existing Docker networks"
  [[ -z "$project_containers$project_volumes$project_networks" ]] || fail "Docker project '$PROJECT_NAME' already exists; use its original install directory or choose another --project-name"
fi
for container in $project_containers; do
  working_dir=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$container") || fail "Could not inspect project ownership"
  [[ "$working_dir" == "$INSTALL_DIR" ]] || fail "Docker project '$PROJECT_NAME' belongs to another install directory; no services changed"
done

[[ "$ADMIN_USERNAME" =~ ^[A-Za-z0-9._@-]{1,64}$ ]] || fail "ADMIN_USERNAME in $ENV_FILE must use only letters, digits, '.', '_', '@', or '-' (max 64 characters)"

for secret_name in ADMIN_PASSWORD SECRET_KEY POSTGRES_PASSWORD; do
  secret_value=${!secret_name}
  if [[ -n "$secret_value" ]]; then
    [[ "$secret_value" =~ ^[A-Za-z0-9._~-]{32,128}$ ]] || fail "$secret_name in $ENV_FILE must be 32-128 URL-safe characters"
  fi
done

if [[ -z "$ADMIN_PASSWORD" || -z "$SECRET_KEY" || -z "$POSTGRES_PASSWORD" ]]; then
  need_command openssl
  [[ -n "$ADMIN_PASSWORD" ]] || ADMIN_PASSWORD=$(openssl rand -hex 24) || fail "Could not generate ADMIN_PASSWORD with OpenSSL"
  [[ -n "$SECRET_KEY" ]] || SECRET_KEY=$(openssl rand -hex 32) || fail "Could not generate SECRET_KEY with OpenSSL"
  [[ -n "$POSTGRES_PASSWORD" ]] || POSTGRES_PASSWORD=$(openssl rand -hex 24) || fail "Could not generate POSTGRES_PASSWORD with OpenSSL"
fi

unique_secret_chars=""
for ((secret_index = 0; secret_index < ${#SECRET_KEY}; secret_index++)); do
  secret_char=${SECRET_KEY:secret_index:1}
  [[ "$unique_secret_chars" == *"$secret_char"* ]] || unique_secret_chars+=$secret_char
done
(( ${#SECRET_KEY} >= 32 && ${#unique_secret_chars} >= 12 )) || fail "SECRET_KEY in $ENV_FILE must satisfy the application's production entropy checks"
[[ "$ADMIN_PASSWORD" != "$SECRET_KEY" && "$ADMIN_PASSWORD" != "$POSTGRES_PASSWORD" && "$SECRET_KEY" != "$POSTGRES_PASSWORD" ]] || fail "ADMIN_PASSWORD, SECRET_KEY, and POSTGRES_PASSWORD must be distinct"

SCRIPT_DIR=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
LOCAL_COMPOSE=$SCRIPT_DIR/../deploy/docker/compose.yml
COMPOSE_URL="https://raw.githubusercontent.com/DrBearJew/OCR/${IMAGE_TAG}/deploy/docker/compose.yml"

COMPOSE_TMP=""
ENV_TMP=""
MARKER_TMP=""
cleanup() {
  [[ -z "$COMPOSE_TMP" || ! -e "$COMPOSE_TMP" ]] || rm -f -- "$COMPOSE_TMP"
  [[ -z "$ENV_TMP" || ! -e "$ENV_TMP" ]] || rm -f -- "$ENV_TMP"
  [[ -z "$MARKER_TMP" || ! -e "$MARKER_TMP" ]] || rm -f -- "$MARKER_TMP"
}
trap cleanup EXIT

COMPOSE_TMP=$(mktemp "$INSTALL_DIR/.compose.XXXXXXXX")
ENV_TMP=$(mktemp "$INSTALL_DIR/.env.XXXXXXXX")
chmod 600 -- "$ENV_TMP"
if [[ -f "$LOCAL_COMPOSE" ]]; then
  cp -- "$LOCAL_COMPOSE" "$COMPOSE_TMP" || fail "Could not stage repository Compose file"
else
  curl --fail --silent --show-error --max-time 60 --output "$COMPOSE_TMP" "$COMPOSE_URL" || fail "Could not download Compose file from the trusted repository ref '$IMAGE_TAG'"
fi
[[ -s "$COMPOSE_TMP" ]] || fail "Compose file is empty"

is_managed_env_key() {
  case "$1" in
    COMPOSE_PROJECT_NAME|COMPOSE_PROFILES|DOKOCR_IMAGE_TAG|DOKOCR_METADATA_ENABLED|DOKOCR_BIND|DOKOCR_PORT|DOKOCR_API_PORT|ADMIN_USERNAME|ADMIN_PASSWORD|SECRET_KEY|POSTGRES_PASSWORD)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

if [[ -f "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*= ]]; then
      is_managed_env_key "${BASH_REMATCH[2]}" && continue
    fi
    printf '%s\n' "$line" >> "$ENV_TMP"
  done < "$ENV_FILE"
fi
{
  printf 'COMPOSE_PROJECT_NAME=%s\n' "$PROJECT_NAME"
  if [[ "$METADATA_ENABLED" == true ]]; then printf 'COMPOSE_PROFILES=metadata\n'; fi
  printf 'DOKOCR_IMAGE_TAG=%s\n' "$IMAGE_TAG"
  printf 'DOKOCR_METADATA_ENABLED=%s\n' "$METADATA_ENABLED"
  printf 'DOKOCR_BIND=%s\n' "$BIND"
  printf 'DOKOCR_PORT=%s\n' "$PORT"
  printf 'DOKOCR_API_PORT=%s\n' "$API_PORT"
  printf 'ADMIN_USERNAME=%s\n' "$ADMIN_USERNAME"
  printf 'ADMIN_PASSWORD=%s\n' "$ADMIN_PASSWORD"
  printf 'SECRET_KEY=%s\n' "$SECRET_KEY"
  printf 'POSTGRES_PASSWORD=%s\n' "$POSTGRES_PASSWORD"
} >> "$ENV_TMP"
chmod 600 -- "$ENV_TMP"
chmod 644 -- "$COMPOSE_TMP"

# Compose parses this file as data; the installer never sources it as shell code.
COMPOSE_CONFIG_PATH=$COMPOSE_TMP
ENV_CONFIG_PATH=$ENV_TMP
PROFILE_ARGS=()
if [[ "$METADATA_ENABLED" == true ]]; then PROFILE_ARGS+=(--profile metadata); fi
compose() {
  (
    unset COMPOSE_FILE COMPOSE_PROFILES COMPOSE_PROJECT_NAME COMPOSE_ENV_FILES COMPOSE_PATH_SEPARATOR COMPOSE_DISABLE_ENV_FILE
    unset DOKOCR_IMAGE_TAG DOKOCR_METADATA_ENABLED DOKOCR_BIND DOKOCR_PORT DOKOCR_API_PORT
    unset ADMIN_USERNAME ADMIN_PASSWORD SECRET_KEY POSTGRES_PASSWORD
    unset FRONTEND_ORIGIN PUBLIC_BASE_URL CORS_ORIGINS COOKIE_SECURE
    docker compose \
      --project-directory "$INSTALL_DIR" \
      --env-file "$ENV_CONFIG_PATH" \
      --file "$COMPOSE_CONFIG_PATH" \
      --project-name "$PROJECT_NAME" \
      "${PROFILE_ARGS[@]}" "$@"
  )
}
compose config --quiet || fail "Docker Compose rejected the downloaded configuration; the existing install was not changed"

if [[ ! -e "$MARKER_FILE" ]]; then
  MARKER_TMP=$(mktemp "$INSTALL_DIR/.marker.XXXXXXXX")
  printf '%s\n' "$MARKER_CONTENT" > "$MARKER_TMP"
  chmod 600 -- "$MARKER_TMP"
  mv -- "$MARKER_TMP" "$MARKER_FILE"
  MARKER_TMP=""
fi
mv -f -- "$COMPOSE_TMP" "$COMPOSE_YAML_PATH"
COMPOSE_TMP=""
mv -f -- "$ENV_TMP" "$ENV_FILE"
ENV_TMP=""
COMPOSE_YAML_PATH=$INSTALL_DIR/compose.yml
COMPOSE_CONFIG_PATH=$COMPOSE_YAML_PATH
ENV_CONFIG_PATH=$ENV_FILE
chmod 644 -- "$COMPOSE_YAML_PATH"
chmod 600 -- "$ENV_FILE"

printf 'Pulling the selected Dok OCR images...\n'
compose pull || fail "Image pull failed. Install files and persistent volumes are preserved; fix access or choose a published tag and retry"
if [[ "$METADATA_ENABLED" == false ]]; then
  PROFILE_ARGS=(--profile metadata)
  metadata_id=$(compose ps -q metadata 2>/dev/null || true)
  if [[ -n "$metadata_id" ]]; then
    printf 'Stopping the previously enabled optional metadata service...\n'
    compose stop metadata || fail "Could not stop the optional metadata service; its model volume and install files are preserved"
  fi
  PROFILE_ARGS=()
fi
printf 'Starting Dok OCR...\n'
compose up -d || fail "Docker Compose could not start the installation. Existing credentials and persistent volumes were preserved; resolve the reported issue and retry"

wait_for_url() {
  local label=$1 url=$2 timeout_seconds=$3 deadline
  deadline=$((SECONDS + timeout_seconds))
  printf 'Waiting for %s...\n' "$label"
  while ((SECONDS < deadline)); do
    if curl --connect-timeout 3 --max-time 8 --fail --silent --show-error "$url" >/dev/null 2>&1; then return 0; fi
    sleep 5
  done
  fail "Timed out waiting for $label at $url; services and persistent volumes remain available for retry"
}

READY_HOST=$BIND
[[ "$READY_HOST" != 0.0.0.0 ]] || READY_HOST=127.0.0.1
wait_for_url 'backend API readiness (/ready)' "http://${READY_HOST}:${API_PORT}/ready" 600
wait_for_url 'frontend' "http://${READY_HOST}:${PORT}/" 300

if [[ "$METADATA_ENABLED" == true ]]; then
  printf 'Waiting up to 35 minutes for the optional metadata model to download and become healthy...\n'
  metadata_deadline=$((SECONDS + 2100))
  while ((SECONDS < metadata_deadline)); do
    metadata_id=$(compose ps -q metadata 2>/dev/null || true)
    if [[ -n "$metadata_id" ]]; then
      metadata_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$metadata_id" 2>/dev/null || true)
      [[ "$metadata_health" == healthy ]] && break
    fi
    sleep 5
  done
  [[ "${metadata_health:-}" == healthy ]] || fail "Metadata service did not become healthy at http://metadata:8080/health within 35 minutes; retrying preserves its model volume"
fi

APP_HOST=$BIND
if [[ "$APP_HOST" == 0.0.0.0 ]]; then APP_HOST=localhost; fi
printf '\nDok OCR is ready: http://%s:%s\n' "$APP_HOST" "$PORT"
printf 'Admin username: %s\nCredentials: %s\n' "$ADMIN_USERNAME" "$ENV_FILE"
if [[ "$METADATA_ENABLED" == true ]]; then
  printf 'Optional LFM2.5 metadata refinement is enabled. Its model is stored in the persistent metadata-models volume.\n'
else
  printf 'OCR: real PP-OCRv6 medium CPU mode; optional LFM2.5 metadata download is disabled.\n'
fi
