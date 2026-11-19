FROM debian:bookworm-slim AS src
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git cmake g++ make python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init . && git remote add origin https://github.com/ikawrakow/ik_llama.cpp.git \
    && git fetch --depth 1 origin cea2d61ffdac38ee2958ba88d120fa07cb67703a \
    && git checkout --detach FETCH_HEAD
COPY paddle-ik/runtime.patch paddle-ik/apply-profile.py /tmp/
RUN git apply /tmp/runtime.patch && python3 /tmp/apply-profile.py

FROM src AS build-avx512
ARG BUILD_JOBS=2
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON \
    -DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON \
    -DGGML_AVX512=ON -DGGML_AVX512_VBMI=ON -DGGML_AVX512_VNNI=ON -DGGML_AVX512_BF16=ON \
    -DGGML_CUDA=OFF -DGGML_CURL=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=ON \
    && cmake --build build --target llama-server llama-quantize test-paddleocr test-mtmd-positions test-lfm-json-schema -j"$BUILD_JOBS"

FROM src AS build-avx2
ARG BUILD_JOBS=2
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON \
    -DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON \
    -DGGML_AVX512=OFF -DGGML_AVX512_VBMI=OFF -DGGML_AVX512_VNNI=OFF -DGGML_AVX512_BF16=OFF \
    -DGGML_CUDA=OFF -DGGML_CURL=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=ON \
    && cmake --build build --target llama-server llama-quantize test-paddleocr test-mtmd-positions test-lfm-json-schema -j"$BUILD_JOBS" \
    && ctest --test-dir build -R '^test-(paddleocr|mtmd-positions|lfm-json-schema)$' --output-on-failure

FROM debian:bookworm-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --chmod=755 paddle-ik/cpu-tier.sh /usr/local/bin/dokocr-cpu-tier
COPY --chmod=755 paddle-ik/serve.sh /usr/local/bin/dokocr-paddle-ik
ENTRYPOINT ["/usr/local/bin/dokocr-paddle-ik"]

FROM base AS runtime
COPY --from=build-avx512 /src/build/bin/llama-server /opt/dokocr/avx512/bin/
COPY --from=build-avx512 /src/build/src/libllama.so /src/build/ggml/src/libggml.so /src/build/examples/mtmd/libmtmd.so /opt/dokocr/avx512/lib/
COPY --from=build-avx2 /src/build/bin/llama-server /opt/dokocr/avx2/bin/
COPY --from=build-avx2 /src/build/src/libllama.so /src/build/ggml/src/libggml.so /src/build/examples/mtmd/libmtmd.so /opt/dokocr/avx2/lib/
COPY --from=build-avx512 /src/LICENSE /usr/share/doc/dokocr-paddle-ik/LICENSE
COPY paddlevl/paddleocr-vl-chat_template.jinja /opt/dokocr/share/paddleocr-vl-chat_template.jinja
RUN for tier in avx512 avx2; do \
      LD_LIBRARY_PATH="/opt/dokocr/$tier/lib" ldd "/opt/dokocr/$tier/bin/llama-server" > /tmp/linkage \
      && ! grep 'not found' /tmp/linkage; \
    done

FROM debian:bookworm-slim AS swap
ADD --checksum=sha256:31f325b39b046869a4c6661803deeb522587ff4895a37f697d64a10e4a484742 https://github.com/mostlygeek/llama-swap/releases/download/v228/llama-swap_228_linux_amd64.tar.gz /tmp/swap.tar.gz
RUN tar -xzf /tmp/swap.tar.gz -C /usr/local/bin llama-swap

FROM runtime AS unified
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build-avx512 /src/build/bin/llama-quantize /opt/dokocr/avx512/bin/
COPY --from=build-avx2 /src/build/bin/llama-quantize /opt/dokocr/avx2/bin/
COPY --from=swap /usr/local/bin/llama-swap /usr/local/bin/
COPY --chmod=755 paddle-ik/serve-role.sh /usr/local/bin/dokocr-serve-role
COPY paddle-ik/llama-swap.yml /etc/llama-swap.yml
COPY paddle-ik/gateway.py /opt/dokocr/gateway.py
COPY metadata/serve.py /opt/dokocr/download.py
EXPOSE 8080
ENTRYPOINT ["python3", "/opt/dokocr/gateway.py"]
