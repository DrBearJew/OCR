"""Apply Paddle-only runtime changes on top of runtime.patch."""
from pathlib import Path


def replace(path, old, new):
    source = Path(path).read_text()
    if source.count(old) != 1:
        raise RuntimeError(f"unexpected source for {path}")
    Path(path).write_text(source.replace(old, new, 1))


# This is a dedicated PaddleOCR build. Use original Q8_0 activation scales.
for suffix, marker in [
    ('ggml.c', '.vec_dot                  = ggml_vec_dot_q8_0_q8_0,\n'),
    ('ggml-quants.c', None),
]:
    marker = marker or ''
    tail = '\n    enum ggml_type dot_type = GGML_TYPE_Q8_2_X4;' if not marker else ''
    replace('ggml/src/' + suffix, marker + '#if GGML_USE_IQK_MULMAT' + tail,
            marker + '#if 0 // PaddleOCR requires FP16 activation scales' + tail)

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
