#include "edge_counter.h"

#include <math.h>
#include <string.h>

#include "config_default.h"
#include "hardware/gpio.h"
#include "hardware/irq.h"
#include "hardware/timer.h"
#include "pico/multicore.h"
#include "pico/stdlib.h"
#include "pps_cal.h"

#define MIN_RECIP_EDGES 64
#define MAX_QUEUE_DEPTH 32
#define DEFAULT_FREQ_ESTIMATE 30000.0f
#define MAX_FREQ_LIMIT 1000000.0f
#define MIN_FREQ_LIMIT 1.0f

static terps_firmware_config_t g_config;
static queue_t g_result_queue;
static critical_section_t g_lock;

typedef struct {
    terps_mode_t mode;
    bool active;
    bool window_open;
    bool sync_forced;
    uint32_t tau_ms;
    uint32_t pulses;
    uint32_t target_edges;
    uint32_t raw_edges;
    uint32_t glitch_count;
    uint32_t min_interval_us;
    float min_interval_frac;
    float freq_estimate_hz;
    float timebase_ppm;
    uint64_t start_us;
    uint64_t end_us;
    uint64_t last_edge_us;
    alarm_id_t gate_alarm;
} freq_state_t;

static freq_state_t g_state;

static inline float clamp_freq(float value)
{
    if (value < MIN_FREQ_LIMIT) {
        return MIN_FREQ_LIMIT;
    }
    if (value > MAX_FREQ_LIMIT) {
        return MAX_FREQ_LIMIT;
    }
    return value;
}

static void update_min_interval_locked(void)
{
    float freq = clamp_freq(g_state.freq_estimate_hz);
    float frac = g_state.min_interval_frac;
    if (frac <= 0.0f) {
        frac = 0.25f;
    }
    float base_period_us = 1e6f / freq;
    uint32_t min_interval = (uint32_t)(base_period_us * frac);
    if (min_interval < 1) {
        min_interval = 1;
    }
    g_state.min_interval_us = min_interval;
}

static void reset_state_locked(void)
{
    g_state.active = false;
    g_state.window_open = false;
    g_state.sync_forced = false;
    g_state.pulses = 0;
    g_state.raw_edges = 0;
    g_state.target_edges = 0;
    g_state.glitch_count = 0;
    g_state.start_us = 0;
    g_state.end_us = 0;
    g_state.last_edge_us = 0;
    if (g_state.gate_alarm >= 0) {
        cancel_alarm(g_state.gate_alarm);
        g_state.gate_alarm = -1;
    }
}

static void enqueue_result_locked(bool timeout_flag)
{
    if (!g_state.window_open) {
        reset_state_locked();
        return;
    }

    const uint64_t start_us = g_state.start_us;
    uint64_t end_us = g_state.end_us;
    if (end_us <= start_us) {
        end_us = start_us + 1;
    }
    const uint64_t elapsed_us = end_us - start_us;
    const uint32_t pulses = g_state.pulses;
    const uint32_t raw = g_state.raw_edges;

    if (pulses == 0 || elapsed_us == 0) {
        reset_state_locked();
        return;
    }

    float freq_hz = ((float)pulses * 1e6f) / (float)elapsed_us;
    freq_hz *= (1.0f + g_state.timebase_ppm * 1e-6f);
    g_state.freq_estimate_hz = freq_hz;
    update_min_interval_locked();

    freq_result_t result = {
        .mode = g_state.mode,
        .pulses = pulses,
        .raw_pulses = raw,
        .min_interval_us = g_state.min_interval_us,
        .tau_ms = (uint32_t)((float)elapsed_us / 1000.0f + 0.5f),
        .start_us = start_us,
        .end_us = end_us,
        .f_hz_x1e4 = (int32_t)llroundf(freq_hz * 1e4f),
        .f_hz = freq_hz,
        .glitch_count = g_state.glitch_count,
        .sync_active = g_state.sync_forced,
        .timeout = timeout_flag,
    };

    if (!queue_try_add(&g_result_queue, &result)) {
        freq_result_t dropped;
        queue_try_remove(&g_result_queue, &dropped);
        queue_try_add(&g_result_queue, &result);
    }
    reset_state_locked();
}

static void compute_target_edges_locked(uint32_t tau_ms)
{
    float freq = clamp_freq(g_state.freq_estimate_hz);
    float expected_edges = (freq * (float)tau_ms) / 1000.0f;
    uint32_t edges = (uint32_t)(expected_edges + 0.5f);
    if (edges < MIN_RECIP_EDGES) {
        edges = MIN_RECIP_EDGES;
    }
    g_state.target_edges = edges;
}

static int64_t gate_alarm_cb(alarm_id_t id, void *user_data)
{
    (void)id;
    (void)user_data;
    critical_section_enter_blocking(&g_lock);
    if (g_state.active && g_state.mode == TERPS_MODE_GATED) {
        g_state.end_us = time_us_64();
        enqueue_result_locked(true);
    }
    critical_section_exit(&g_lock);
    return 0;
}

static void start_window_locked(terps_mode_t mode, uint32_t tau_ms)
{
    g_state.mode = mode;
    g_state.tau_ms = tau_ms;
    g_state.pulses = 0;
    g_state.raw_edges = 0;
    g_state.glitch_count = 0;
    g_state.last_edge_us = 0;
    g_state.sync_forced = false;
    g_state.active = true;
    g_state.window_open = (mode == TERPS_MODE_GATED);
    g_state.start_us = g_state.window_open ? time_us_64() : 0;
    g_state.end_us = g_state.start_us;

    if (mode == TERPS_MODE_RECIP) {
        compute_target_edges_locked(tau_ms);
    } else {
        if (g_state.gate_alarm >= 0) {
            cancel_alarm(g_state.gate_alarm);
        }
        g_state.gate_alarm = add_alarm_in_ms((int64_t)tau_ms, gate_alarm_cb, NULL, true);
    }
}

