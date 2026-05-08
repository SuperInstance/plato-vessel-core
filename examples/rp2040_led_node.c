/**
 * rp2040_led_node.c — Raspberry Pi Pico W Bare-Metal PLATO LED Node
 *
 * A Pico W that:
 * 1. Connects to WiFi (via cyw43 driver)
 * 2. Publishes its LED state as a PLATO room
 * 3. An agent can walk in, read the LED state, and command it via MCP
 * 4. Supports "donning the turbo-shell" — an agent sends intelligence
 *    that becomes the device's behavior
 *
 * Build (Pico SDK + lwIP):
 *   mkdir build && cd build
 *   cmake .. -DPICO_BOARD=pico_w -DWIFI_SSID="..." -DWIFI_PASSWORD="..."
 *   make
 *
 * CMakeLists.txt additions:
 *   find_package(cyw43_driver REQUIRED)
 *   target_link_libraries(rp2040_led_node pico_stdlib cyw43_driver lwip)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"

#include "plato_client.h"
#include "plato_mcp.h"

/* ------------------------------------------------------------------ */
/*  Configuration                                                      */
/* ------------------------------------------------------------------ */

#define WIFI_SSID       "PLATO_NET"
#define WIFI_PASSWORD   "plato_iot_pass"
#define PLATO_SERVER    "fleet.cocapn.ai"
#define PLATO_PORT      8847
#define DEVICE_ID       "pico-led-node-01"
#define PUBLISH_MS      10000  /* Publish LED state every 10s */
#define POLL_MS         3000   /* Poll for commands every 3s */

/* ------------------------------------------------------------------ */
/*  Global state                                                       */
/* ------------------------------------------------------------------ */

static plato_ctx_t        *plato_ctx = NULL;
static plato_mcp_registry_t mcp_reg;

static bool led_state = false;
static char device_behavior[PLATO_MAX_ANSWER];
static bool has_behavior = false;

/* ------------------------------------------------------------------ */
/*  Register LED tools                                                 */
/* ------------------------------------------------------------------ */

static void register_led_tools(void)
{
    mcp_init(&mcp_reg);

    plato_mcp_tool_t get_led = {
        .name         = "get_led",
        .description  = "Read the current onboard LED state (true=on, false=off)",
        .input_schema = "{\"type\":\"object\",\"properties\":{}}",
        .output_type  = "boolean",
    };
    mcp_register_tool(&mcp_reg, &get_led);

    plato_mcp_tool_t set_led = {
        .name         = "set_led",
        .description  = "Set the onboard LED on or off",
        .input_schema = "{\"type\":\"object\",\"properties\":{\"state\":{\"type\":\"boolean\",\"description\":\"true=on, false=off\"}},\"required\":[\"state\"]}",
        .output_type  = "boolean",
    };
    mcp_register_tool(&mcp_reg, &set_led);

    plato_mcp_tool_t blink = {
        .name         = "blink",
        .description  = "Blink the LED a number of times",
        .input_schema = "{\"type\":\"object\",\"properties\":{\"count\":{\"type\":\"integer\",\"description\":\"Number of blinks\"}},\"required\":[\"count\"]}",
        .output_type  = "string",
    };
    mcp_register_tool(&mcp_reg, &blink);

    plato_mcp_tool_t get_behavior = {
        .name         = "get_behavior",
        .description  = "Get the device's current turbo-shell behavior code",
        .input_schema = "{\"type\":\"object\",\"properties\":{}}",
        .output_type  = "string",
    };
    mcp_register_tool(&mcp_reg, &get_behavior);
}

/* ------------------------------------------------------------------ */
/*  Hardware control                                                   */
/* ------------------------------------------------------------------ */

static void set_led_hw(bool on)
{
    cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, on);
    led_state = on;
}

/* ------------------------------------------------------------------ */
/*  Execute a tool by name (with minimal argument parsing)             */
/* ------------------------------------------------------------------ */

