#ifndef TERPS_EDGE_COUNTER_H
#define TERPS_EDGE_COUNTER_H

#include <stdbool.h>
#include <stdint.h>

#include "pico/util/queue.h"
#include "terps_config.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    terps_mode_t mode;
    uint32_t pulses;
    uint32_t raw_pulses;
    uint32_t min_interval_us;
    uint32_t tau_ms;
    uint64_t start_us;
    uint64_t end_us;
    int32_t f_hz_x1e4;
    float f_hz;
    uint32_t glitch_count;
    bool sync_active;
    bool timeout;
} freq_result_t;

void freq_counter_init(const terps_firmware_config_t *config);
void freq_counter_start_window(terps_mode_t mode, uint32_t tau_ms);
void freq_counter_stop(void);
queue_t *freq_counter_queue(void);
void freq_counter_on_sync(bool level_high);
void freq_counter_update_timebase_ppm(float ppm_correction);
float freq_counter_last_frequency(void);
void freq_counter_set_min_interval(float min_interval_frac);

#ifdef __cplusplus
}
#endif

#endif
