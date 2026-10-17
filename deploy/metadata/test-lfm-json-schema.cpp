#include "chat.h"
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>

int main() {
    try {
        for (const char * path : {"models/templates/LFM2.5-Instruct.jinja", "models/templates/google-gemma-4-31B-it.jinja"}) {
            std::ifstream file(path);
            if (!file) throw std::runtime_error("missing template fixture");
            const std::string source((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
            auto templates = common_chat_templates_ptr(common_chat_templates_init(nullptr, source));
            common_chat_templates_inputs inputs;
            common_chat_msg user;
            user.role = "user";
            user.content = "Extract invoice metadata.";
            inputs.messages = {user};
            inputs.use_jinja = true;
            inputs.enable_thinking = true;
            inputs.reasoning_format = COMMON_REASONING_FORMAT_AUTO;
            for (const char * schema : {"{}", R"({"type":"object","properties":{"invoice_number":{"type":"object","properties":{"value":{"type":"string"}},"required":["value"],"additionalProperties":false}},"required":["invoice_number"],"additionalProperties":false})"}) {
                inputs.json_schema = schema;
                const auto result = common_chat_templates_apply(templates.get(), inputs);
                if (result.grammar.empty()) throw std::runtime_error("schema grammar was ignored");
                if (result.grammar_lazy) throw std::runtime_error("schema grammar must apply immediately, not wait for a tool trigger");
                if (!result.supports_thinking) throw std::runtime_error("reasoning support was lost");
            }
            inputs.json_schema.clear();
            if (!common_chat_templates_apply(templates.get(), inputs).grammar.empty()) {
                throw std::runtime_error("plain chat unexpectedly constrained");
            }
        }
        std::cout << "PASS: LFM2.5 and Gemma JSON mode, typed schema, reasoning, and unconstrained chat\n";
        return 0;
    } catch (const std::exception & error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
