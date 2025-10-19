#include "config_default.h"

const terps_firmware_config_t terps_default_config = {
    .mode = TERPS_MODE_RECIP,
    .tau_ms = 100,
    .min_interval_frac = 0.25f,
    .timebase_ppm = 0.0f,
    .adc_gain = 16,
    .adc_rate_sps = 20,
    .adc_mains_reject = true,
    .avg_window = 8,
    .binary_frames = false,
    .queue_length = 8,
    .sync_gpio = 3,
    .pps_gpio = 21,
    .freq_gpio = 2,
    .spi_cs_gpio = 17,
    .spi_drdy_gpio = 20,
    .spi_sck_gpio = 18,
    .spi_mosi_gpio = 19,
    .spi_miso_gpio = 16,
    .adc_timeout_ms = 200,
    .debug_deglitch_stats = false,
};
