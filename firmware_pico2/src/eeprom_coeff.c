#include "eeprom_coeff.h"

#include <stddef.h>

#include "terps_config.h"
#include "uni_o.h"

static bool g_unio_enabled = false;

void rps_eeprom_init(uint gpio_data, uint32_t bitrate_bps)
{
    g_unio_enabled = (gpio_data != TERPS_GPIO_UNUSED);
    unio_init(gpio_data, bitrate_bps);
}

rps_eeprom_status_t rps_eeprom_read(rps_eeprom_t *out, uint16_t addr, size_t len)
{
    if (out == NULL || len == 0) {
        return RPS_EEPROM_IO_ERROR;
    }
    if (!g_unio_enabled) {
        return RPS_EEPROM_NO_DEVICE;
    }
    if (len > sizeof(out->bytes)) {
        len = sizeof(out->bytes);
    }

    if (!unio_read(addr, out->bytes, len)) {
        switch (unio_last_status()) {
            case UNIO_STATUS_NO_DEVICE:
                return RPS_EEPROM_NO_DEVICE;
            case UNIO_STATUS_IO_ERROR:
            default:
                return RPS_EEPROM_IO_ERROR;
        }
    }
    out->device_address = unio_last_device_address();
    out->start_addr = addr;
    out->length = len;
    return RPS_EEPROM_OK;
}
