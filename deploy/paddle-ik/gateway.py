"""Provision the two pinned model assets, then start one lazy model gateway."""
import fcntl
import os
from pathlib import Path
import shutil
import subprocess

from download import ensure_model, digest

MODEL_DIR = Path('/models')
PADDLE = 'https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/resolve/511b09642bb324401f15f97cc23bc67e8f0a291d/'
SOURCE = 'PaddleOCR-VL-1.6-GGUF.gguf'
SOURCE_HASH = 'f3ae46ec885050acf4b3d31944431e1fd90d50664fb09126af4a3c050ba14ee8'
PROJECTOR_HASH = '204d757d7610d9b3faab10d506d69e5b244e32bf765e2bab2d0167e65e0a058a'
Q8_SIZE = 498316256
Q8_HASH = 'a9a23a93838383ecb8a3bb166c2c0491c226d4442b22855b879920ca66854ef7'


def prepare_ocr():
    ensure_model(MODEL_DIR, PADDLE + 'PaddleOCR-VL-1.6-GGUF-mmproj.gguf', 881770560,
                 PROJECTOR_HASH, name='paddleocr-vl-mmproj.gguf')
    q8 = MODEL_DIR / 'paddleocr-vl-q8_0.gguf'
    lock = q8.with_suffix('.lock')
    temp = q8.with_suffix('.building')
    if any(path.is_symlink() for path in (q8, lock, temp)):
        raise RuntimeError('Refusing symlink in OCR model cache')
    with lock.open('a') as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        if not q8.exists():
            source = ensure_model(MODEL_DIR, PADDLE + SOURCE, 935769056, SOURCE_HASH, name=SOURCE)
            if shutil.disk_usage(MODEL_DIR).free < Q8_SIZE + 128 * 1024**2:
                raise RuntimeError('Insufficient space to prepare PaddleOCR weights')
            subprocess.run(['/opt/dokocr/bin/llama-quantize', '--pure', str(source), str(temp), 'Q8_0', '2'],
                           check=True)
            if temp.stat().st_size != Q8_SIZE or digest(temp) != Q8_HASH:
                raise RuntimeError('Prepared PaddleOCR weights did not match the verified Q8 model')
            os.replace(temp, q8)
        elif q8.stat().st_size != Q8_SIZE or digest(q8) != Q8_HASH:
            raise RuntimeError('Existing PaddleOCR Q8 file is different; preserved, not overwritten')


def main():
    subprocess.run(['/usr/local/bin/dokocr-paddle-ik', '--check-cpu'], check=True)
    prepare_ocr()
    ensure_model(MODEL_DIR)
    os.execv('/usr/local/bin/llama-swap', ['llama-swap', '-config', '/etc/llama-swap.yml', '-listen', '0.0.0.0:8080'])


if __name__ == '__main__':
    main()
