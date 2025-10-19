#include <math.h>
#include <stdio.h>
#include <string.h>

#include "ads1220.h"
#include "config_default.h"
#include "edge_counter.h"
#include "hardware/gpio.h"
#include "hardware/irq.h"
#include "hardware/spi.h"
#include "pico/multicore.h"
#include "pico/stdlib.h"
#include "pps_cal.h"
#include "terps_config.h"
#include "tusb.h"
#include "usb_cdc.h"

#define FRAME_QUEUE_DEPTH 16

static terps_firmware_config_t g_config;
static queue_t *g_freq_queue;
static queue_t g_frame_queue;
static bool g_binary_mode = true;
static int32_t g_last_diode_uV = 0;

static void core1_main(void);
static void process_frequency_result(const freq_result_t *freq);

static void setup_adc(void)
{
    ads1220_hw_t hw = {
        .spi = spi0,
        .cs_gpio = g_config.spi_cs_gpio,
        .drdy_gpio = g_config.spi_drdy_gpio,
        .sck_gpio = g_config.spi_sck_gpio,
        .mosi_gpio = g_config.spi_mosi_gpio,
        .miso_gpio = g_config.spi_miso_gpio,
    };

    ads1220_config_t cfg = {
        .gain = g_config.adc_gain,
        .rate_sps = g_config.adc_rate_sps,
        .mains_reject = g_config.adc_mains_reject,
        .average_window = g_config.avg_window > 0 ? g_config.avg_window : 8,
    };

    ads1220_init(&hw, &cfg);
}

static void init_config(void)
{
    g_config = terps_default_config;
    if (g_config.queue_length == 0 || g_config.queue_length > 64) {
        g_config.queue_length = FRAME_QUEUE_DEPTH;
    }
    if (g_config.adc_timeout_ms == 0) {
        g_config.adc_timeout_ms = 200;
    }
    g_binary_mode = g_config.binary_frames;
}

static void init_usb(void)
{
    tud_init(0);
    usb_cdc_init(g_binary_mode ? TERPS_STREAM_BINARY : TERPS_STREAM_CSV);
}

static void feed_pps_correction(void)
{
    if (g_config.pps_gpio == TERPS_GPIO_UNUSED) {
        return;
    }
    pps_cal_tick();
    float ppm = pps_cal_correction_ppm();
    freq_counter_update_timebase_ppm(ppm);
}

int main()
{
    stdio_init_all();
    init_config();

    queue_init(&g_frame_queue, sizeof(terps_frame_t), g_config.queue_length);

    freq_counter_init(&g_config);
    g_freq_queue = freq_counter_queue();
    setup_adc();
    if (g_config.pps_gpio != TERPS_GPIO_UNUSED) {
        pps_cal_init(g_config.pps_gpio);
        gpio_set_irq_enabled(g_config.pps_gpio, GPIO_IRQ_EDGE_RISE, true);
    }
    init_usb();

    multicore_launch_core1(core1_main);

    sleep_ms(200);
    freq_counter_start_window(g_config.mode, g_config.tau_ms);

    while (true) {
        tud_task();
        usb_cdc_poll();

        terps_frame_t frame;
        if (queue_try_remove(&g_frame_queue, &frame)) {
            usb_cdc_send_frame(&frame);
        }

        feed_pps_correction();
    }
}

static void core1_main(void)
{
    while (true) {
        freq_result_t freq;
        queue_remove_blocking(g_freq_queue, &freq);
        process_frequency_result(&freq);
    }
}

static void process_frequency_result(const freq_result_t *freq)
{
    uint8_t frame_flags = 0;
    if (freq->sync_active) {
        frame_flags |= TERPS_FLAG_SYNC_ACTIVE;
    }

    uint8_t adc_flags = 0;
    int32_t v_uV = g_last_diode_uV;
    bool adc_ok = ads1220_read_uV(&v_uV, g_config.adc_timeout_ms, &adc_flags);
    if (adc_ok) {
        g_last_diode_uV = v_uV;
    }
    frame_flags |= adc_flags;
    frame_flags |= pps_cal_status_flags();

    if (!adc_ok && (adc_flags & TERPS_FLAG_ADC_TIMEOUT) && g_config.debug_deglitch_stats) {
        printf("[ads1220] DRDY timeout\n");
    }
    if (g_config.debug_deglitch_stats && freq->timeout) {
        printf("[freq] window timeout pulses=%u\n", freq->pulses);
    }

    terps_frame_t frame = {0};
    frame.ts_ms = (uint32_t)(freq->end_us / 1000ULL);
    frame.f_hz_x1e4 = freq->f_hz_x1e4;
    frame.tau_ms = (uint16_t)freq->tau_ms;
    frame.f_hz = freq->f_hz;
    frame.mode = (uint8_t)freq->mode;
    frame.diode_uV = g_last_diode_uV;
    frame.adc_gain = g_config.adc_gain;
    frame.flags = frame_flags;
    float ppm = pps_cal_correction_ppm();
    frame.ppm_corr = ppm;
    frame.ppm_corr_x1e2 = (int16_t)lroundf(ppm * 100.0f);

    if (g_config.debug_deglitch_stats && !g_binary_mode) {
        printf("# raw=%u kept=%u dropped=%u min_interval_us=%u\n",
               freq->raw_pulses,
               freq->pulses,
               freq->glitch_count,
               freq->min_interval_us);
    }

    if (!queue_try_add(&g_frame_queue, &frame)) {
        terps_frame_t dropped;
        queue_try_remove(&g_frame_queue, &dropped);
        queue_try_add(&g_frame_queue, &frame);
    }

    freq_counter_start_window(g_config.mode, g_config.tau_ms);
}
