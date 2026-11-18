"""Apply Paddle-only runtime changes on top of runtime.patch."""
from pathlib import Path


def replace(path, old, new):
    source = Path(path).read_text()
    if source.count(old) != 1:
        raise RuntimeError(f"unexpected source for {path}")
    Path(path).write_text(source.replace(old, new, 1))


# The gateway uses a separate process per model, but both exec the same binary.
# Choose the Q8_0 activation layout once, before any model tensors are built.
replace('ggml/src/ggml.c', 'static const ggml_type_traits_t type_traits[',
        'static ggml_type_traits_t type_traits[')
replace('ggml/src/ggml.c', '        // initialize time system (required on Windows)', '''        const char * paddle = getenv("DOKOCR_PADDLE_FP16_ACTIVATIONS");
        if (paddle && strcmp(paddle, "1") == 0) {
            type_traits[GGML_TYPE_Q8_0].vec_dot_type = GGML_TYPE_Q8_0;
        }

        // initialize time system (required on Windows)''')
replace('ggml/src/ggml-quants.c', '    enum ggml_type dot_type = GGML_TYPE_Q8_2_X4;',
        '    enum ggml_type dot_type = ggml_internal_get_type_traits(GGML_TYPE_Q8_0).vec_dot_type;')
replace('ggml/src/ggml-quants.c', '    if (iqk_mul_mat(nrc, nrc, n, GGML_TYPE_Q8_0, vx, bx, dot_type, vy, by, s, bs, 0, 1)) {',
        '    if (dot_type != GGML_TYPE_Q8_0 && iqk_mul_mat(nrc, nrc, n, GGML_TYPE_Q8_0, vx, bx, dot_type, vy, by, s, bs, 0, 1)) {')

# Portable CI builds do not get the extra foundation features from -march=native.
replace('ggml/src/CMakeLists.txt', 'list(APPEND ARCH_FLAGS -mavx512bw)',
        'list(APPEND ARCH_FLAGS -mavx512bw -mavx512dq -mavx512vl -mavx512cd)')

marker = '#if IK_PRINT_TIMING == 2\n            auto tim2 = ggml_time_us();\n            printf("set_inputs(mask1): %d us\\n", int(tim2-tim1));\n#endif'
mask = '''            // Paddle image tokens share a scalar position, but attention is
            // causal within the raster. Earlier image microbatches precede
            // this batch. Do not assume arbitrary embedding batches are laid out this way.
            if (lctx.model.arch == LLM_ARCH_PADDLEOCR && batch.embd && (data || data_f16)
                    && !data_swa && !data_swa_f16 && &mask_kv_self == &kv_self) {
                const int64_t head = mask_kv_self.head;
                const llama_pos * y = batch.pos + n_tokens;
                const llama_pos * x = batch.pos + 2*n_tokens;
                bool raster = head + n_tokens <= n_kv;
                for (int64_t j = 0; raster && j < n_tokens; ++j) {
                    raster = batch.n_seq_id[j] == 1 && batch.seq_id[j][0] == batch.seq_id[0][0]
                        && batch.pos[j] == batch.pos[0] && mask_kv_self.cells[head+j].pos == batch.pos[j]
                        && (j == 0 || y[j-1] < y[j] || (y[j-1] == y[j] && x[j-1] < x[j]));
                }
                if (raster) {
                    const auto inf = ggml_fp32_to_fp16(-INFINITY);
                    for (int64_t j = 0; j < n_tokens; ++j) {
                        const int64_t end = j*n_kv + head + n_tokens;
                        const int64_t first = j*n_kv + head + j + 1;
                        if (data_f16) std::fill(data_f16 + first, data_f16 + end, inf);
                        if (data) std::fill(data + first, data + end, -INFINITY);
                    }
                }
            }
'''
replace('src/llama.cpp', marker, mask + marker)
