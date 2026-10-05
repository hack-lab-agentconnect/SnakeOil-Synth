SAMPLE_RATE = 44100
BLOCK_SIZE = 256
MAX_VOICES = 12

WAVEFORMS = ("sine", "square", "saw", "triangle")

MODES = ("off", "fm", "am", "ring", "sync")
DEFAULT_MODE = "fm"
DEFAULT_MODE_DEPTH = 0.7

SEMITONE_MIN = -12.0
SEMITONE_MAX = 12.0
CENTS_MIN = -0.5
CENTS_MAX = 0.5

LPF_MODES = ("voice", "master")
DEFAULT_LPF_MODE = "voice"

FM_INDEX_MAX = 8.0
PITCH_BEND_RANGE = 2.0

DEFAULT_ADSR = {
    "attack": 0.006,
    "decay": 0.120,
    "sustain": 0.75,
    "release": 0.180,
}
