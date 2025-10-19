#ifndef TERPS_ADS1220_H
#define TERPS_ADS1220_H

#include <stdbool.h>
#include <stdint.h>

#include "hardware/spi.h"

typedef struct {
    spi_inst_t *spi;
    uint cs_gpio;
    uint drdy_gpio;
    uint sck_gpio;
    uint mosi_gpio;
    uint miso_gpio;
} ads1220_hw_t;

typedef struct {
    uint8_t gain;
    uint16_t rate_sps;
    bool mains_reject;
    uint32_t average_window;
} ads1220_config_t;

void ads1220_init(const ads1220_hw_t *hw, const ads1220_config_t *config);
void ads1220_apply_config(const ads1220_config_t *config);
bool ads1220_read_uV(int32_t *value_uV, uint32_t timeout_ms, uint8_t *flags);
void ads1220_sleep(void);
void ads1220_wake(void);

#endif
