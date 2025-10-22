接线与系统部署全指南（Pico 2 + ADS1220 + 树莓派3B+ + TERPS）
========================================================

本指南手把手从硬件接线开始，到环境配置、固件刷写、EEPROM 系数读取与校验、实时采集与绘图、完整自测，一步一步跑通 RPS/DPS8000（TERPS） 的频率与二极管通道采集。

---

1. 硬件总览与 BOM
------------------

- 控制&测量：Raspberry Pi 3B+（上位机） + Raspberry Pi Pico 2（固件/采集）
- 高精度 ADC：ADS1220 模块（SPI）
- 传感器：TERPS（RPS/DPS8000 系列，带频率输出 + 温度二极管 + 内置 EEPROM/11LC040）
- 比较/整形：把传感器频率输出整形为 3.3V 方波（比较器/施密特）
- 导线：母-母杜邦线若干（推荐 13 根起），模拟差分建议用双绞/屏蔽线
- 小阻容：
  - 频率整形输出端：33–68 Ω 串联 + 47–100 pF 对地（靠近比较器脚）
  - ADS1220 差分 AIN：AIN0、AIN1 各串 ~100 Ω；AIN0–AIN1 间并 1 nF（可视噪声再加各自对地 1 nF）
  - UNI/O SCIO：串 220–470 Ω（推挽，非上拉）

供电：Pico 通过 USB 连树莓派即可（供电+数据）。ADS1220 用 Pico 的 3V3 供电。所有设备共地。不要把树莓派 5V/3V3 直接接到 Pico 的 3V3/VSYS。

---

2. 接线指导（逐针脚对照）
------------------------

### 2.1 Pico 2 ↔ ADS1220（SPI0 + DRDY + 电源地）

ADS1220 模块常见丝印：左排（数字）DRDY, MISO, MOSI, SCLK, CS, DVDD, DGND；右排（模拟）AIN0/1/... REFP0/REFN0 AVDD AGND。

| 功能      | ADS1220 引脚 | 接到 Pico 2 | 物理脚号 | 说明                |
|-----------|--------------|-------------|----------|---------------------|
| SPI MISO  | MISO         | GP16        | Pin 21   | SPI0 MISO           |
| SPI MOSI  | MOSI         | GP19        | Pin 25   | SPI0 MOSI           |
| SPI SCLK  | SCLK         | GP18        | Pin 24   | SPI0 SCLK           |
| 片选 CS   | CS           | GP17        | Pin 22   | 片选                |
| 数据就绪  | DRDY         | GP20        | Pin 26   | DRDY 中断           |
| 数字电源  | DVDD         | 3V3         | Pin 36   | 3.3V                |
| 数字地    | DGND         | GND         | Pin 23   | 共地                |
| 模拟电源  | AVDD         | 3V3         | Pin 36   | 与 DVDD 同源        |
| 模拟地    | AGND         | AGND        | Pin 33   | 模拟回流更干净      |
| 差分 +    | AIN0         | 传感器二极管正 | —        | 串 ~100 Ω           |
| 差分 −    | AIN1         | 传感器二极管负 | —        | 串 ~100 Ω           |
| 差分 RC   | AIN0↔AIN1    | —           | —        | 并 1 nF（抗混叠）   |

参考：如果模块板上已把 AVDD=DVDD 或 AGND=DGND 硬连通，可减少一两根线，但仍建议星形回流：数字地与模拟地优先就近落在各自侧。

---

### 2.2 TERPS 传感器 ↔ ADS1220 / 比较器 / Pico 2

