cmake_minimum_required(VERSION 3.13)
project(terps_pico2 C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(PICO_SDK_PATH "$ENV{PICO_SDK_PATH}" CACHE PATH "Path to pico-sdk")

include(${PICO_SDK_PATH}/external/pico_sdk_import.cmake)

pico_sdk_init()

add_executable(terps_pico2
    src/main.cpp
    src/config_default.cpp
    src/edge_counter.cpp
    src/ads1220.cpp
    src/usb_cdc.cpp
    src/pps_cal.cpp
)

target_include_directories(terps_pico2 PUBLIC include)

pico_enable_stdio_usb(terps_pico2 1)
pico_enable_stdio_uart(terps_pico2 0)

set_target_properties(terps_pico2 PROPERTIES OUTPUT_NAME "terps_pico2")

pico_add_extra_outputs(terps_pico2)

 target_link_libraries(terps_pico2
    pico_stdlib
    pico_multicore
    hardware_spi
    hardware_gpio
    hardware_irq
    hardware_timer
    hardware_dma
    hardware_sync
    tinyusb_device
    tinyusb_board
)
