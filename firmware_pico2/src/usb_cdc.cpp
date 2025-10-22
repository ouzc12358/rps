#include "usb_cdc.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "pico/stdlib.h"
#include "pico/time.h"
#include "tusb.h"

static terps_stream_mode_t g_mode = TERPS_STREAM_CSV;
static char g_cmd_buffer[128];
static size_t g_cmd_len = 0;


static bool ensure_write_capacity(uint32_t needed_bytes, uint32_t timeout_ms)
{
    uint32_t start = to_ms_since_boot(get_absolute_time());
    while (tud_cdc_connected()) {
        uint32_t available = tud_cdc_write_available();
        if (available >= needed_bytes) {
            return true;
        }
        tud_task();
        sleep_ms(1);
        if (to_ms_since_boot(get_absolute_time()) - start > timeout_ms) {
            return false;
        }
    }
    return false;
}
static uint16_t crc16_ccitt(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; ++i) {
        crc ^= (uint16_t)data[i] << 8;
        for (int b = 0; b < 8; ++b) {
            if (crc & 0x8000) {
                crc = (uint16_t)((crc << 1) ^ 0x1021);
            } else {
                crc <<= 1;
            }
        }
    }
    return crc;
}

void usb_cdc_init(terps_stream_mode_t mode)
{
    g_mode = mode;
}

void usb_cdc_set_mode(terps_stream_mode_t mode)
{
    g_mode = mode;
}

static bool cdc_wait_ready(void)
{
    uint32_t start = to_ms_since_boot(get_absolute_time());
    while (!tud_cdc_connected()) {
        tud_task();
        sleep_ms(5);
        if (to_ms_since_boot(get_absolute_time()) - start > 2000) {
            return false;
        }
    }
    return true;
}

bool usb_cdc_send_frame(const terps_frame_t *frame)
{
    if (frame == NULL) {
        return false;
    }
    if (!cdc_wait_ready()) {
        return false;
    }

    if (g_mode == TERPS_STREAM_BINARY) {
        uint8_t payload[19];
        size_t offset = 0;
        memcpy(&payload[offset], &frame->ts_ms, sizeof(frame->ts_ms));
        offset += sizeof(frame->ts_ms);
        memcpy(&payload[offset], &frame->f_hz_x1e4, sizeof(frame->f_hz_x1e4));
        offset += sizeof(frame->f_hz_x1e4);
        memcpy(&payload[offset], &frame->tau_ms, sizeof(frame->tau_ms));
        offset += sizeof(frame->tau_ms);
        memcpy(&payload[offset], &frame->diode_uV, sizeof(frame->diode_uV));
        offset += sizeof(frame->diode_uV);
        payload[offset++] = frame->adc_gain;
        payload[offset++] = frame->flags;
        memcpy(&payload[offset], &frame->ppm_corr_x1e2, sizeof(frame->ppm_corr_x1e2));
        offset += sizeof(frame->ppm_corr_x1e2);
        payload[offset++] = frame->mode;

        const uint8_t header[3] = {0x55, 0xAA, (uint8_t)offset};
        const uint16_t crc = crc16_ccitt(payload, offset);
        uint8_t crc_bytes[2];
        memcpy(crc_bytes, &crc, sizeof(crc));

        uint32_t total_len = sizeof(header) + (uint32_t)offset + sizeof(crc_bytes);
        if (!ensure_write_capacity(total_len, 100)) {
            return false;
        }
        tud_cdc_write(header, sizeof(header));
        tud_cdc_write(payload, offset);
        tud_cdc_write(crc_bytes, sizeof(crc_bytes));
        tud_cdc_write_flush();
        return true;
    }

    char line[160];
    const char *mode_str = frame->mode == 0 ? "GATED" : "RECIP";
    int written = snprintf(
        line,
        sizeof(line),
        "%lu,%.4f,%u,%.1f,%u,%u,%.2f,%s\r\n",
        (unsigned long)frame->ts_ms,
        frame->f_hz,
        frame->tau_ms,
        frame->diode_uV / 1.0f,
        frame->adc_gain,
        frame->flags,
        frame->ppm_corr,
        mode_str);

    if (written <= 0) {
        return false;
    }
    if (!ensure_write_capacity((uint32_t)written, 100)) {
        return false;
    }
    tud_cdc_write(line, (uint32_t)written);
    tud_cdc_write_flush();
    return true;
}

bool usb_cdc_read_line(char *buffer, size_t max_len)
{
    bool line_ready = false;
    while (tud_cdc_available()) {
        int ch = tud_cdc_read_char();
        if (ch < 0) {
            break;
        }
        char c = (char)ch;
        if (c == '\r') {
            continue;
        }
        if (c == '\n') {
            if (g_cmd_len > 0) {
                if (buffer != NULL && max_len > 0) {
                    size_t copy_len = g_cmd_len < (max_len - 1) ? g_cmd_len : (max_len - 1);
                    memcpy(buffer, g_cmd_buffer, copy_len);
                    buffer[copy_len] = '\0';
                }
                g_cmd_len = 0;
                line_ready = true;
            }
            continue;
        }
        if (g_cmd_len < sizeof(g_cmd_buffer) - 1) {
            g_cmd_buffer[g_cmd_len++] = c;
        } else {
            g_cmd_len = 0;
        }
    }
    return line_ready;
}

void usb_cdc_write_line(const char *text)
{
    if (text == NULL) {
        return;
    }
    size_t len = strlen(text);
    if (!ensure_write_capacity((uint32_t)len, 100)) {
        return;
    }
    tud_cdc_write(text, (uint32_t)len);
    tud_cdc_write_flush();
}

void usb_cdc_printf(const char *fmt, ...)
{
    char line[256];
    va_list args;
    va_start(args, fmt);
    int written = vsnprintf(line, sizeof(line), fmt, args);
    va_end(args);
    if (written <= 0) {
        return;
    }
    if ((size_t)written >= sizeof(line)) {
        written = sizeof(line) - 1;
        line[written] = '\0';
    }
    usb_cdc_write_line(line);
}

void usb_cdc_poll(void)
{
    tud_task();
}