- 二极管（温度）：TERPS 的二极管正/负 → ADS1220 AIN0/AIN1（各串 ~100 Ω，差分并 1 nF）
- 频率输出：TERPS 频率 → 比较器/施密特整形 → Pico 2 GP2（Pin 4，3.3V 逻辑）
- 比较器输出端：33–68 Ω 串联 + 47–100 pF 对地（靠近比较器脚）
- EEPROM（系数，Microchip 11LC040 / UNI-O 单线）：
  - DATA/SCIO → Pico 2 GP6（串 220–470 Ω，推挽，非上拉）
  - VDD → 3V3（Pico Pin 36）
  - GND → GND（Pico Pin 23/33 任一就近）
  - 注意：UNI/O 不是 Dallas 1-Wire，不要加 4.7 k 上拉，保持推挽 + 串阻

---

### 2.3 树莓派 3B+ ↔ Pico 2（仅逻辑/同步；供电和数据走 USB）

- USB 线：树莓派 USB-A ↔ Pico 2 Micro-USB（供电 + CDC 串口）
- 公共地：Pi GND（Pin 6/9/14/20/25/30/34/39 任一）→ Pico GND（Pin 23/3/38 任一）
- 可选 SYNC：Pi GPIO23（物理 Pin 16）→ Pico GP3（Pin 5）
- 可选 1PPS：外部 1PPS → Pico GP21（Pin 27）

不要把 Pi 的 5V/3V3 直接接 Pico 的 3V3/VSYS。Pico 通过 USB 已经供电和通信。

---

### 2.4 接线数量建议

- 最少可用（不接 SYNC）：11 根
- 推荐（加 SYNC，独立多接一根地）：13 根
- 再加 1PPS：15 根

---

3. 软件环境与固件刷写
--------------------

### 3.1 上位机环境（树莓派 3B+）

```bash
sudo apt update
sudo apt install -y git cmake ninja-build gcc-arm-none-eabi libnewlib-arm-none-eabi \
                    python3-venv build-essential picotool
```

### 3.2 编译 Pico 2 固件

```bash
# 假设仓库已在 ~/rps（按实际路径调整）
cd ~/rps/firmware_pico2
cmake -S . -B build -G Ninja -DPICO_SDK_FETCH_FROM_GIT=1 -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ls build/*.uf2   # 看到生成的 .uf2
```

### 3.3 刷入固件（两种方式，选其一）

**方式 A：BOOTSEL 拖拽（推荐）**

1. 按住 BOOTSEL 键，把 Pico 2 插到树莓派 USB；
2. 系统会出现 U 盘 RPI-RP2；
3. 复制 UF2：`cp build/*.uf2 /media/$USER/RPI-RP2/`；拷完会自动重启；
4. 确认串口：`ls /dev/ttyACM*`（应出现 `/dev/ttyACM0`）。

**方式 B：picotool**

```bash
picotool reboot -u                 # 让设备进 U 盘模式
picotool load -f build/*.uf2
```

---

4. 项目安装与首跑
----------------

```bash
cd ~/rps
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[terps,plot]      # 安装上位机：解析+绘图+CLI
```

首跑（实时图 + CSV 落盘）：

```bash
terps-host run --port /dev/ttyACM0 --out run.csv --plot --plot-window-sec 60
```

- 预期：四象限实时图滚动：左上 压力（计算）/ 右上 温度（计算）/ 左下 频率（原始）/ 右下 二极管电压（原始）；`run.csv` 持续增长；终端每 ~60s 打一次健康统计。
- `Ctrl+C` 应能优雅退出（窗口和线程都收掉）。

---

5. 读取 EEPROM 系数（UNI/O，Microchip 11LC040）
---------------------------------------------

本固件已在 Pico 2 的 GP6 上实现 UNI/O（11LC040）只读，通过 CDC 文本命令对外提供。

### 5.1 快速串口自测

```bash
picocom -b115200 /dev/ttyACM0
# 在 picocom 中敲：
INFO.DEV
EEPROM.DUMP 0 32
# 预期：
# OK FW=... UNIO_GPIO=6 BITRATE=~50kbps
# OK LEN=32
# 64 个十六进制字符（允许每 32 字节换行）
# 退出：Ctrl+A, Ctrl+Q
```

