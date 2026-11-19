#!/bin/sh
set -eu

has_flags() {
    for flag in "$@"; do
        if ! grep -qm1 -w "$flag" /proc/cpuinfo; then
            return 1
        fi
    done
    return 0
}

tier_supported() {
    case "$1" in
        avx512) has_flags avx2 fma f16c avx512f avx512dq avx512cd avx512bw avx512vl avx512vbmi avx512_vnni avx512_bf16 ;;
        avx2)   has_flags avx2 fma f16c ;;
        *)      return 1 ;;
    esac
}

if [ -n "${DOKOCR_CPU_TIER:-}" ]; then
    tier="$DOKOCR_CPU_TIER"
    case "$tier" in
        avx512|avx2) ;;
        *)
            echo "Invalid DOKOCR_CPU_TIER '$tier' (choose avx512 or avx2)" >&2
            exit 2
            ;;
    esac
    if ! tier_supported "$tier"; then
        echo "Requested DOKOCR_CPU_TIER='$tier' is not supported by this host CPU" >&2
        exit 1
    fi
elif tier_supported avx512; then
    tier=avx512
elif tier_supported avx2; then
    tier=avx2
else
    echo "Dok OCR unified runtime requires an x86_64 CPU with AVX2, FMA, and F16C (avx2 fma f16c); older AVX1-only CPUs can use standard PP-OCRv6 or --ocr-runtime external / --metadata-runtime external" >&2
    exit 1
fi

if [ ! -x "/opt/dokocr/$tier/bin/llama-server" ]; then
    echo "Dok OCR binary missing for selected CPU tier '$tier'" >&2
    exit 1
fi

printf '%s\n' "$tier"
