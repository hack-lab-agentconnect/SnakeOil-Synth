#include "PluginProcessor.h"

#include "PluginEditor.h"

SnakeOilProcessor::SnakeOilProcessor()
    : AudioProcessor(BusesProperties().withOutput("Output", juce::AudioChannelSet::stereo(), true)) {}

void SnakeOilProcessor::prepareToPlay(double, int) {}

bool SnakeOilProcessor::isBusesLayoutSupported(const BusesLayout& layouts) const {
    return layouts.getMainOutputChannelSet() == juce::AudioChannelSet::stereo();
}

void SnakeOilProcessor::processBlock(juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi) {
    juce::ScopedNoDenormals noDenormals;
    midi.clear();  // P0: MIDI is accepted but ignored.
    buffer.clear();
}

juce::AudioProcessorEditor* SnakeOilProcessor::createEditor() { return new SnakeOilEditor(*this); }

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() { return new SnakeOilProcessor(); }