### 5.2 完整 dump、校验与解析（上位机 CLI）

```bash
# 读取前 512B（0..0x1FF）
terps-host coeff dump --port /dev/ttyACM0 --addr 0 --len 512 --out rps.bin
```

```bash
# 校验与大端浮点示例解析
python3 - <<'PY'
import struct
b=open('rps.bin','rb').read()
print("len=",len(b),"sum16=",hex(sum(b[:0x200]) & 0xFFFF))  # 正确应为 0x1234
for off in (0x80,0x84,0x88,0x8C):
    if off+4<=len(b):
        print(hex(off), struct.unpack(">f", b[off:off+4])[0])  # 注意大端 '>f'
PY
```

校验规则：`sum(bytes[0..0x1FF]) & 0xFFFF == 0x1234`；浮点为大端 IEEE-754。  
自动应用策略（已内置）：系数来源优先级 manual > eeprom > config；当 EEPROM 校验通过且解析成功时自动使用并在 CSV 首注释写入：  
`# coeff_source=eeprom coeff_order=N coeff_serial=... unit=uV`。  
解析失败或无设备时回退到 manual/config，并给出 WARN。

### 5.3 手动覆盖系数（回退/调试）

```bash
# 手动设置：P = a0 + a1*y + a2*y^2 + ...  ，y 单位为 µV（v_uV）
terps-host coeff set --order 3 --a 0.0 1.234e-3 -5.6e-9 7.8e-15

# 运行时指定来源 auto/manual/config（默认 auto）
terps-host run --port /dev/ttyACM0 --coeff-source auto --out run.csv --plot
```

---

6. 频率与模拟链路的小技巧（强烈建议）
----------------------------------

- 频率多沿/翻倍（60 kHz→整形后 30 kHz 不稳）：在比较器输出端加 33–68 Ω 串联 + 47–100 pF 对地，器件脚就近；确保进入 GP2 的每周期只有一次上升沿。
- 模拟差分抗混叠：AIN0、AIN1 各串 ~100 Ω；AIN0–AIN1 间并 1 nF；必要时各自对地再并 1 nF；星形回地（AGND / GND 分别回各自侧）。
- UNI/O 电气：SCIO 为推挽，非开漏；串 220–470 Ω 防冲突；短线 + 0.1 µF 去耦。

---

7. 常见问题（FAQ / 排错）
------------------------

1. Pico 插入无 RPI-RP2 U 盘：多半 USB 线仅充电不带数据；换短的数据线；或 `picotool reboot -u`。
2. 没有 `/dev/ttyACM0`：`dmesg | tail` 看日志；把用户加入 dialout：`sudo usermod -a -G dialout $USER` 并重新登录。
3. `EEPROM.DUMP` 报 `ERR NAK/NO_DEVICE`：检查 UNI/O 接线（GP6、推挽串阻、3V3/GND）；把速率稍降（固件里把半位 T_HALF_US 提到 12–15 µs）。
4. 校验不是 0x1234：常见是读长不对（必须 512 B）或端序/地址偏移错误；重读 `--len 512` 并确认解析用 `'>f'`。
5. 实时图卡顿/丢样：绘图 FPS 适度（10–20）；CDC 命令在命令线程执行（不阻塞采样）；USB 口直插主板，避开劣质 HUB。
6. 精度不达预期：频率测量要优于 0.05 Hz@30 kHz；二极管分辨率优于 0.01 mV；按上文阻抗/RC/接地建议优化。
7. CSV 首注释缺少 coeff 信息：更新到最新上位机；确保 `--coeff-source` 选项正确且 `coeff set / coeff dump` 已执行。

---

8. 版本与许可
-------------

- 固件：Pico 2（RP2350）/ TinyUSB CDC
- 上位机：Python 3.9+，matplotlib（实时绘图），pyserial（CDC），typer/click（CLI）
- License：见仓库 LICENSE

---

（说明书正文到此结束）

