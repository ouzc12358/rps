#include "ads1220.h"

#include <math.h>
#include <string.h>

#include "hardware/gpio.h"
#include "hardware/spi.h"
#include "pico/stdlib.h"
#include "pico/time.h"
#include "terps_config.h"

#define ADS1220_CMD_RESET 0x06
#define ADS1220_CMD_START 0x08
#define ADS1220_CMD_RDATA 0x10
#define ADS1220_CMD_WREG 0x40
#define ADS1220_CMD_RREG 0x20
#define ADS1220_CMD_PWRDOWN 0x02
#define ADS1220_CMD_WAKEUP 0x00

#define ADS1220_VREF_UV 2048000LL
#define ADS1220_FULL_SCALE 8388608LL

static ads1220_hw_t g_hw;
static ads1220_config_t g_cfg;
static int32_t g_filtered_uV = 0;
static bool g_initialized = false;

static inline void cs_select(void)
{
    gpio_put(g_hw.cs_gpio, 0);
}

static inline void cs_deselect(void)
{
    gpio_put(g_hw.cs_gpio, 1);
}

static void write_command(uint8_t cmd)
{
    cs_select();
    spi_write_blocking(g_hw.spi, &cmd, 1);
    cs_deselect();
}

static void write_registers(uint8_t start, const uint8_t *data, size_t len)
{
    uint8_t cmd = ADS1220_CMD_WREG | ((start & 0x03) << 2) | ((len - 1) & 0x03);
    cs_select();
    spi_write_blocking(g_hw.spi, &cmd, 1);
    spi_write_blocking(g_hw.spi, data, len);
    cs_deselect();
}

static uint8_t gain_to_bits(uint8_t gain)
{
    switch (gain) {
        case 1:
            return 0x00;
        case 2:
            return 0x01;
        case 4:
            return 0x02;
        case 8:
            return 0x03;
        case 16:
            return 0x04;
        case 32:
            return 0x05;
        case 64:
            return 0x06;
        case 128:
            return 0x07;
        default:
            return 0x04;  // default to 16x
    }
}

static uint8_t rate_to_bits(uint16_t rate)
{
    if (rate <= 20) {
        return 0x00;
    }
    if (rate <= 45) {
        return 0x01;
    }
    if (rate <= 90) {
        return 0x02;
    }
    if (rate <= 175) {
        return 0x03;
    }
    if (rate <= 330) {
        return 0x04;
    }
    if (rate <= 600) {
        return 0x05;
    }
    if (rate <= 1000) {
        return 0x06;
    }
    return 0x07;
}

static void apply_registers(void)
{
    uint8_t reg0 = (0x00 << 4) | (gain_to_bits(g_cfg.gain) << 1);
    if (g_cfg.gain <= 1) {
        reg0 |= 0x01;  // disable PGA when gain 1
    }

    uint8_t reg1 = 0x04;  // continuous conversion
    reg1 |= (rate_to_bits(g_cfg.rate_sps) << 5);

    uint8_t reg2 = 0x10;  // internal reference, default settings
    if (g_cfg.mains_reject) {
        reg2 |= 0x08;
    }

    uint8_t reg3 = 0x00;  // IDACs off

    uint8_t regs[4] = {reg0, reg1, reg2, reg3};
    write_registers(0, regs, 4);
}

static int32_t read_raw_code(void)
{
    uint8_t cmd = ADS1220_CMD_RDATA;
    uint8_t rx[3] = {0};

    cs_select();
    spi_write_blocking(g_hw.spi, &cmd, 1);
    spi_read_blocking(g_hw.spi, 0xFF, rx, 3);
    cs_deselect();

    int32_t raw = ((int32_t)rx[0] << 16) | ((int32_t)rx[1] << 8) | (int32_t)rx[2];
    if (raw & 0x800000) {
        raw |= 0xFF000000;
    }
    return raw;
}

void ads1220_init(const ads1220_hw_t *hw, const ads1220_config_t *config)
{
    g_hw = *hw;
    g_cfg = *config;

    spi_init(g_hw.spi, 1 * 1000 * 1000);
    gpio_set_function(g_hw.sck_gpio, GPIO_FUNC_SPI);
    gpio_set_function(g_hw.mosi_gpio, GPIO_FUNC_SPI);
    gpio_set_function(g_hw.miso_gpio, GPIO_FUNC_SPI);

    gpio_init(g_hw.cs_gpio);
    gpio_set_dir(g_hw.cs_gpio, GPIO_OUT);
    gpio_put(g_hw.cs_gpio, 1);

    gpio_init(g_hw.drdy_gpio);
    gpio_set_dir(g_hw.drdy_gpio, GPIO_IN);
    gpio_pull_up(g_hw.drdy_gpio);

    sleep_ms(2);
    write_command(ADS1220_CMD_RESET);
    sleep_ms(2);

    apply_registers();
    write_command(ADS1220_CMD_START);
    g_filtered_uV = 0;
    g_initialized = true;
}

void ads1220_apply_config(const ads1220_config_t *config)
{
    g_cfg = *config;
    if (!g_initialized) {
        return;
    }
    apply_registers();
    g_filtered_uV = 0;
}

static bool ads1220_is_data_ready(void)
{
    return gpio_get(g_hw.drdy_gpio) == 0;
}

bool ads1220_read_uV(int32_t *value_uV, uint32_t timeout_ms, uint8_t *flags)
{
    if (!g_initialized || value_uV == NULL) {
        return false;
    }

    if (flags != NULL) {
        *flags &= ~(TERPS_FLAG_ADC_TIMEOUT | TERPS_FLAG_ADC_SATURATED);
    }

    uint32_t effective_timeout = timeout_ms > 0 ? timeout_ms : 200;
    absolute_time_t deadline = make_timeout_time_ms(effective_timeout);
    while (!ads1220_is_data_ready()) {
        if (time_reached(deadline)) {
            if (flags != NULL) {
                *flags |= TERPS_FLAG_ADC_TIMEOUT;
            }
            return false;
        }
        tight_loop_contents();
    }

    int32_t raw = read_raw_code();
    int64_t gain = g_cfg.gain;
    if (gain <= 0) {
        gain = 1;
    }
    int64_t microvolts = (int64_t)raw * ADS1220_VREF_UV;
    microvolts /= (gain * ADS1220_FULL_SCALE);

    if (flags != NULL) {
        if (raw >= 0x7FFFF0 || raw <= -0x7FFFF0) {
            *flags |= TERPS_FLAG_ADC_SATURATED;
        }
    }

    if (g_cfg.average_window > 1) {
        if (g_filtered_uV == 0) {
            g_filtered_uV = (int32_t)microvolts;
        } else {
            g_filtered_uV += (int32_t)((microvolts - g_filtered_uV) / (int32_t)g_cfg.average_window);
        }
        *value_uV = g_filtered_uV;
    } else {
        *value_uV = (int32_t)microvolts;
    }
    return true;
}

void ads1220_sleep(void)
{
    if (!g_initialized) {
        return;
    }
    write_command(ADS1220_CMD_PWRDOWN);
}

void ads1220_wake(void)
{
    if (!g_initialized) {
        return;
    }
    write_command(ADS1220_CMD_WAKEUP);
    sleep_us(50);
    write_command(ADS1220_CMD_START);
}
