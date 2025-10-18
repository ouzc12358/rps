#include "ads1220.h"

void ads1220_init(const ads1220_config_t* config) {
    (void)config;
    // TODO: Configure SPI peripheral and ADS1220 registers.
}

bool ads1220_read_uV(int32_t* value) {
    (void)value;
    // TODO: Fetch averaged conversion result in microvolts.
    return false;
}
