#ifndef TERPS_UNI_O_H
#define TERPS_UNI_O_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    UNIO_STATUS_OK = 0,
    UNIO_STATUS_NO_DEVICE,
    UNIO_STATUS_IO_ERROR,
} unio_status_t;

void unio_init(uint gpio_scio, uint32_t bitrate_bps);
bool unio_read(uint16_t addr, uint8_t *buf, size_t len);
unio_status_t unio_last_status(void);
uint8_t unio_last_device_address(void);
uint32_t unio_current_bitrate(void);

#ifdef __cplusplus
}
#endif

#endif
