SAMPLE_RATE = 44100
BLOCK_SIZE = 256
MAX_VOICES = 12

MIN_DUTY = 0.02
DEFAULT_DUTY = 0.5
DEFAULT_PWM = 0.0
LAYER_GAIN = 0.6

MODES = ("off", "fm", "am", "ring", "sync")
DEFAULT_MODE = "fm"
DEFAULT_MODE_DEPTH = 0.7

SEMITONE_MIN = -12.0
SEMITONE_MAX = 12.0
CENTS_MIN = -0.5
CENTS_MAX = 0.5

LPF_MODES = ("voice", "master")
DEFAULT_LPF_MODE = "voice"
DEFAULT_LPF_CUTOFF = 2000.0

FM_INDEX_MAX = 8.0
PITCH_BEND_RANGE = 2.0

DEFAULT_ADSR = {
    "attack": 0.006,
    "decay": 0.120,
    "sustain": 0.75,
    "release": 0.180,
}

AMP_TIME_MIN = 0.001
AMP_ATTACK_MAX = 5.0
AMP_DECAY_MAX = 5.0
AMP_RELEASE_MAX = 10.0

FIXED_VELOCITY = 100 / 127
FLT_ENV_OCTAVES = 6.0
FLT_VEL_OCTAVES = 6.0

DEFAULT_FLT_ENV = {
    "attack": 0.005,
    "decay": 0.3,
    "sustain": 0.3,
    "release": 0.3,
}
