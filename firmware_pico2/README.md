# Pico 2 Firmware Scaffold

This directory captures the Raspberry Pi Pico 2 firmware layout for the TERPS RPS synchronous acquisition system. It uses the Pico SDK with TinyUSB enabled.

## Components

- `src/main.cpp` – entry point that boots dual-core scheduling, configures PIO edge capture, and orchestrates USB CDC transfers.
- `src/edge_counter.cpp` – reciprocal frequency counter using PIO + IRQ with digital debouncing.
- `src/ads1220.cpp` – SPI driver for ADS1220/ADS1120/ADS124S06 family with register presets.
- `src/usb_cdc.cpp` – TinyUSB stream wrapper that emits CSV or binary frames.
- `src/pps_cal.cpp` – optional 1PPS disciplining loop that updates the ppm correction field.
- `config_default.json` – firmware-level defaults mirrored by the host configuration.

Each module is currently a stub; fill in device-specific code during firmware bring-up. Keep public headers under `include/` and update the CMake target lists accordingly.

## Build

```bash
mkdir -p build && cd build
cmake .. -DPICO_SDK_PATH=/path/to/pico-sdk
cmake --build .
```

Use `-DTERPS_BINARY=ON` to default the firmware to binary frame streaming; otherwise CSV is emitted.
