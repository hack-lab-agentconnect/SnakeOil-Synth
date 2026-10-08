#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

#include "json_mini.hpp"
#include "snakeoil/engine.hpp"

namespace {

bool readFile(const std::string& path, std::string& out) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        return false;
    }
    out.assign((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    return true;
}

bool readFloats(const std::string& path, std::vector<float>& out) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        return false;
    }
    in.seekg(0, std::ios::end);
    const std::streamoff bytes = in.tellg();
    in.seekg(0, std::ios::beg);
    out.resize(static_cast<std::size_t>(bytes / 4));
    in.read(reinterpret_cast<char*>(out.data()), bytes);
    return static_cast<bool>(in) || in.eof();
}

void applySet(snakeoil::Engine& engine, const std::string& id,
              const jsonmini::Value& value) {
    if (value.isNumber()) {
        engine.setParamById(id, value.number);
    } else if (value.type == jsonmini::Value::kBool) {
        engine.setParamById(id, value.boolean ? 1.0 : 0.0);
    } else if (value.isString()) {
        engine.setChoice(id, value.str);
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: golden_check <scenario.json> <expected.f32>\n");
        return 2;
    }
    std::string text;
    if (!readFile(argv[1], text)) {
        std::fprintf(stderr, "cannot read scenario %s\n", argv[1]);
        return 2;
    }
    std::vector<float> expected;
    if (!readFloats(argv[2], expected)) {
        std::fprintf(stderr, "cannot read expected audio %s\n", argv[2]);
        return 2;
    }

    jsonmini::Value scenario;
    try {
        scenario = jsonmini::parse(text);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "invalid scenario: %s\n", e.what());
        return 2;
    }

    const double sampleRate = scenario.find("sample_rate")->number;
    const int blockSize = static_cast<int>(scenario.find("block_size")->number);
    const int blocks = static_cast<int>(scenario.find("blocks")->number);
    int tailSlots = 0;
    if (const jsonmini::Value* tail = scenario.find("tail_slots")) {
        if (tail->isNumber()) {
            tailSlots = static_cast<int>(tail->number);
        }
    }
    const jsonmini::Value* events = scenario.find("events");

    snakeoil::Engine engine(sampleRate, blockSize, snakeoil::kMaxVoices, tailSlots, tailSlots);
    const std::string scenarioPath = argv[1];
    const std::size_t slash = scenarioPath.find_last_of('/');
    const std::string goldenDir =
        slash == std::string::npos ? std::string(".") : scenarioPath.substr(0, slash);
    if (const jsonmini::Value* tables = scenario.find("noise_tables")) {
        for (const auto& color : tables->array) {
            std::vector<float> raw;
            const std::string path = goldenDir + "/noisetable_" + color.str + ".f32";
            if (readFloats(path, raw)) {
                engine.setNoiseTable(color.str,
                                     std::vector<double>(raw.begin(), raw.end()));
            }
        }
    }
    if (const jsonmini::Value* starts = scenario.find("noise_starts")) {
        std::vector<long long> values;
        for (const auto& value : starts->array) {
            values.push_back(static_cast<long long>(value.number));
        }
        engine.setNoiseStarts(std::move(values));
    }
    if (const jsonmini::Value* phases = scenario.find("unison_phases")) {
        std::vector<double> values;
        for (const auto& value : phases->array) {
            values.push_back(value.number);
        }
        engine.setUnisonPhases(std::move(values));
    }
    if (const jsonmini::Value* params = scenario.find("params")) {
        if (params->isObject()) {
            for (const auto& entry : params->object) {
                applySet(engine, entry.first, entry.second);
            }
        }
    }
    std::vector<std::vector<const jsonmini::Value*>> byBlock(static_cast<std::size_t>(blocks));
    if (events != nullptr && events->isArray()) {
        for (const auto& event : events->array) {
            const jsonmini::Value* block = event.find("block");
            if (block != nullptr && block->isNumber()) {
                const int index = static_cast<int>(block->number);
                if (index >= 0 && index < blocks) {
                    byBlock[static_cast<std::size_t>(index)].push_back(&event);
                }
            }
        }
    }

    std::vector<float> rendered;
    rendered.reserve(static_cast<std::size_t>(blocks) * static_cast<std::size_t>(blockSize) * 2);
    std::vector<float> block(static_cast<std::size_t>(blockSize) * 2);
    for (int i = 0; i < blocks; ++i) {
        for (const jsonmini::Value* event : byBlock[static_cast<std::size_t>(i)]) {
            if (const jsonmini::Value* on = event->find("note_on")) {
                engine.noteOn(static_cast<int>(on->array[0].number), on->array[1].number);
            }
            if (const jsonmini::Value* off = event->find("note_off")) {
                engine.noteOff(static_cast<int>(off->array[0].number));
            }
            if (const jsonmini::Value* wheel = event->find("wheel")) {
                engine.setModWheel(wheel->number);
            }
            if (const jsonmini::Value* at = event->find("aftertouch")) {
                engine.setAftertouch(at->number);
            }
            if (const jsonmini::Value* set = event->find("set")) {
                for (const auto& entry : set->object) {
                    applySet(engine, entry.first, entry.second);
                }
            }
        }
        engine.render(block.data(), blockSize);
        rendered.insert(rendered.end(), block.begin(), block.end());
    }

    if (rendered.size() != expected.size()) {
        std::fprintf(stderr, "size mismatch: rendered %zu samples, expected %zu\n",
                     rendered.size(), expected.size());
        return 1;
    }
    double maxDiff = 0.0;
    std::size_t over = 0;
    for (std::size_t i = 0; i < rendered.size(); ++i) {
        const double diff = std::fabs(static_cast<double>(rendered[i]) -
                                      static_cast<double>(expected[i]));
        maxDiff = std::max(maxDiff, diff);
        if (diff > 1e-6) {
            ++over;
        }
    }
    const char* name = argv[1];
    if (over == 0) {
        std::printf("PASS %s: %zu samples, max abs diff %.3e\n", name, rendered.size(),
                    maxDiff);
        return 0;
    }
    std::fprintf(stderr, "FAIL %s: %zu/%zu samples exceed 1e-6 (max abs diff %.3e)\n",
                 name, over, rendered.size(), maxDiff);
    return 1;
}
