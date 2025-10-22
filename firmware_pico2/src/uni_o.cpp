#include "uni_o.h"

#include "hardware/gpio.h"
#include "pico/stdlib.h"
#include "pico/time.h"

namespace {

constexpr uint32_t UNIO_T_STANDBY_US = 600;
constexpr uint32_t UNIO_T_HDR_US = 10;
constexpr uint32_t UNIO_MIN_HALF_US = 5;
constexpr uint32_t UNIO_MAX_HALF_US = 200;
constexpr uint8_t UNIO_START_HEADER = 0x55;
constexpr uint8_t UNIO_CMD_READ = 0x03;

enum class BitReadResult {
    Zero,
    One,
    Idle,
    Error,
};

static uint g_gpio = 0;
static bool g_initialized = false;
static uint32_t g_half_bit_us = 20;
static uint32_t g_bitrate_bps = 0;
static uint8_t g_last_device_addr = 0;
static unio_status_t g_last_status = UNIO_STATUS_NO_DEVICE;

static inline void drive_high()
{
    gpio_put(g_gpio, 1);
    gpio_set_dir(g_gpio, true);
}

static inline void drive_low()
{
    gpio_put(g_gpio, 0);
    gpio_set_dir(g_gpio, true);
}

static inline void release_line()
{
    gpio_set_dir(g_gpio, false);
}

static inline bool sample_line()
{
    return gpio_get(g_gpio);
}

static inline void half_delay()
{
    busy_wait_us_32(g_half_bit_us);
}

static void standby_pulse()
{
    if (!g_initialized) {
        return;
    }
    release_line();
    busy_wait_us_32(UNIO_T_STANDBY_US);
}

static void tx_bit(bool bit, bool release_after)
{
    if (bit) {
        drive_high();
        half_delay();
        drive_low();
        half_delay();
    } else {
        drive_low();
        half_delay();
        drive_high();
        half_delay();
    }
    if (release_after) {
        release_line();
    }
}

static void tx_byte(uint8_t value)
{
    for (int bit = 7; bit >= 0; --bit) {
        tx_bit(((value >> bit) & 0x01u) != 0, false);
    }
    release_line();
}

static BitReadResult rx_bit(bool& value_out)
{
    release_line();
    half_delay();
    bool first = sample_line();
    half_delay();
    bool second = sample_line();

    if (!first && second) {
        value_out = false;
        return BitReadResult::Zero;
    }
    if (first && !second) {
        value_out = true;
        return BitReadResult::One;
    }
    if (first && second) {
        return BitReadResult::Idle;
    }
    return BitReadResult::Error;
}

static bool expect_mak_from_slave()
{
    bool value = false;
    BitReadResult res = rx_bit(value);
    if (res == BitReadResult::Idle) {
        g_last_status = UNIO_STATUS_NO_DEVICE;
        return false;
    }
    if (res != BitReadResult::One) {
        g_last_status = UNIO_STATUS_IO_ERROR;
        return false;
    }
    tx_bit(false, true);  // SAK = 0
    return true;
}

static bool send_mak_to_slave(bool more)
{
    tx_bit(more, true);
    bool ack_value = false;
    BitReadResult res = rx_bit(ack_value);
    if (res == BitReadResult::Idle) {
        g_last_status = UNIO_STATUS_NO_DEVICE;
        return false;
    }
    if (res != BitReadResult::Zero || ack_value) {
        g_last_status = UNIO_STATUS_IO_ERROR;
        return false;
    }
    return true;
}

static bool rx_byte(uint8_t& value_out)
{
    uint8_t value = 0;
    for (int bit = 7; bit >= 0; --bit) {
        bool bit_value = false;
        BitReadResult res = rx_bit(bit_value);
        if (res == BitReadResult::Idle) {
            g_last_status = UNIO_STATUS_NO_DEVICE;
            return false;
        }
        if (res == BitReadResult::Error) {
            g_last_status = UNIO_STATUS_IO_ERROR;
            return false;
        }
        if (bit_value) {
            value |= (uint8_t)(1u << bit);
        }
    }
    value_out = value;
    return true;
}

static bool start_header()
{
    standby_pulse();
    drive_low();
    busy_wait_us_32(UNIO_T_HDR_US);
    tx_byte(UNIO_START_HEADER);
    return true;
}

static bool execute_read(uint8_t device_addr, uint16_t addr, uint8_t* buf, size_t len)
{
    if (!start_header()) {
        g_last_status = UNIO_STATUS_IO_ERROR;
        return false;
    }

    tx_byte(device_addr);
    if (!expect_mak_from_slave()) {
        return false;
    }

    tx_byte(UNIO_CMD_READ);
    if (!expect_mak_from_slave()) {
        return false;
    }

    tx_byte((uint8_t)((addr >> 8) & 0xFFu));
    if (!expect_mak_from_slave()) {
        return false;
    }

    tx_byte((uint8_t)(addr & 0xFFu));
    if (!expect_mak_from_slave()) {
        return false;
    }

    for (size_t i = 0; i < len; ++i) {
        uint8_t value = 0;
        if (!rx_byte(value)) {
            return false;
        }
        buf[i] = value;
        bool more = (i + 1) < len;
        if (!send_mak_to_slave(more)) {
            return false;
        }
    }

    standby_pulse();
    g_last_status = UNIO_STATUS_OK;
    g_last_device_addr = device_addr;
    return true;
}

static uint32_t compute_half_period(uint32_t bitrate_bps)
{
    if (bitrate_bps == 0) {
        bitrate_bps = 20000;
    }
    uint32_t period_us = (uint32_t)((1000000u + bitrate_bps / 2) / bitrate_bps);
    uint32_t half_us = period_us / 2;
    if (half_us < UNIO_MIN_HALF_US) {
        half_us = UNIO_MIN_HALF_US;
    }
    if (half_us > UNIO_MAX_HALF_US) {
        half_us = UNIO_MAX_HALF_US;
    }
    if (half_us == 0) {
        half_us = UNIO_MIN_HALF_US;
    }
    return half_us;
}

}  // namespace

