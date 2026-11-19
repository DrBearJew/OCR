#!/bin/sh
set -eu
[ "$#" = 2 ] || exit 2
role=$1 port=$2
case "$role" in
 paddleocr-vl)
    export DOKOCR_PADDLE_FP16_ACTIVATIONS=1
    exec /usr/local/bin/dokocr-paddle-ik "$port"
    ;;
 metadata)
    tier=$(/usr/local/bin/dokocr-cpu-tier)
    export LD_LIBRARY_PATH="/opt/dokocr/$tier/lib"
    unset DOKOCR_PADDLE_FP16_ACTIVATIONS
    exec "/opt/dokocr/$tier/bin/llama-server" --port "$port" --host 127.0.0.1 --webui none --jinja \
      --model /models/LFM2.5-8B-A1B-Q5_K_M.gguf --alias metadata --ctx-size 128000 \
      --parallel 1 --batch-size 1024 --ubatch-size 512 --threads 4 --threads-batch 4 \
      --cache-type-k q8_0 --cache-type-v q8_0 --cache-ram 0 --ctx-checkpoints 0 \
      --ctx-checkpoints-interval 0 --no-warmup --spec-type none --reasoning-budget 3072 \
      --flash-attn on --n-gpu-layers 0 --device none
    ;;
 *) echo 'Unknown Dok OCR model role' >&2; exit 2 ;;
esac