static void handle_edge_locked(uint64_t timestamp_us)
{
    if (!g_state.active) {
        return;
    }

    g_state.raw_edges++;
    if (g_state.last_edge_us != 0) {
        uint64_t delta = timestamp_us - g_state.last_edge_us;
        if (delta < g_state.min_interval_us) {
            g_state.glitch_count++;
            return;
        }
    }

    g_state.last_edge_us = timestamp_us;
    if (!g_state.window_open) {
        g_state.window_open = true;
        g_state.start_us = timestamp_us;
    }
    g_state.end_us = timestamp_us;
    g_state.pulses++;

    if (g_state.mode == TERPS_MODE_RECIP && g_state.pulses >= g_state.target_edges) {
        enqueue_result_locked(false);
    }
}

static void handle_sync_locked(bool level_high)
{
    if (level_high) {
        g_state.sync_forced = true;
        start_window_locked(g_state.mode, g_state.tau_ms);
    } else {
        if (!g_state.active) {
            return;
        }
        g_state.end_us = time_us_64();
        enqueue_result_locked(false);
    }
}

static void gpio_callback(uint gpio, uint32_t events)
{
    uint64_t now = time_us_64();
    critical_section_enter_blocking(&g_lock);

    if (gpio == g_config.freq_gpio && (events & GPIO_IRQ_EDGE_RISE)) {
        handle_edge_locked(now);
    } else if (gpio == g_config.sync_gpio && (events & (GPIO_IRQ_EDGE_RISE | GPIO_IRQ_EDGE_FALL))) {
        bool high = (events & GPIO_IRQ_EDGE_RISE) != 0;
        handle_sync_locked(high);
    } else if (gpio == g_config.pps_gpio && (events & GPIO_IRQ_EDGE_RISE)) {
        pps_cal_on_pps_edge(now);
    }

    critical_section_exit(&g_lock);
}

void freq_counter_init(const terps_firmware_config_t *config)
{
    if (config == NULL) {
        config = &terps_default_config;
    }
    g_config = *config;

    uint32_t depth = config->queue_length;
    if (depth == 0 || depth > MAX_QUEUE_DEPTH) {
        depth = 8;
    }
    queue_init(&g_result_queue, sizeof(freq_result_t), depth);

    memset(&g_state, 0, sizeof(g_state));
    g_state.freq_estimate_hz = DEFAULT_FREQ_ESTIMATE;
    g_state.min_interval_frac = config->min_interval_frac > 0.0f ? config->min_interval_frac : 0.25f;
    g_state.timebase_ppm = config->timebase_ppm;
    g_state.tau_ms = config->tau_ms;
    g_state.gate_alarm = -1;
    update_min_interval_locked();

    critical_section_init(&g_lock);

    gpio_init(config->freq_gpio);
    gpio_set_dir(config->freq_gpio, GPIO_IN);
    gpio_pull_down(config->freq_gpio);

    gpio_set_irq_enabled_with_callback(config->freq_gpio, GPIO_IRQ_EDGE_RISE, true, gpio_callback);

    if (config->sync_gpio != TERPS_GPIO_UNUSED) {
        gpio_init(config->sync_gpio);
        gpio_set_dir(config->sync_gpio, GPIO_IN);
        gpio_pull_down(config->sync_gpio);
        gpio_set_irq_enabled(config->sync_gpio, GPIO_IRQ_EDGE_RISE | GPIO_IRQ_EDGE_FALL, true);
    }

    if (config->pps_gpio != TERPS_GPIO_UNUSED) {
        gpio_init(config->pps_gpio);
        gpio_set_dir(config->pps_gpio, GPIO_IN);
        gpio_pull_down(config->pps_gpio);
        gpio_set_irq_enabled(config->pps_gpio, GPIO_IRQ_EDGE_RISE, true);
        pps_cal_init(config->pps_gpio);
    }
}

void freq_counter_start_window(terps_mode_t mode, uint32_t tau_ms)
{
    if (tau_ms == 0) {
        tau_ms = g_config.tau_ms;
    }

    critical_section_enter_blocking(&g_lock);
    g_state.min_interval_frac = g_config.min_interval_frac;
    g_state.timebase_ppm = g_config.timebase_ppm;
    start_window_locked(mode, tau_ms);
    critical_section_exit(&g_lock);
}

void freq_counter_stop(void)
{
    critical_section_enter_blocking(&g_lock);
    enqueue_result_locked(true);
    reset_state_locked();
    critical_section_exit(&g_lock);
}

queue_t *freq_counter_queue(void)
{
    return &g_result_queue;
}

void freq_counter_on_sync(bool level_high)
{
    critical_section_enter_blocking(&g_lock);
    handle_sync_locked(level_high);
    critical_section_exit(&g_lock);
}

void freq_counter_update_timebase_ppm(float ppm_correction)
{
    critical_section_enter_blocking(&g_lock);
    g_state.timebase_ppm = ppm_correction;
    critical_section_exit(&g_lock);
}

float freq_counter_last_frequency(void)
{
    critical_section_enter_blocking(&g_lock);
    float value = g_state.freq_estimate_hz;
    critical_section_exit(&g_lock);
    return value;
}

void freq_counter_set_min_interval(float min_interval_frac)
{
    critical_section_enter_blocking(&g_lock);
    g_state.min_interval_frac = min_interval_frac;
    update_min_interval_locked();
    critical_section_exit(&g_lock);
}
