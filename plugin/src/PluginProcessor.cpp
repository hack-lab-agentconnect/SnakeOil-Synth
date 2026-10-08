#include "PluginProcessor.h"

#include <algorithm>
#include <cmath>

#include <juce_audio_utils/juce_audio_utils.h>

#include "PluginEditor.h"
#include <SnakeOilData.h>

namespace {

juce::StringArray splitChoices(const char* choices) {
    return juce::StringArray::fromTokens(juce::String(choices == nullptr ? "" : choices), "|", "");
}

std::vector<double> binaryToDoubles(const char* data, int sizeInBytes) {
    const int count = sizeInBytes / static_cast<int>(sizeof(float));
    std::vector<double> out(static_cast<std::size_t>(count));
    const auto* floats = reinterpret_cast<const float*>(data);
    for (int i = 0; i < count; ++i) {
        out[static_cast<std::size_t>(i)] = static_cast<double>(floats[i]);
    }
    return out;
}

}  // namespace

SnakeOilProcessor::SnakeOilProcessor()
    : AudioProcessor(BusesProperties().withOutput("Output", juce::AudioChannelSet::stereo(), true)),
      apvts_(*this, nullptr, "PARAMETERS", makeLayout()) {
    int count = 0;
    const snakeoil::ParamSpec* specs = snakeoil::paramSpecs(count);
    specs_.assign(specs, specs + count);
    rawValues_.reserve(specs_.size());
    for (const auto* spec : specs_) {
        rawValues_.push_back(apvts_.getRawParameterValue(spec->id));
    }
    engine_ = std::make_unique<snakeoil::Engine>(44100.0, 512);
    loadNoiseTables();
    for (int i = 0; i < count; ++i) {
        if (specs_[static_cast<std::size_t>(i)]->kind == snakeoil::ParamKind::Choice) {
            const auto choices = splitChoices(specs_[static_cast<std::size_t>(i)]->choices);
            const int index = static_cast<int>(specs_[static_cast<std::size_t>(i)]->defaultValue);
            if (index >= 0 && index < choices.size()) {
                engine_->setChoice(specs_[static_cast<std::size_t>(i)]->id, choices[index].toStdString());
            }
        }
    }
}

juce::AudioProcessorValueTreeState::ParameterLayout SnakeOilProcessor::makeLayout() {
    int count = 0;
    const snakeoil::ParamSpec* specs = snakeoil::paramSpecs(count);
    juce::AudioProcessorValueTreeState::ParameterLayout layout;
    for (int i = 0; i < count; ++i) {
        const auto& spec = specs[i];
        const juce::ParameterID pid{spec.id, 1};
        switch (spec.kind) {
            case snakeoil::ParamKind::Continuous: {
                juce::NormalisableRange<float> range(spec.minimum, spec.maximum);
                if (spec.logarithmic && spec.minimum > 0.0f) {
                    range.setSkewForCentre(std::sqrt(spec.minimum * spec.maximum));
                }
                layout.add(std::make_unique<juce::AudioParameterFloat>(
                    pid, spec.label, range, spec.defaultValue));
                break;
            }
            case snakeoil::ParamKind::Toggle:
                layout.add(std::make_unique<juce::AudioParameterBool>(
                    pid, spec.label, spec.defaultValue >= 0.5f));
                break;
            case snakeoil::ParamKind::Choice:
                layout.add(std::make_unique<juce::AudioParameterChoice>(
                    pid, spec.label, splitChoices(spec.choices),
                    static_cast<int>(spec.defaultValue)));
                break;
        }
    }
    return layout;
}

void SnakeOilProcessor::prepareToPlay(double sampleRate, int samplesPerBlock) {
    const int block = std::min(std::max(samplesPerBlock, 64), snakeoil::kMaxBlock);
    engine_ = std::make_unique<snakeoil::Engine>(sampleRate, block);
    loadNoiseTables();
    scratch_.assign(static_cast<std::size_t>(block) * 2, 0.0f);
}

void SnakeOilProcessor::loadNoiseTables() {
    if (engine_ == nullptr) {
        return;
    }
    engine_->setNoiseTable("white", binaryToDoubles(BinaryData::noisetable_white_f32,
                                                    BinaryData::noisetable_white_f32Size));
    engine_->setNoiseTable("pink", binaryToDoubles(BinaryData::noisetable_pink_f32,
                                                   BinaryData::noisetable_pink_f32Size));
    engine_->setNoiseTable("brown", binaryToDoubles(BinaryData::noisetable_brown_f32,
                                                    BinaryData::noisetable_brown_f32Size));
}

