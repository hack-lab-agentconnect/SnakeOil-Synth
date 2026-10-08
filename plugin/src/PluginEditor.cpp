#include "PluginEditor.h"

#include <map>

#include "PluginProcessor.h"
#include "params_gen.hpp"

namespace {

juce::StringArray splitChoices(const char* choices) {
    return juce::StringArray::fromTokens(juce::String(choices == nullptr ? "" : choices), "|", "");
}

}  // namespace

SnakeOilEditor::SnakeOilEditor(SnakeOilProcessor& processor)
    : AudioProcessorEditor(&processor), processor_(processor) {
    int count = 0;
    const snakeoil::ParamSpec* specs = snakeoil::paramSpecs(count);
    auto& state = processor_.state();

    std::map<juce::String, juce::GroupComponent*> groupMap;
    for (int i = 0; i < count; ++i) {
        const auto& spec = specs[i];
        auto it = groupMap.find(spec.group);
        if (it == groupMap.end()) {
            auto group = std::make_unique<juce::GroupComponent>(spec.group, spec.group);
            auto* groupPtr = group.get();
            groups_.push_back(std::move(group));
            addAndMakeVisible(groupPtr);
            it = groupMap.emplace(spec.group, groupPtr).first;
        }

        Control control;
        if (spec.kind == snakeoil::ParamKind::Toggle) {
            control.toggle = std::make_unique<juce::ToggleButton>(spec.label);
            control.buttonAttachment = std::make_unique<
                juce::AudioProcessorValueTreeState::ButtonAttachment>(
                state, spec.id, *control.toggle);
            addAndMakeVisible(*control.toggle);
        } else if (spec.kind == snakeoil::ParamKind::Choice) {
            control.combo = std::make_unique<juce::ComboBox>();
            control.combo->addItemList(splitChoices(spec.choices), 1);
            control.comboAttachment = std::make_unique<
                juce::AudioProcessorValueTreeState::ComboBoxAttachment>(
                state, spec.id, *control.combo);
            control.label = std::make_unique<juce::Label>();
            static_cast<juce::Label*>(control.label.get())->setText(spec.label, juce::dontSendNotification);
            addAndMakeVisible(*control.label);
            addAndMakeVisible(*control.combo);
        } else {
            control.slider = std::make_unique<juce::Slider>(juce::Slider::RotaryHorizontalVerticalDrag,
                                                            juce::Slider::TextBoxBelow);
            control.sliderAttachment = std::make_unique<
                juce::AudioProcessorValueTreeState::SliderAttachment>(
                state, spec.id, *control.slider);
            control.label = std::make_unique<juce::Label>();
            static_cast<juce::Label*>(control.label.get())->setText(spec.label, juce::dontSendNotification);
            addAndMakeVisible(*control.label);
            addAndMakeVisible(*control.slider);
        }
        controls_.push_back(std::move(control));
    }

    meterLabel_.setJustificationType(juce::Justification::centredRight);
    addAndMakeVisible(meterLabel_);

    setSize(900, 620);
    startTimerHz(15);
}

SnakeOilEditor::~SnakeOilEditor() { stopTimer(); }

void SnakeOilEditor::paint(juce::Graphics& g) {
    g.fillAll(getLookAndFeel().findColour(juce::ResizableWindow::backgroundColourId));
}

void SnakeOilEditor::resized() {
    int count = 0;
    const snakeoil::ParamSpec* specs = snakeoil::paramSpecs(count);

    // Group the controls by their spec group, preserving order.
    struct GroupLayout {
        juce::GroupComponent* group;
        std::vector<int> indices;
    };
    std::vector<GroupLayout> layouts;
    for (int i = 0; i < count; ++i) {
        juce::GroupComponent* group = nullptr;
        // find the group component created for this spec's group name
        for (auto& g : groups_) {
            if (g->getText() == specs[i].group) {
                group = g.get();
                break;
            }
        }
        if (group == nullptr) {
            continue;
        }
        if (layouts.empty() || layouts.back().group != group) {
            layouts.push_back({group, {}});
        }
        layouts.back().indices.push_back(i);
    }

    const int groupWidth = 280;
    const int rowHeight = 300;
    const int margin = 10;
    int x = margin;
    int y = margin;
    int rowMax = rowHeight;
    for (auto& layout : layouts) {
        const int rows = static_cast<int>(layout.indices.size());
        const int height = std::min(rowMax, 30 + rows * 36);
        if (x + groupWidth > getWidth() - margin && x > margin) {
            x = margin;
            y += rowMax + margin;
        }
        layout.group->setBounds(x, y, groupWidth, height);
        int cy = y + 22;
        for (int index : layout.indices) {
            auto& control = controls_[static_cast<std::size_t>(index)];
            const int cx = x + 10;
            const int cw = groupWidth - 20;
            if (control.toggle) {
                control.toggle->setBounds(cx, cy, cw, 26);
                cy += 30;
            } else if (control.combo) {
                control.label->setBounds(cx, cy, cw, 18);
                control.combo->setBounds(cx, cy + 18, cw, 24);
                cy += 46;
            } else {
                control.label->setBounds(cx, cy, cw, 18);
                control.slider->setBounds(cx, cy + 18, cw, 44);
                cy += 64;
            }
        }
        x += groupWidth + margin;
    }
    meterLabel_.setBounds(getWidth() - 220, getHeight() - 24, 210, 20);
}

void SnakeOilEditor::timerCallback() {
    double left = 0.0;
    double right = 0.0;
    bool clipped = false;
    processor_.engineMeter(left, right, clipped);
    juce::String text = juce::String::formatted("L %.2f  R %.2f", left, right);
    if (clipped) {
        text += "  CLIP";
    }
    meterLabel_.setText(text, juce::dontSendNotification);
}
