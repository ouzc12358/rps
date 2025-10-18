#ifndef TERPS_USB_CDC_H
#define TERPS_USB_CDC_H

#include <stdint.h>

typedef struct {
    uint32_t ts_ms;
    float frequency_hz;
    float tau_ms;
    float diode_uV;
    uint8_t adc_gain;
    uint8_t flags;
    float ppm_corr;
    uint8_t mode;
} terps_frame_t;

void usb_cdc_init(void);
void usb_cdc_send_frame(const terps_frame_t* frame);

#endif