bool SnakeOilProcessor::isBusesLayoutSupported(const BusesLayout& layouts) const {
    const auto out = layouts.getMainOutputChannelSet();
    return out == juce::AudioChannelSet::mono() || out == juce::AudioChannelSet::stereo();
}

void SnakeOilProcessor::syncParametersToEngine() {
    for (std::size_t i = 0; i < specs_.size(); ++i) {
        const auto* spec = specs_[i];
        const float value = rawValues_[i]->load();
        if (spec->kind == snakeoil::ParamKind::Choice) {
            const auto choices = splitChoices(spec->choices);
            const int index = juce::jlimit(0, choices.size() - 1, static_cast<int>(std::lround(value)));
            engine_->setChoice(spec->id, choices[index].toStdString());
        } else {
            engine_->setParamById(spec->id, static_cast<double>(value));
        }
    }
}

void SnakeOilProcessor::handleMidi(const juce::MidiBuffer& midi) {
    for (const auto metadata : midi) {
        const auto message = metadata.getMessage();
        if (message.isNoteOn()) {
            engine_->noteOn(message.getNoteNumber(), message.getVelocity());
        } else if (message.isNoteOff()) {
            engine_->noteOff(message.getNoteNumber());
        } else if (message.isPitchWheel()) {
            engine_->setPitchBend((message.getPitchWheelValue() - 8192) / 8192.0);
        } else if (message.isController()) {
            const int cc = message.getControllerNumber();
            const int value = message.getControllerValue();
            if (cc == 1) {
                engine_->setModWheel(value / 127.0);
            } else if (cc == 64) {
                engine_->setSustain(value >= 64);
            } else if (cc == 123) {
                engine_->allNotesOff();
            } else if (cc == 121) {
                engine_->resetControllers();
            }
        } else if (message.isChannelPressure()) {
            engine_->setAftertouch(message.getChannelPressureValue() / 127.0);
        } else if (message.isAftertouch()) {
            engine_->setAftertouch(message.getAfterTouchValue() / 127.0);
        }
    }
}

void SnakeOilProcessor::processBlock(juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi) {
    juce::ScopedNoDenormals noDenormals;
    const int n = buffer.getNumSamples();
    if (n <= 0) {
        midi.clear();
        return;
    }
    syncParametersToEngine();
    handleMidi(midi);
    midi.clear();

    if (auto* playHead = getPlayHead()) {
        if (const auto position = playHead->getPosition()) {
            if (const auto bpm = position->getBpm()) {
                engine_->setHostTempo(*bpm, true);
            }
        }
    }

    if (scratch_.size() < static_cast<std::size_t>(n) * 2) {
        scratch_.assign(static_cast<std::size_t>(n) * 2, 0.0f);
    }
    const int channels = buffer.getNumChannels();
    int done = 0;
    while (done < n) {
        const int chunk = std::min(n - done, snakeoil::kMaxBlock);
        engine_->render(scratch_.data(), chunk);
        for (int ch = 0; ch < channels; ++ch) {
            const int source = ch < 2 ? ch : 0;
            float* out = buffer.getWritePointer(ch) + done;
            for (int i = 0; i < chunk; ++i) {
                out[i] = scratch_[static_cast<std::size_t>(i) * 2 + source];
            }
        }
        done += chunk;
    }
}

juce::AudioProcessorEditor* SnakeOilProcessor::createEditor() {
    return new SnakeOilEditor(*this);
}

void SnakeOilProcessor::engineMeter(double& left, double& right, bool& clipped) const {
    if (engine_ != nullptr) {
        engine_->peekMeter(left, right, clipped);
    } else {
        left = right = 0.0;
        clipped = false;
    }
}

void SnakeOilProcessor::getStateInformation(juce::MemoryBlock& destData) {
    const auto state = apvts_.copyState();
    juce::MemoryOutputStream stream(destData, false);
    state.writeToStream(stream);
}

void SnakeOilProcessor::setStateInformation(const void* data, int sizeInBytes) {
    const auto tree = juce::ValueTree::readFromData(data, static_cast<std::size_t>(sizeInBytes));
    if (tree.isValid()) {
        apvts_.replaceState(tree);
    }
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() {
    return new SnakeOilProcessor();
}
