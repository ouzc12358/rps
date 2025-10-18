#ifndef TERPS_ADS1220_H
#define TERPS_ADS1220_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint8_t gain;
    uint16_t rate_sps;
    bool mains_reject;
} ads1220_config_t;

void ads1220_init(const ads1220_config_t* config);
bool ads1220_read_uV(int32_t* value);

#endif
