#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

#include <memory>
#include <vector>

class SnakeOilProcessor;

class SnakeOilEditor : public juce::AudioProcessorEditor, private juce::Timer {
public:
    explicit SnakeOilEditor(SnakeOilProcessor& processor);
    ~SnakeOilEditor() override;

    void paint(juce::Graphics&) override;
    void resized() override;

private:
    void timerCallback() override;

    struct Control {
        std::unique_ptr<juce::Component> label;
        std::unique_ptr<juce::Slider> slider;
        std::unique_ptr<juce::ToggleButton> toggle;
        std::unique_ptr<juce::ComboBox> combo;
        std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> sliderAttachment;
        std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> buttonAttachment;
        std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> comboAttachment;
    };

    SnakeOilProcessor& processor_;
    std::vector<std::unique_ptr<juce::GroupComponent>> groups_;
    std::vector<Control> controls_;
    juce::Label meterLabel_;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(SnakeOilEditor)
};
