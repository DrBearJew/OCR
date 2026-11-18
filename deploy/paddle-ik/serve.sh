#!/bin/sh
set -eu
if [ "$#" != 1 ]; then
    echo 'Usage: dokocr-paddle-ik PORT (binds to IPv4 loopback)' >&2
    exit 2
fi
# Fail before executing the optimized binary on unsupported hosts.
for flag in avx2 fma f16c avx512f avx512dq avx512cd avx512bw avx512vl avx512vbmi avx512_vnni avx512_bf16; do
    if ! grep -qm1 -w "$flag" /proc/cpuinfo; then
        echo "PaddleOCR ik requires CPU flag: $flag" >&2
        exit 1
    fi
done
[ "$1" != --check-cpu ] || exit 0
export DOKOCR_PADDLE_FP16_ACTIVATIONS=1
template=/opt/dokocr/share/paddleocr-vl-chat_template.jinja
[ -r "$template" ] || template=/models/paddleocr-vl-chat_template.jinja
[ -r "$template" ] || { echo "PaddleOCR chat template is missing" >&2; exit 1; }
exec /opt/dokocr/bin/llama-server --port "$1" --host 127.0.0.1 --webui none --jinja \
    --model /models/paddleocr-vl-q8_0.gguf --mmproj /models/paddleocr-vl-mmproj.gguf \
    --chat-template-file "$template" --alias paddleocr-vl \
    --ctx-size 4096 --parallel 1 --batch-size 1024 --ubatch-size 512 --threads 4 --threads-batch 4 \
    --flash-attn on --cache-type-k f16 --cache-type-v f16 --cache-ram 0 --no-warmup \
    --n-gpu-layers 0 --no-mmproj-offload --no-fused-up-gate --temp 0
