#include "usb_cdc.h"

void usb_cdc_init(void) {
    // TODO: Initialize TinyUSB CDC and queue structures.
}

void usb_cdc_send_frame(const terps_frame_t* frame) {
    (void)frame;
    // TODO: Serialize as CSV or binary and push to USB FIFO.
}
