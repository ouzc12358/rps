#include "pico/stdlib.h"

// TODO: Implement Core0 acquisition loop and Core1 USB framing.
int main() {
    stdio_init_all();
    while (true) {
        tight_loop_contents();
    }
    return 0;
}
