#!/bin/sh
set -eu

detect_threads() {
    if [ -n "${DOKOCR_THREADS:-}" ]; then
        case "$DOKOCR_THREADS" in
            ''|*[!0-9]*)
                echo "Invalid DOKOCR_THREADS '$DOKOCR_THREADS' (expected positive integer)" >&2
                exit 2
                ;;
        esac
        if [ "$DOKOCR_THREADS" -lt 1 ]; then
            echo "Invalid DOKOCR_THREADS '$DOKOCR_THREADS' (expected >= 1)" >&2
            exit 2
        fi
        printf '%s\n' "$DOKOCR_THREADS"
        return 0
    fi

    # Prefer physical cores (avoids SMT oversubscription on Zen/Intel), falling back to nproc.
    n=$(awk -F: '
        /^[[:space:]]*physical id[[:space:]]*:/ { pid=$2; gsub(/[[:space:]]/, "", pid) }
        /^[[:space:]]*core id[[:space:]]*:/     { cid=$2; gsub(/[[:space:]]/, "", cid); if (pid != "") seen[pid ":" cid]=1 }
        END { c=0; for (k in seen) c++; print c }
    ' /proc/cpuinfo 2>/dev/null || echo 0)
    if [ "${n:-0}" -lt 1 ]; then
        n=$(nproc 2>/dev/null || echo 4)
    fi

    # Respect Docker/systemd cgroup v2 or v1 CPU quotas when tighter than host cores.
    if [ -r /sys/fs/cgroup/cpu.max ]; then
        set -- $(cat /sys/fs/cgroup/cpu.max 2>/dev/null || true)
        if [ "${1:-max}" != "max" ] && [ "${2:-0}" -gt 0 ] 2>/dev/null; then
            q=$(( $1 / $2 ))
            [ "$q" -lt 1 ] && q=1
            [ "$q" -lt "$n" ] && n=$q
        fi
    elif [ -r /sys/fs/cgroup/cpu/cpu.cfs_quota_us ] && [ -r /sys/fs/cgroup/cpu/cpu.cfs_period_us ]; then
        quota=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || echo -1)
        period=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us 2>/dev/null || echo 0)
        if [ "$quota" -gt 0 ] 2>/dev/null && [ "$period" -gt 0 ] 2>/dev/null; then
            q=$(( quota / period ))
            [ "$q" -lt 1 ] && q=1
            [ "$q" -lt "$n" ] && n=$q
        fi
    fi

    # Default ceiling of 8 physical cores hits the memory-bandwidth sweet spot without pegging larger hosts (override via DOKOCR_THREADS).
    [ "$n" -gt 8 ] && n=8
    [ "$n" -lt 1 ] && n=1
    printf '%s\n' "$n"
}

if [ "${1:-}" = "--threads" ]; then
    detect_threads
    exit 0
fi

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
