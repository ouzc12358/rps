# TERPS Host Application

The TERPS host utilities run on Raspberry Pi 3B+/5 and ingest synchronized frequency + diode voltage frames emitted by the Raspberry Pi Pico 2 firmware. This guide covers setup, protocol details, runtime presets, wiring, and configuration fields.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev,plot,terps]
terps-host run --port /dev/ttyACM0 --config host_pi/config.json --set output_csv=run.csv
```

Start with CSV output for readability; switch to `--set frame_format=binary` once the firmware
path is validated. Use `--port -` to replay synthetic frames from stdin during bench testing.

## Setup

1. Create a virtual environment and install dependencies (include the TERPS extra for `pyserial`):

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .[dev,plot,terps]
   ```

2. Connect the Pico 2 to the Pi over USB. Once the firmware is running the device appears as `/dev/ttyACM*`.

3. Edit `host_pi/config.json` to match your window length, ADC plan, polynomial coefficients, and host runtime preferences.

## Running

Invoke the CLI registered as `terps-host`:

```bash
terps-host run --port /dev/ttyACM0 --config host_pi/config.json --set output_csv=/home/pi/data/run.csv
```

- CSV streaming is the default; switch to binary parsing with `--set frame_format=binary`.
- Override individual coefficients at runtime (`--set sensor_poly.Y=600000.0`, `--set adc.gain=32`, etc.).
- Use `--port -` to pipe pre-recorded frames from stdin during bench testing.
- The reader thread auto-reconnects on `SerialException` with exponential backoff (
  configurable via `host.reconnect_initial_sec` / `host.reconnect_max_sec`).
- Runner logs aggregate statistics every `host.stats_log_interval` 秒（累计帧数、CRC/长度错误、丢帧、重连次数）。

Processed samples (timestamp, frequency, gate length, diode µV, pressure, flags) are persisted to the configured CSV path. `%FS` is defined identically to the analysis tooling: `max(output) - min(output)` over the dataset.

## Protocol & Units

| Field             | Type    | Unit           | Notes                                   |
|-------------------|---------|----------------|-----------------------------------------|
| `ts_ms`           | `uint32`| ms             | Millisecond timestamp relative to Pico. |
| `f_hz_x1e4`       | `int32` | Hz × 10⁴       | Reciprocal or gated frequency reading. |
| `tau_ms`          | `uint16`| ms             | Actual window length applied.           |
| `v_uV`            | `int32` | µV             | Diode voltage referred to sensor_poly.Y |
| `adc_gain`        | `uint8` | -              | ADS1220 PGA setting.                    |
| `flags`           | `uint8` | bitfield       | bit0=SYNC, bit1=ADC DRDY timeout, bit2=PPS lock, bit3=ADC saturation. |
| `ppm_corr_x1e2`   | `int16` | ppm × 10²      | Timebase correction (+/-).              |
| `mode`            | `uint8` | enum           | 0=GATED, 1=RECIP.                       |

Binary frame layout:

```
0x55 0xAA | len(u8=19) | <I i H i B B h B> | CRC16-CCITT (0x1021, init 0xFFFF, little-endian)
```

Example frame (ts=123456 ms, f=30000.1234 Hz, τ=100 ms, v=600120 µV, gain=16, flags=SYNC, ppm=0.25, mode=RECIP):

```
55 AA 13 40 E2 01 00 D2 A7 E1 11 64 00 38 28 09 00 10 01 19 00 01 1C 9C
```

Byte map (little-endian):

- 0–1: header `0x55AA`
- 2: payload length (=19)
- 3–6: `ts_ms` (`uint32`, milliseconds)
- 7–10: `f_hz_x1e4` (`int32`, Hz × 10⁴)
- 11–12: `tau_ms` (`uint16`, milliseconds)
- 13–16: `v_uV` (`int32`, microvolts)
- 17: `adc_gain` (`uint8`)
- 18: `flags` (`uint8`, bit0=SYNC, bit1=ADC DRDY timeout, bit2=PPS lock, bit3=ADC saturation)
- 19–20: `ppm_corr_x1e2` (`int16`, ppm × 100)
- 21: `mode` (`uint8`, 0=GATED, 1=RECIP)
- 22–23: CRC16-CCITT (`uint16`, little-endian)

CSV mode mirrors the same fields using the header:

```
ts_ms,f_hz,tau_ms,v_uV,adc_gain,flags,ppm_corr,mode
```

> `v_uV` 与 `sensor_poly.Y` 均为微伏 (µV)；固件输出与上位机多项式计算必须保持该单位一致。

## Acquisition Presets

| 档位        | 推荐模式 | τ 窗口 (ms) | ADS1220 PGA | 采样率 (SPS) | 时基            | 1PPS | 目标精度 |
|-------------|---------|-------------|-------------|--------------|-----------------|------|----------|
| 0.02% FS    | RECIP   | 50–100      | ×16         | 20–25        | 板载晶体 / TCXO | 可选 | 工程验收 |
| 0.01% FS    | RECIP   | 300–1000    | ×32         | 20–40        | TCXO + 周期校准 | 建议 | 高稳测量 |
| 0.003% FS   | RECIP   | 1000–5000   | ×32         | 20–50        | OCXO / GPSDO    | 必要 | 计量级   |

## Wiring Topologies

**拓扑 A（ADS1220 连接至 Pico 2）**

- Frequency input → Pico2 `GP2` (PIO edge counter) with SN74LVC1G17 or comparator front-end.
- ADS1220 SPI (Pico2): `SCK GP18`, `MOSI GP19`, `MISO GP16`, `CS GP17`, `DRDY GP20`.
- Optional SYNC (`Pi GPIO23` → `Pico GP3`) and 1PPS (`GPS→Pico GP21`).
- Power: Pico via USB; ADS1220 from Pico 3V3 (single point ground).

