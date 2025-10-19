#ifndef TERPS_PPS_CAL_H
#define TERPS_PPS_CAL_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void pps_cal_init(uint32_t gpio);
void pps_cal_on_pps_edge(uint64_t timestamp_us);
void pps_cal_tick(void);
float pps_cal_correction_ppm(void);
bool pps_cal_is_locked(void);
uint8_t pps_cal_status_flags(void);

#ifdef __cplusplus
}
#endif

#endif
