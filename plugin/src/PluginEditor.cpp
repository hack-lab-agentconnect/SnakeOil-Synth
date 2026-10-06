#include "PluginEditor.h"

SnakeOilEditor::SnakeOilEditor(SnakeOilProcessor& p) : AudioProcessorEditor(&p) {
    label_.setText("SnakeOil Synth (P0 scaffold)", juce::dontSendNotification);
    label_.setJustificationType(juce::Justification::centred);
    addAndMakeVisible(label_);
    setSize(400, 200);
}

void SnakeOilEditor::resized() { label_.setBounds(getLocalBounds()); }