---

# BSL/FS Calibration Toolkit

`bslfs` is a Python package and CLI that evaluates pressure sensor calibration data following JJG860/JJG882 conventions. It ingests CSV data, performs best straight line (BSL) fitting, compares against endpoint and least-squares references, and produces metrics, plots, and reports.

It also ships a `terps-host` command that runs on Raspberry Pi to decode TERPS RPS frames (frequency + diode voltage), compute pressure with polynomial coefficients, and archive synchronized samples. See `docs/terps_host.md` for wiring and usage notes.

## Installation

```bash
pip install -e .[dev,plot]
```

- Core dependencies: `numpy`, `pandas`, `typer`.
- Optional plotting extras (`[plot]`) enable PNG outputs via `matplotlib`.

### TERPS Host Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev,plot,terps]
terps-host run --port /dev/ttyACM0 --config host_pi/config.json --set output_csv=run.csv
```

Use `--set frame_format=binary` once the Pico 2 firmware is streaming binary frames reliably.
On Raspberry Pi desktop sessions install the Tk backend first (`sudo apt install python3-tk`) so Matplotlib windows can open.

Replay the bundled sample frames to sanity-check the pipeline:

```bash
cat samples/sample_frames.bin | terps-host --port - --frame-format binary --set output_csv=replay.csv
```

Add `--plot` to open a realtime Matplotlib dashboard (requires `pip install -e .[plot]`).
Extra controls:

- `--plot-snapshot-every 10` saves PNGs beside `--out` every 10 seconds.
- `--temp-mode linear|poly|off` controls the upper-right temperature proxy (`--temp-linear-v0-uV`, `--temp-linear-slope-uV-per-C`, `temp_poly` in config drive conversions).

## Input Format

Provide a CSV file with the following columns:

| Column        | Required | Description                                  |
|---------------|----------|----------------------------------------------|
| `pressure_ref`| ✅        | Applied reference pressure (engineering units) |
| `output`      | ✅        | Sensor output reading                         |
| `cycle_id`    | ✅        | Identifier for each loading branch (up/down)  |
| `temp`        | ➕        | Measured temperature (optional)               |

Rows may be unordered; the tool infers loading direction per `cycle_id` based on the pressure trend. Multiple cycles and repeated pressures are supported.

Full-scale span `%FS` is defined as `max(output) - min(output)` for the provided dataset.

## CLI Usage

Generate calibration artefacts:

```bash
bslfs calc --in data.csv --mode bsl --report out/ --temp-comp linear
```

Outputs in `out/`:

- `metrics.csv` – summary table of linearity, hysteresis, repeatability, total error (absolute + %FS)
- `residuals.csv` – per-sample predictions and residuals for all fits
- `report.md` – Markdown report ready for sharing
- `plots.png` – scatter, error, and hysteresis loop visualisations (requires `[plot]` extra)

Create a demo dataset and matching report:

```bash
bslfs demo --out demo_output/
```

## Algorithms

- **Endpoint line**: straight line between minimum and maximum pressures.
- **OLS line**: ordinary least squares regression.
- **BSL line**: Chebyshev (minimax) fit that minimises the peak absolute deviation while constraining all points within the band.
- **Temperature compensation** (`--temp-comp linear`): augments the regression with a linear temperature term and reports compensated metrics alongside uncompensated ones.

Metrics follow JJG definitions:

- **Linearity**: peak absolute deviation from each reference line, reported in output units and %FS.
- **Hysteresis**: maximum up/down difference at matching reference pressures.
- **Repeatability**: worst-case deviation from the mean for repeated pressures in the same direction.
- **Total error**: root-sum-square of BSL linearity, hysteresis, and repeatability.

## Development

- Format and lint: `ruff check .` and `black .`
- Run tests: `pytest -q`
- Pre-commit hooks: `pre-commit install`

See `docs/formulas.md` for detailed derivations and JJG references.
