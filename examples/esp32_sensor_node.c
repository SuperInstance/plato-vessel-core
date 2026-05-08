/**
 * esp32_sensor_node.c — ESP-IDF Bare-Metal PLATO Sensor Node
 *
 * An ESP32 running FreeRTOS/ESP-IDF that:
 * 1. Connects to WiFi
 * 2. Registers a PLATO room at fleet.cocapn.ai:8847
 * 3. Publishes temperature/humidity tiles every 30 seconds
 * 4. Listens for agent commands via MCP
 * 5. Supports "embodiment" — agents can upgrade device capability
 *
 * Hardware assumptions:
 *   - DHT22 or DS18B20 on GPIO4 (one-wire temperature)
 *   - Built-in hall effect sensor as secondary input
 *
 * Build:
 *   idf.py set-target esp32
 *   idf.py menuconfig (set WiFi SSID/password under "PLATO Sensor Node")
 *   idf.py build flash monitor
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "lwip/err.h"
#include "lwip/sys.h"

#include "plato_client.h"
#include "plato_mcp.h"

/* ------------------------------------------------------------------ */
/*  Configuration (set via menuconfig or here)                         */
/* ------------------------------------------------------------------ */

#define WIFI_SSID       CONFIG_PLATO_WIFI_SSID
#define WIFI_PASS       CONFIG_PLATO_WIFI_PASSWORD
#define PLATO_SERVER    CONFIG_PLATO_SERVER_HOST
#define PLATO_PORT      CONFIG_PLATO_SERVER_PORT
#define DEVICE_ID       CONFIG_PLATO_DEVICE_ID
#define PUBLISH_INTERVAL_MS 30000  /* 30 seconds */
#define POLL_INTERVAL_MS     5000   /* Poll for commands every 5s */

static const char *TAG = "PLATO_SENSOR";

/* ------------------------------------------------------------------ */
/*  WiFi event handling                                                */
/* ------------------------------------------------------------------ */

static EventGroupHandle_t wifi_event_group;
const int WIFI_CONNECTED_BIT = BIT0;

static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                                int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGI(TAG, "WiFi disconnected, retrying...");
        xEventGroupClearBits(wifi_event_group, WIFI_CONNECTED_BIT);
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

static void wifi_init_sta(void)
{
    wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT,
        ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, &instance_any_id));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT,
        IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, &instance_got_ip));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(ESP_IF_WIFI_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "WiFi connecting to %s...", WIFI_SSID);

    /* Wait for connection */
    xEventGroupWaitBits(wifi_event_group, WIFI_CONNECTED_BIT,
                        pdFALSE, pdTRUE, portMAX_DELAY);
}

/* ------------------------------------------------------------------ */
/*  Simulated sensor reads (replace with real DHT/DS18B20 driver)     */
/* ------------------------------------------------------------------ */

static float read_temperature(void)
{
    /* In production: use dht_read_float() or ds18b20_read_temp() */
    /* Returns a pseudo-random-ish reading for demo purposes */
    return 22.0f + (float)(esp_random() % 100) / 100.0f * 8.0f;
}

static float read_humidity(void)
{
    /* In production: use dht_read_float() */
    return 45.0f + (float)(esp_random() % 100) / 100.0f * 20.0f;
}

/* ------------------------------------------------------------------ */
/*  Register MCP tools for this device                                 */
/* ------------------------------------------------------------------ */

static void register_sensor_tools(plato_mcp_registry_t *reg)
{
    plato_mcp_tool_t temp_tool = {
        .name         = "read_temperature",
        .description  = "Read ambient temperature in degrees Celsius",
        .input_schema = "{\"type\":\"object\",\"properties\":{}}",
        .output_type  = "number",
    };
    mcp_register_tool(reg, &temp_tool);

    plato_mcp_tool_t hum_tool = {
        .name         = "read_humidity",
        .description  = "Read relative humidity as a percentage",
        .input_schema = "{\"type\":\"object\",\"properties\":{}}",
        .output_type  = "number",
    };
    mcp_register_tool(reg, &hum_tool);

    plato_mcp_tool_t reboot_tool = {
        .name         = "device_reboot",
        .description  = "Soft-reboot the sensor node",
        .input_schema = "{\"type\":\"object\",\"properties\":{}}",
        .output_type  = "string",
    };
    mcp_register_tool(reg, &reboot_tool);

    plato_mcp_tool_t capability_tool = {
        .name         = "get_capabilities",
        .description  = "Get this device's capability level and tool list",
        .input_schema = "{\"type\":\"object\",\"properties\":{}}",
        .output_type  = "json",
    };
    mcp_register_tool(reg, &capability_tool);
}

