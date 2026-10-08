cmake_minimum_required(VERSION 3.24)
project(SnakeOilSynth VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)
set(FETCHCONTENT_QUIET OFF)

FetchContent_Declare(
    JUCE
    GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
    GIT_TAG 9.0.3
    GIT_SHALLOW TRUE)
FetchContent_Declare(
    doctest
    GIT_REPOSITORY https://github.com/doctest/doctest.git
    GIT_TAG v2.4.11
    SOURCE_SUBDIR header_only_no_cmake
    GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(JUCE doctest)

message(STATUS "JUCE fetched to ${juce_SOURCE_DIR}; read its license files before distributing binaries:")
foreach(_f LICENSE.md README.md)
    if(EXISTS "${juce_SOURCE_DIR}/${_f}")
        message(STATUS "  ${juce_SOURCE_DIR}/${_f}")
    endif()
endforeach()

# Strict warnings for OUR targets only (never JUCE).
function(snakeoil_strict_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /WX)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
endfunction()

enable_testing()

# --- DSP library (no JUCE) ---------------------------------------------------
add_library(snakeoil_dsp STATIC
    dsp/snakeoil/version.cpp)
target_include_directories(snakeoil_dsp PUBLIC dsp)
target_compile_features(snakeoil_dsp PUBLIC cxx_std_20)
snakeoil_strict_warnings(snakeoil_dsp)

# --- Tests -------------------------------------------------------------------
add_executable(snakeoil_tests tests/test_main.cpp)
target_include_directories(snakeoil_tests SYSTEM PRIVATE "${doctest_SOURCE_DIR}")
target_link_libraries(snakeoil_tests PRIVATE snakeoil_dsp)
snakeoil_strict_warnings(snakeoil_tests)
add_test(NAME snakeoil_tests COMMAND snakeoil_tests)

add_executable(golden_check tests/golden_check.cpp)
target_include_directories(golden_check PRIVATE tests)
target_link_libraries(golden_check PRIVATE snakeoil_dsp)
snakeoil_strict_warnings(golden_check)

add_executable(dsp_selftest tests/dsp_selftest.cpp)
target_link_libraries(dsp_selftest PRIVATE snakeoil_dsp)
snakeoil_strict_warnings(dsp_selftest)
add_test(NAME dsp_selftest COMMAND dsp_selftest)

# Golden sound lock: replay each scenario and compare with the Python reference
# (tools/export_cpp_golden.py). Runs without JUCE.
file(GLOB _snakeoil_golden "${CMAKE_CURRENT_SOURCE_DIR}/tests/golden/*.scenario.json")
foreach(_scenario ${_snakeoil_golden})
    get_filename_component(_name "${_scenario}" NAME)
    string(REGEX REPLACE "\\.scenario\\.json$" "" _name "${_name}")
    add_test(
        NAME golden_${_name}
        COMMAND golden_check "${_scenario}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/golden/${_name}.f32")
endforeach()

# --- Plugin ------------------------------------------------------------------
juce_add_binary_data(SnakeOilData SOURCES
    tests/golden/noisetable_white.f32
    tests/golden/noisetable_pink.f32
    tests/golden/noisetable_brown.f32)

juce_add_plugin(SnakeOilSynth
    COMPANY_NAME "SnakeOil"
    PRODUCT_NAME "SnakeOil Synth"
    FORMATS VST3 Standalone
    IS_SYNTH TRUE
    NEEDS_MIDI_INPUT TRUE
    NEEDS_MIDI_OUTPUT FALSE
    PLUGIN_MANUFACTURER_CODE Snko
    PLUGIN_CODE Soil
    VST3_CATEGORIES Instrument Synth
    COPY_PLUGIN_AFTER_BUILD FALSE)

target_sources(SnakeOilSynth PRIVATE
    src/PluginProcessor.cpp
    src/PluginEditor.cpp)

target_compile_definitions(SnakeOilSynth PUBLIC
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0)

target_link_libraries(SnakeOilSynth
    PRIVATE
        snakeoil_dsp
        SnakeOilData
        juce::juce_audio_utils
    PUBLIC
        juce::juce_recommended_config_flags
        juce::juce_recommended_warning_flags)
