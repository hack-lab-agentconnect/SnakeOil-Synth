#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

#include "PluginProcessor.h"

class SnakeOilEditor : public juce::AudioProcessorEditor {
public:
    explicit SnakeOilEditor(SnakeOilProcessor&);
    void resized() override;

private:
    juce::Label label_;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(SnakeOilEditor)
};
