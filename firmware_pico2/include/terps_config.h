#ifndef TERPS_CONFIG_H
#define TERPS_CONFIG_H

#include <stdbool.h>
#include <stdint.h>

#define TERPS_GPIO_UNUSED 0xFFFFFFFFu
#define TERPS_FLAG_SYNC_ACTIVE 0x01u
#define TERPS_FLAG_ADC_TIMEOUT 0x02u
#define TERPS_FLAG_PPS_LOCKED 0x04u
#define TERPS_FLAG_ADC_SATURATED 0x08u

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    TERPS_MODE_GATED = 0,
    TERPS_MODE_RECIP = 1,
} terps_mode_t;

typedef struct {
    terps_mode_t mode;
    uint32_t tau_ms;
    float min_interval_frac;
    float timebase_ppm;
    uint8_t adc_gain;
    uint16_t adc_rate_sps;
    bool adc_mains_reject;
    uint32_t avg_window;
    bool binary_frames;
    uint32_t queue_length;
    uint32_t sync_gpio;
    uint32_t pps_gpio;
    uint32_t freq_gpio;
    uint32_t spi_cs_gpio;
    uint32_t spi_drdy_gpio;
    uint32_t spi_sck_gpio;
    uint32_t spi_mosi_gpio;
    uint32_t spi_miso_gpio;
    uint32_t adc_timeout_ms;
    bool debug_deglitch_stats;
} terps_firmware_config_t;

extern const terps_firmware_config_t terps_default_config;

#ifdef __cplusplus
}
#endif

#endif
