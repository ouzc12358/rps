#include "pps_cal.h"

#include <math.h>
#include <string.h>

#include "hardware/gpio.h"
#include "pico/stdlib.h"
#include "terps_config.h"

#define PPS_EXPECTED_INTERVAL_US 1000000ULL
#define PPS_LOCK_THRESHOLD_PPM 5.0f
#define PPS_TIMEOUT_US 3000000ULL
#define PPS_ALPHA 0.2f

static uint32_t g_pps_gpio = 0;
static uint64_t g_last_edge_us = 0;
static uint64_t g_last_tick_us = 0;
static float g_correction_ppm = 0.0f;
static bool g_locked = false;
static uint32_t g_lock_counter = 0;

void pps_cal_init(uint32_t gpio)
{
    g_pps_gpio = gpio;
    g_last_edge_us = 0;
    g_last_tick_us = time_us_64();
    g_correction_ppm = 0.0f;
    g_locked = false;
    g_lock_counter = 0;

    if (gpio != 0 && gpio != 0xFFFFFFFFu) {
        gpio_init(gpio);
        gpio_set_dir(gpio, GPIO_IN);
        gpio_pull_down(gpio);
    }
}

void pps_cal_on_pps_edge(uint64_t timestamp_us)
{
    if (g_last_edge_us != 0) {
        uint64_t interval = timestamp_us - g_last_edge_us;
        float error_ppm = ((float)interval - (float)PPS_EXPECTED_INTERVAL_US) * 1e6f /
                          (float)PPS_EXPECTED_INTERVAL_US;
        g_correction_ppm = (1.0f - PPS_ALPHA) * g_correction_ppm - PPS_ALPHA * error_ppm;
        g_last_tick_us = timestamp_us;

        if (fabsf(error_ppm) < PPS_LOCK_THRESHOLD_PPM) {
            if (g_lock_counter < 5) {
                g_lock_counter++;
            }
        } else {
            if (g_lock_counter > 0) {
                g_lock_counter--;
            }
        }
        g_locked = g_lock_counter >= 3;
    }
    g_last_edge_us = timestamp_us;
}

void pps_cal_tick(void)
{
    uint64_t now = time_us_64();
    if (now - g_last_tick_us > PPS_TIMEOUT_US) {
        g_locked = false;
        g_correction_ppm = 0.0f;
        g_lock_counter = 0;
    }
}

float pps_cal_correction_ppm(void)
{
    return g_correction_ppm;
}

bool pps_cal_is_locked(void)
{
    return g_locked;
}

uint8_t pps_cal_status_flags(void)
{
    return g_locked ? TERPS_FLAG_PPS_LOCKED : 0x00u;
}
