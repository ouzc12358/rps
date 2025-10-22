#ifndef TERPS_EEPROM_COEFF_H
#define TERPS_EEPROM_COEFF_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    RPS_EEPROM_OK = 0,
    RPS_EEPROM_NO_DEVICE,
    RPS_EEPROM_IO_ERROR,
} rps_eeprom_status_t;

typedef struct {
    uint8_t device_address;
    uint16_t start_addr;
    size_t length;
    uint8_t bytes[512];
} rps_eeprom_t;

void rps_eeprom_init(uint gpio_data, uint32_t bitrate_bps);
rps_eeprom_status_t rps_eeprom_read(rps_eeprom_t *out, uint16_t addr, size_t len);

#ifdef __cplusplus
}
#endif

#endif
