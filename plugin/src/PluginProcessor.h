#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

#include <atomic>
#include <memory>
#include <vector>

#include "params_gen.hpp"
#include "snakeoil/engine.hpp"

class SnakeOilProcessor : public juce::AudioProcessor {
public:
    SnakeOilProcessor();
    ~SnakeOilProcessor() override = default;

    void prepareToPlay(double sampleRate, int samplesPerBlock) override;
    void releaseResources() override {}
    bool isBusesLayoutSupported(const BusesLayout& layouts) const override;
    void processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return JucePlugin_Name; }
    bool acceptsMidi() const override { return true; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram(int) override {}
    const juce::String getProgramName(int) override { return {}; }
    void changeProgramName(int, const juce::String&) override {}

    void getStateInformation(juce::MemoryBlock&) override;
    void setStateInformation(const void*, int) override;

    juce::AudioProcessorValueTreeState& state() { return apvts_; }
    void engineMeter(double& left, double& right, bool& clipped) const;

private:
    static juce::AudioProcessorValueTreeState::ParameterLayout makeLayout();
    void syncParametersToEngine();
    void handleMidi(const juce::MidiBuffer&);
    void loadNoiseTables();

    juce::AudioProcessorValueTreeState apvts_;
    std::unique_ptr<snakeoil::Engine> engine_;
    std::vector<std::atomic<float>*> rawValues_;
    std::vector<const snakeoil::ParamSpec*> specs_;
    std::vector<float> scratch_;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(SnakeOilProcessor)
};