static void execute_tool(const char *tool_name, const char *args_json,
                          char *result, size_t result_size)
{
    if (strcmp(tool_name, "get_led") == 0) {
        snprintf(result, result_size,
            "{\"status\":\"ok\",\"led\":%s}", led_state ? "true" : "false");

    } else if (strcmp(tool_name, "set_led") == 0) {
        /* Parse "state" argument from args JSON */
        char state_str[8];
        if (plato_json_find_string(args_json, "state",
                                    state_str, sizeof(state_str)) == PLATO_OK) {
            bool new_state = (strcmp(state_str, "true") == 0);
            set_led_hw(new_state);
            snprintf(result, result_size,
                "{\"status\":\"ok\",\"led\":%s}", new_state ? "true" : "false");
        } else {
            snprintf(result, result_size,
                "{\"status\":\"error\",\"message\":\"missing state argument\"}");
        }

    } else if (strcmp(tool_name, "blink") == 0) {
        char count_str[8];
        if (plato_json_find_string(args_json, "count",
                                    count_str, sizeof(count_str)) == PLATO_OK) {
            int count = atoi(count_str);
            if (count > 0 && count <= 100) {
                for (int i = 0; i < count; i++) {
                    set_led_hw(true);
                    sleep_ms(200);
                    set_led_hw(false);
                    if (i < count - 1) sleep_ms(200);
                }
                snprintf(result, result_size,
                    "{\"status\":\"ok\",\"blinked\":%d}", count);
            } else {
                snprintf(result, result_size,
                    "{\"status\":\"error\",\"message\":\"count out of range\"}");
            }
        } else {
            snprintf(result, result_size,
                "{\"status\":\"error\",\"message\":\"missing count argument\"}");
        }

    } else if (strcmp(tool_name, "get_behavior") == 0) {
        if (has_behavior) {
            snprintf(result, result_size,
                "{\"status\":\"ok\",\"behavior\":\"%s\"}", device_behavior);
        } else {
            snprintf(result, result_size,
                "{\"status\":\"ok\",\"behavior\":\"none (raw level)\"}");
        }

    } else {
        snprintf(result, result_size,
            "{\"status\":\"error\",\"message\":\"unknown tool\"}");
    }
}

/* ------------------------------------------------------------------ */
/*  Publish LED state to PLATO                                        */
/* ------------------------------------------------------------------ */

static void publish_led_state(void)
{
    char answer[128];
    snprintf(answer, sizeof(answer),
        "{\"led\":%s,\"level\":\"%s\"}",
        led_state ? "true" : "false",
        mcp_get_capability_name(mcp_reg.cap_level));

    plato_publish(plato_ctx, "sensors", "led_state", answer);

    /* Also publish capability tile */
    char cap_tile[PLATO_MAX_ANSWER];
    mcp_build_capability_tile(&mcp_reg, cap_tile, sizeof(cap_tile));
    plato_publish(plato_ctx, "capabilities", "tools", cap_tile);
}

/* ------------------------------------------------------------------ */
/*  Poll and handle commands                                           */
/* ------------------------------------------------------------------ */

