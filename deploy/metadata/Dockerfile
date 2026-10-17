FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git cmake g++ make && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init . && git remote add origin https://github.com/ikawrakow/ik_llama.cpp.git \
    && git fetch --depth 1 origin cea2d61ffdac38ee2958ba88d120fa07cb67703a \
    && git checkout --detach FETCH_HEAD
COPY lfm-json-schema.patch /tmp/lfm-json-schema.patch
COPY test-lfm-json-schema.cpp tests/test-lfm-json-schema.cpp
RUN git apply --check /tmp/lfm-json-schema.patch && git apply /tmp/lfm-json-schema.patch
# ponytail: portable x86-64 AVX2 CPU build; no native/AVX512 or GPU requirement.
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    -DGGML_NATIVE=OFF -DGGML_AVX2=ON -DGGML_AVX512=OFF \
    -DGGML_AVX512_VBMI=OFF -DGGML_AVX512_VNNI=OFF -DGGML_AVX512_BF16=OFF \
    -DGGML_CUDA=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=ON \
    && cmake --build build --target llama-server test-lfm-json-schema -j2 \
    && ctest --test-dir build -R '^test-lfm-json-schema$' --output-on-failure

FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.source="https://github.com/DrBearJew/OCR"
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=build /src/LICENSE /usr/share/doc/dokocr-metadata/ik-LICENSE
COPY serve.py /usr/local/bin/dokocr-metadata
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DOKOCR_METADATA_COMPUTE=cpu
RUN llama-server --version
VOLUME ["/models"]
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --retries=3 --start-period=30m \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)" || exit 1
ENTRYPOINT ["python", "/usr/local/bin/dokocr-metadata"]
