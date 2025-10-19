#ifndef TERPS_USB_CDC_H
#define TERPS_USB_CDC_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint32_t ts_ms;
    int32_t f_hz_x1e4;
    uint16_t tau_ms;
    int32_t diode_uV;
    uint8_t adc_gain;
    uint8_t flags;
    int16_t ppm_corr_x1e2;
    uint8_t mode;
    float f_hz;
    float ppm_corr;
} terps_frame_t;

typedef enum {
    TERPS_STREAM_BINARY = 0,
    TERPS_STREAM_CSV = 1,
} terps_stream_mode_t;

void usb_cdc_init(terps_stream_mode_t mode);
void usb_cdc_set_mode(terps_stream_mode_t mode);
bool usb_cdc_send_frame(const terps_frame_t *frame);
void usb_cdc_poll(void);

#ifdef __cplusplus
}
#endif

#endif
