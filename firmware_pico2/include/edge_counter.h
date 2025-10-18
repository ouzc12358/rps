#ifndef TERPS_EDGE_COUNTER_H
#define TERPS_EDGE_COUNTER_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint32_t pulses;
    uint64_t window_ticks;
} edge_counter_result_t;

void edge_counter_init(void);
void edge_counter_start(void);
bool edge_counter_read(edge_counter_result_t* result);

#endif