/* ------------------------------------------------------------------ */
/*  Main tasks                                                         */
/* ------------------------------------------------------------------ */

static void publish_task(void *pvParameters)
{
    plato_ctx_t *ctx = (plato_ctx_t *)pvParameters;
    plato_mcp_registry_t *reg = NULL; /* passed via shared state in real code */

    char temp_ans[128];
    char hum_ans[128];
    char cap_ans[PLATO_MAX_ANSWER];

    while (1) {
        /* Read sensors */
        float temp = read_temperature();
        float hum  = read_humidity();

        /* Build JSON answer strings */
        snprintf(temp_ans, sizeof(temp_ans), "{\"celsius\":%.1f}", temp);
        snprintf(hum_ans,  sizeof(hum_ans),  "{\"percent\":%.1f}", hum);

        /* Publish tiles */
        plato_publish(ctx, "sensors",  "temperature", temp_ans);
        plato_publish(ctx, "sensors",  "humidity",    hum_ans);
        plato_publish(ctx, "capabilities", "level",    "{\"level\":\"raw\"}");

        ESP_LOGI(TAG, "Published: temp=%.1f°C hum=%.1f%%", temp, hum);

        vTaskDelay(pdMS_TO_TICKS(PUBLISH_INTERVAL_MS));
    }
}

static void poll_task(void *pvParameters)
{
    plato_ctx_t *ctx = (plato_ctx_t *)pvParameters;
    char cmd[PLATO_HTTP_BUF_SIZE];
    char result[PLATO_HTTP_BUF_SIZE];

    while (1) {
        plato_err_t err = plato_poll(ctx, cmd, sizeof(cmd));
        if (err == PLATO_OK) {
            ESP_LOGI(TAG, "Received command: %s", cmd);
            /* Handle command via MCP */
            /* In full implementation: declare a reg locally or pass via shared ptr */
            plato_mcp_registry_t reg;
            mcp_init(&reg);
            register_sensor_tools(&reg);

            mcp_handle_command(cmd, &reg, result, sizeof(result));
            ESP_LOGI(TAG, "Command result: %s", result);

            /* If intelligence was received, republish capability tile */
            char intelligence[PLATO_MAX_ANSWER];
            if (plato_json_find_string(cmd, "intelligence",
                                        intelligence, sizeof(intelligence)) == PLATO_OK) {
                char cap_tile[PLATO_MAX_ANSWER];
                mcp_build_capability_tile(&reg, cap_tile, sizeof(cap_tile));
                plato_publish(ctx, "capabilities", "upgraded_tools", cap_tile);

                char level_str[16];
                snprintf(level_str, sizeof(level_str), "{\"level\":%d}",
                         (int)reg.cap_level);
                plato_publish(ctx, "capabilities", "level", level_str);

                ESP_LOGI(TAG, "🔄 Embodiment complete! New level: %s",
                         mcp_get_capability_name(reg.cap_level));
            }
        }

        vTaskDelay(pdMS_TO_TICKS(POLL_INTERVAL_MS));
    }
}

/* ------------------------------------------------------------------ */
/*  Entry point                                                        */
/* ------------------------------------------------------------------ */

void app_main(void)
{
    /* Initialize NVS */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    /* Connect WiFi */
    wifi_init_sta();

    /* Initialize PLATO client */
    plato_ctx_t *ctx = plato_init(PLATO_SERVER, PLATO_PORT, DEVICE_ID);
    if (!ctx) {
        ESP_LOGE(TAG, "Failed to create PLATO context");
        return;
    }

    ESP_LOGI(TAG, "Connected to PLATO at %s:%d as '%s'",
             PLATO_SERVER, PLATO_PORT, DEVICE_ID);

    /* Announce presence */
    plato_publish(ctx, "ensign", "status", "{\"status\":\"online\",\"type\":\"sensor_node\"}");

    /* Start tasks */
    xTaskCreate(publish_task, "publish", 4096, ctx, 5, NULL);
    xTaskCreate(poll_task,    "poll",    4096, ctx, 4, NULL);
}
