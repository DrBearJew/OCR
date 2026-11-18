#!/usr/bin/env bash
# llama-swap invokes this on demand; it must stay attached to the container.
set -Eeuo pipefail
[[ $# == 3 && $1 =~ ^[0-9]{1,5}$ ]] || { echo 'usage: launch.sh PORT IMAGE ASSET_DIRECTORY' >&2; exit 2; }
port=$1 image=$2 assets=$3
mounts=()
for asset in paddleocr-vl-q8_0.gguf paddleocr-vl-mmproj.gguf paddleocr-vl-chat_template.jinja; do
    [[ -r "$assets/$asset" ]] || { echo "Missing asset: $asset" >&2; exit 1; }
    mounts+=(--mount "type=bind,src=$assets/$asset,dst=/models/$asset,readonly")
done
exec docker run --rm --init --name dokocr-paddle-ik --network host --read-only \
    --cap-drop ALL --security-opt=no-new-privileges \
    "${mounts[@]}" "$image" "$port"