**拓扑 B（ADS1220 连接至 Pi）**

- Pico2 仅负责频率计数，通过 USB/UART 将结果发送至 Pi。
- ADS1220 SPI (Pi): `SCLK GPIO11`, `MOSI GPIO10`, `MISO GPIO9`, `CS GPIO8`, `DRDY GPIO25`。
- 保留 `GPIO2/3` I²C 给 DPS5000；同步线 `Pi GPIO23` → `Pico GP3` 保持窗对齐。

## Configuration Reference

`host_pi/config.json` consolidates acquisition defaults and host runtime behaviour. Key fields:

- `mode`: `RECIP`（互易计数）或 `GATED`（固定闸门）。
- `tau_ms`: 目标窗口长度；固件返回实际值并写入帧 `tau_ms`。
- `min_interval_frac`: 互易模式去毛刺阈值（最小沿间隔 = frac × 周期）。
- `timebase_ppm`: 静态 ppm 修正（无 1PPS 时手动设定）。
- `frame_format`: `csv` 或 `binary`（二进制默认更稳健）。
- `output_csv`: 结果 CSV 输出路径。留空仅做在线处理。
- `adc`: ADS1220 配置 (`gain`, `rate_sps`, `mains_reject`).
- `sensor_poly`:
  - `X`：频率基准 (Hz)。
  - `Y`：二极管电压基准 (µV)。
  - `K`：二维系数矩阵（行=频率阶次，列=电压阶次）。矩阵可扩展，需保持行长一致。
- `allan_window`: Allan deviation 计算窗口长度（样本数）。
- `host`: Runtime knobs
  - `queue_maxsize`: 接收线程 → 处理线程缓冲深度。
  - `reconnect_initial_sec` / `reconnect_max_sec`: 串口重连指数退避范围。
  - `stats_log_interval`: 日志输出周期（秒）。
  - `binary_chunk_size`: 二进制模式下单次读取的字节数。

### 预设档位

`terps-host` 提供 `--preset` 开关快速切换采集参数：

| 预设 | 模式 | τ (ms) | PGA | 采样率 (S/s) | 说明 |
|------|------|--------|-----|--------------|------|
| `0p02` | RECIP | 100 | ×16 | 50 | 0.02% FS 入门档 |
| `0p01` | RECIP | 500 | ×32 | 40 | 0.01% FS（建议 1PPS）|
| `0p003` | RECIP | 2000 | ×32 | 20 | 0.003% FS（OCXO/GPSDO）|

示例：`terps-host run --preset 0p02 --port /dev/ttyACM0 --set output_csv=run.csv`

## Tooling

- `host_pi/tools/allan.py`：计算频率序列的 Allan 偏差。
- `host_pi/tools/plot.py`：快速绘制频率 / 压力随时间曲线。

## Samples & Replay

- `samples/sample_run.csv`：示例处理结果，可直接用 `bslfs calc --in samples/sample_run.csv --report out/` 检验。
- `samples/sample_frames.bin`：十个二进制帧的样例，可用 `cat samples/sample_frames.bin | terps-host --port - --frame-format binary --set output_csv=replay.csv` 回放，验证解析与日志输出。

## Firmware Build & Flash

1. 克隆 Pico SDK 并设置 `PICO_SDK_PATH`（例如 `export PICO_SDK_PATH=$HOME/pico-sdk`）。
2. 编译固件：

   ```bash
   cmake -S firmware_pico2 -B firmware_pico2/build -G Ninja -DPICO_SDK_PATH=$PICO_SDK_PATH
   cmake --build firmware_pico2/build -j
   ```

   生成的 UF2 文件位于 `firmware_pico2/build/`，在 BOOTSEL 模式下复制到 Pico 2。

3. 主要固件配置（参见 `include/config_default.h`）：

   | 字段 | 默认值 | 描述 |
   |------|--------|------|
   | `mode` | `RECIP` | 互易计数；可切换为 `GATED` |
   | `tau_ms` | 100 | 窗口长度 (ms) |
   | `min_interval_frac` | 0.25 | 去毛刺最小沿间隔占比 |
   | `timebase_ppm` | 0.0 | 初始时基修正 |
   | `adc_gain` | 16 | ADS1220 PGA |
   | `adc_rate_sps` | 20 | 采样率 (S/s) |
   | `avg_window` | 8 | ADS1220 移动平均窗口 |
   | `binary_frames` | true | 默认输出二进制帧 |
| `queue_length` | 8 | 频率→帧缓冲深度 |
| `sync_gpio` | GP3 | SYNC 输入（Pi→Pico） |
| `pps_gpio` | GP21 | 1PPS 输入（可选） |
| `freq_gpio` | GP2 | 频率计数输入 |
| `adc_timeout_ms` | 200 | ADS1220 DRDY 超时时间 |
| `debug_deglitch_stats` | false | CSV 下输出去毛刺统计（注释行） |

   修改后重新编译即可生效；若需运行时切换，可在未来扩展命令接口。

## Firmware Reminder

`firmware_pico2/` 现已实现双核架构：Core0 执行互易/闸门计数并处理 SYNC/1PPS，Core1 读取 ADS1220、
融合频率/电压/校准信息，通过 TinyUSB CDC 输出统一帧。保持本指南列出的单位与字段顺序不变，
以确保 `bslfs.terps.frames` 与上位机解析逻辑兼容。

当 `debug_deglitch_stats` 置为 true 且固件处于 CSV 模式时，会额外输出 `# raw=...` 注释行，记录原始沿数/保留沿数/毛刺丢弃数与当前去毛刺阈值，便于现场诊断输入振铃。