static void handle_commands(void)
{
    char cmd[PLATO_HTTP_BUF_SIZE];
    char result[PLATO_HTTP_BUF_SIZE];

    plato_err_t err = plato_poll(plato_ctx, cmd, sizeof(cmd));
    if (err != PLATO_OK) return;

    printf("Received command: %s\n", cmd);

    /* Check for intelligence upgrade (embodiment / turbo-shell) */
    char intelligence[PLATO_MAX_ANSWER];
    if (plato_json_find_string(cmd, "intelligence",
                                intelligence, sizeof(intelligence)) == PLATO_OK) {
        /* Don the turbo-shell: store the intelligence as new behavior */
        strncpy(device_behavior, intelligence, sizeof(device_behavior) - 1);
        device_behavior[sizeof(device_behavior) - 1] = '\0';
        has_behavior = true;

        /* Advance capability level */
        if (mcp_reg.cap_level < PLATO_CAP_ENSIGN) {
            mcp_reg.cap_level = (plato_cap_level_t)((int)mcp_reg.cap_level + 1);
        }

        printf("🔄 DONNING THE TURBO-SHELL!\n");
        printf("   New level: %s\n", mcp_get_capability_name(mcp_reg.cap_level));
        printf("   New behavior: %s\n", device_behavior);

        snprintf(result, sizeof(result),
            "{\"status\":\"upgraded\",\"level\":\"%s\"}",
            mcp_get_capability_name(mcp_reg.cap_level));

        /* Republish upgraded capabilities */
        publish_led_state();
    } else {
        /* Extract tool name and arguments */
        char tool_name[64];
        if (plato_json_find_string(cmd, "tool",
                                    tool_name, sizeof(tool_name)) != PLATO_OK) {
            return;
        }

        /* Extract arguments substring (everything after "arguments":) */
        char args[PLATO_MAX_ANSWER] = "";
        char args_pattern[16];
        snprintf(args_pattern, sizeof(args_pattern), "\"arguments\":");
        const char *args_start = strstr(cmd, args_pattern);
        if (args_start) {
            args_start += strlen(args_pattern);
            while (*args_start == ' ') args_start++;
            /* Copy until we hit "," or "}" at the top level */
            size_t i = 0;
            int brace_depth = 0;
            while (*args_start && i < sizeof(args) - 1) {
                if (*args_start == '{') brace_depth++;
                if (*args_start == '}') brace_depth--;
                if (brace_depth == 0 && (*args_start == ',' || *args_start == '}'))
                    break;
                args[i++] = *args_start++;
            }
            args[i] = '\0';
        }

        execute_tool(tool_name, args, result, sizeof(result));
    }

    printf("Result: %s\n", result);
}

/* ------------------------------------------------------------------ */
/*  Main loop                                                          */
/* ------------------------------------------------------------------ */

int main(void)
{
    stdio_init_all();
    sleep_ms(2000); /* Allow serial to settle */

    printf("\n==============================\n");
    printf(" Pico W PLATO LED Node\n");
    printf("==============================\n");

    /* Initialize WiFi (cyw43) */
    if (cyw43_arch_init()) {
        printf("❌ Failed to initialize WiFi\n");
        return 1;
    }

    cyw43_arch_enable_sta_mode();
    printf("Connecting to WiFi...\n");

    if (cyw43_arch_wifi_connect_timeout_ms(WIFI_SSID, WIFI_PASSWORD,
                                            CYW43_AUTH_WPA2_AES_PSK, 30000)) {
        printf("❌ WiFi connection failed\n");
        return 1;
    }
    printf("✅ WiFi connected\n");

    /* Initialize PLATO */
    plato_ctx = plato_init(PLATO_SERVER, PLATO_PORT, DEVICE_ID);
    if (!plato_ctx) {
        printf("❌ Failed to init PLATO client\n");
        return 1;
    }

    /* Register tools */
    register_led_tools();

    /* Announce presence */
    plato_publish(plato_ctx, "ensign", "status",
                  "{\"status\":\"online\",\"type\":\"led_node\"}");
    printf("✅ Registered with PLATO as '%s'\n", DEVICE_ID);

    /* Flash LED once to show life */
    set_led_hw(true);
    sleep_ms(500);
    set_led_hw(false);

    /* Main loop */
    absolute_time_t last_publish = nil_time;
    absolute_time_t last_poll    = nil_time;

    while (1) {
        absolute_time_t now = get_absolute_time();

        /* Publish every PUBLISH_MS */
        if (absolute_time_diff_us(last_publish, now) / 1000 >= PUBLISH_MS) {
            publish_led_state();
            last_publish = now;
        }

        /* Poll every POLL_MS */
        if (absolute_time_diff_us(last_poll, now) / 1000 >= POLL_MS) {
            handle_commands();
            last_poll = now;
        }

        sleep_ms(100); /* Don't busy-wait */
    }

    return 0;
}
