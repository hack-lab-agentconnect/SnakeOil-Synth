import os
import sys

WINDOWS_HOSTAPI_PRIORITY = ("ASIO", "WASAPI", "WDM-KS")


def prepare_asio():
    if sys.platform.startswith("win") and "SD_ENABLE_ASIO" not in os.environ:
        os.environ["SD_ENABLE_ASIO"] = "1"


def _hostapi_index(sd, name):
    for i, api in enumerate(sd.query_hostapis()):
        if name.lower() in api["name"].lower():
            return i
    return None


def _api_name(sd, index):
    if index is None or index < 0:
        return None
    return sd.query_hostapis()[index]["name"]


def _extra_settings(sd, api_name, prefer_exclusive):
    name = (api_name or "").lower()
    if "asio" in name:
        factory = getattr(sd, "AsioSettings", None)
        if factory is not None:
            try:
                return factory(), False
            except Exception:
                return None, False
        return None, False
    if "wasapi" in name and prefer_exclusive:
        factory = getattr(sd, "WasapiSettings", None)
        if factory is not None:
            try:
                return factory(exclusive=True), True
            except Exception:
                return None, False
    return None, False


def _resolve_device_index(sd, device):
    if isinstance(device, int):
        return device
    if device is None:
        return None
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if device.lower() in dev["name"].lower() and dev["max_output_channels"] > 0:
            return i
    raise ValueError("no output device matching %r" % device)


def _first_output_in_api(sd, api_index):
    api = sd.query_hostapis()[api_index]
    default = api.get("default_output_device", -1)
    if default is not None and default >= 0:
        return default
    for di in api.get("devices", []):
        if sd.query_devices(di)["max_output_channels"] > 0:
            return di
    return None


def resolve_output(sd, hostapi=None, device=None, prefer_exclusive=True):
    if device is not None:
        index = _resolve_device_index(sd, device)
        dev = sd.query_devices(index)
        api_name = _api_name(sd, dev["hostapi"])
        extra, exclusive = _extra_settings(sd, api_name, prefer_exclusive)
        return {
            "device": index,
            "device_name": dev["name"],
            "hostapi": api_name,
            "extra_settings": extra,
            "exclusive": exclusive,
        }

    wanted = [hostapi] if hostapi else list(WINDOWS_HOSTAPI_PRIORITY)
    for name in wanted:
        idx = _hostapi_index(sd, name)
        if idx is None:
            continue
        dev_index = _first_output_in_api(sd, idx)
        if dev_index is None:
            continue
        api_name = _api_name(sd, idx)
        extra, exclusive = _extra_settings(sd, api_name, prefer_exclusive)
        dev = sd.query_devices(dev_index)
        return {
            "device": dev_index,
            "device_name": dev["name"],
            "hostapi": api_name,
            "extra_settings": extra,
            "exclusive": exclusive,
        }

    default_device = sd.default.device[1]
    if default_device is not None and default_device >= 0:
        dev = sd.query_devices(default_device)
        api_name = _api_name(sd, dev["hostapi"])
        return {
            "device": default_device,
            "device_name": dev["name"],
            "hostapi": api_name,
            "extra_settings": None,
            "exclusive": False,
        }
    return {
        "device": None,
        "device_name": "(system default)",
        "hostapi": None,
        "extra_settings": None,
        "exclusive": False,
    }


def default_samplerate(sd, device_index, fallback):
    try:
        if device_index is not None:
            sr = sd.query_devices(device_index).get("default_samplerate")
            if sr:
                return int(sr)
    except Exception:
        pass
    try:
        if sd.default.samplerate:
            return int(sd.default.samplerate)
    except Exception:
        pass
    return fallback


def format_device_listing(sd):
    lines = []
    hostapis = sd.query_hostapis()
    lines.append("Host APIs:")
    for i, api in enumerate(hostapis):
        lines.append("  [%d] %s" % (i, api["name"]))
    lines.append("Audio outputs:")
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if dev["max_output_channels"] <= 0:
            continue
        api = hostapis[dev["hostapi"]]["name"]
        lines.append("  [%d] %-40s  hostapi=%s  out=%d  default_sr=%s"
                     % (i, dev["name"], api, dev["max_output_channels"],
                        dev.get("default_samplerate")))
    return "\n".join(lines)