extern "C" {

void unio_init(uint gpio_scio, uint32_t bitrate_bps)
{
    g_gpio = gpio_scio;
    g_bitrate_bps = (bitrate_bps == 0) ? 20000 : bitrate_bps;
    g_half_bit_us = compute_half_period(g_bitrate_bps);
    g_last_device_addr = 0;
    g_last_status = UNIO_STATUS_NO_DEVICE;
    g_initialized = false;

    if (gpio_scio == 0xFFFFFFFFu) {
        return;
    }

    gpio_init(gpio_scio);
    gpio_pull_up(gpio_scio);
    gpio_put(gpio_scio, 1);
    release_line();
    g_initialized = true;
}

bool unio_read(uint16_t addr, uint8_t* buf, size_t len)
{
    if (!g_initialized || buf == nullptr || len == 0) {
        g_last_status = g_initialized ? UNIO_STATUS_IO_ERROR : UNIO_STATUS_NO_DEVICE;
        return false;
    }
    if (len > 512) {
        len = 512;
    }

    const uint8_t start_addr = 0xA0;
    const uint8_t end_addr = 0xAE;
    for (uint8_t dev = start_addr; dev <= end_addr; dev = (uint8_t)(dev + 2)) {
        if (execute_read(dev, addr, buf, len)) {
            return true;
        }
        if (g_last_status == UNIO_STATUS_IO_ERROR) {
            standby_pulse();
            return false;
        }
        standby_pulse();
    }
    g_last_status = UNIO_STATUS_NO_DEVICE;
    return false;
}

unio_status_t unio_last_status(void)
{
    return g_last_status;
}

uint8_t unio_last_device_address(void)
{
    return g_last_device_addr;
}

uint32_t unio_current_bitrate(void)
{
    return g_bitrate_bps;
}

}  // extern "C"
