#!/bin/sh
set -eu
if [ "$#" != 1 ]; then
    echo 'Usage: dokocr-paddle-ik PORT (binds to IPv4 loopback)' >&2
    exit 2
fi
tier=$(/usr/local/bin/dokocr-cpu-tier)
if [ "$1" = --check-cpu ]; then
    echo "Dok OCR unified CPU backend: $tier"
    exit 0
fi
export LD_LIBRARY_PATH="/opt/dokocr/$tier/lib"
export DOKOCR_PADDLE_FP16_ACTIVATIONS=1
template=/opt/dokocr/share/paddleocr-vl-chat_template.jinja
[ -r "$template" ] || template=/models/paddleocr-vl-chat_template.jinja
[ -r "$template" ] || { echo "PaddleOCR chat template is missing" >&2; exit 1; }
exec "/opt/dokocr/$tier/bin/llama-server" --port "$1" --host 127.0.0.1 --webui none --jinja \
    --model /models/paddleocr-vl-q8_0.gguf --mmproj /models/paddleocr-vl-mmproj.gguf \
    --chat-template-file "$template" --alias paddleocr-vl \
    --ctx-size 4096 --parallel 1 --batch-size 1024 --ubatch-size 512 --threads 4 --threads-batch 4 \
    --flash-attn on --cache-type-k f16 --cache-type-v f16 --cache-ram 0 --no-warmup \
    --n-gpu-layers 0 --no-mmproj-offload --no-fused-up-gate --temp 0
