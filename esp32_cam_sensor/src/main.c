#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_event.h"
#include "esp_idf_version.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "mqtt_client.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#if defined(__has_include)
#if __has_include("esp_camera.h")
#define APP_HAS_CAMERA 1
#include "esp_camera.h"
#include "sensor.h"
#else
#define APP_HAS_CAMERA 0
#endif
#else
#define APP_HAS_CAMERA 0
#endif

#ifndef WIFI_SSID
#define WIFI_SSID "CHANGE_ME_SSID"
#endif

#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "CHANGE_ME_PASSWORD"
#endif

#ifndef WIFI_MIN_AUTHMODE
#define WIFI_MIN_AUTHMODE WIFI_AUTH_OPEN
#endif

#ifndef MQTT_URI
#define MQTT_URI "mqtt://192.168.1.10:1883"
#endif

#ifndef MQTT_USERNAME
#define MQTT_USERNAME ""
#endif

#ifndef MQTT_PASSWORD
#define MQTT_PASSWORD ""
#endif

#ifndef NODE_GROUP
#define NODE_GROUP "all"
#endif

#ifndef TELEMETRY_PERIOD_MS
#define TELEMETRY_PERIOD_MS 5000U
#endif

#ifndef INVENTORY_PERIOD_MS
#define INVENTORY_PERIOD_MS 60000U
#endif

#ifndef SENSOR_SID
#define SENSOR_SID "esp32cam_0"
#endif

#ifndef SENSOR_STYPE
#define SENSOR_STYPE "esp32cam"
#endif

#define TOPIC_BUF_LEN 128
#define NODE_ID_BUF_LEN 32

/* schema_v1 integer key map serialized as JSON object keys */
#define K_VER "0"
#define K_TYP "1"
#define K_NID "2"
#define K_SEQ "3"
#define K_TUP "4"
#define K_MID "5"

#define K_SENSORS "10"
#define K_HW "20"
#define K_FW "21"
#define K_CAPS "22"
#define K_NET "23"

#define KS_SID "0"
#define KS_STYPE "1"
#define KS_CHANS "2"

#define KC_CID "0"
#define KC_UNIT "1"
#define KC_VAL "2"
#define KC_Q "3"
#define KC_TUP "4"

#define MSG_TYPE_TELEMETRY 1
#define MSG_TYPE_COMMAND 2
#define MSG_TYPE_ACK 3
#define MSG_TYPE_INVENTORY 4

#define KINT_VER 0
#define KINT_TYP 1
#define KINT_NID 2
#define KINT_SEQ 3
#define KINT_TUP 4
#define KINT_MID 5
#define KINT_CMD 30
#define KINT_ARGS 31
#define KINT_ACK_MID 40
#define KINT_RC 41
#define KINT_DETAIL 42
#define KINT_REBOOT 44

#define CMD_OP_SET_CONFIG 10
#define CMD_OP_SET_PERIOD 11
#define CMD_OP_OTA 12
#define CMD_OP_REBOOT 13
#define CMD_OP_READ_NOW 14

#define ACK_RC_OK 0
#define ACK_RC_INVALID_SCHEMA -1
#define ACK_RC_WRONG_TARGET -2
#define ACK_RC_UNSUPPORTED_SENSOR -3

static const char *TAG = "sensor_network_node";
static EventGroupHandle_t s_wifi_event_group;
static const int WIFI_CONNECTED_BIT = BIT0;

static esp_mqtt_client_handle_t s_mqtt_client;
static bool s_mqtt_connected = false;
static volatile uint32_t s_telemetry_period_ms = TELEMETRY_PERIOD_MS;
static uint32_t s_seq = 0;
static bool s_camera_ready = false;

static char s_node_id[NODE_ID_BUF_LEN];
static char s_topic_tele[TOPIC_BUF_LEN];
static char s_topic_inv[TOPIC_BUF_LEN];
static char s_topic_ack[TOPIC_BUF_LEN];
static char s_topic_cmd_node[TOPIC_BUF_LEN];
static char s_topic_cmd_group[TOPIC_BUF_LEN];

typedef struct {
    bool ok;
    uint32_t capture_ms;
    size_t jpeg_len;
    uint16_t width;
    uint16_t height;
} camera_capture_stats_t;

typedef struct {
    const uint8_t *data;
    size_t len;
    size_t pos;
} cbor_reader_t;

typedef struct {
    uint8_t *data;
    size_t cap;
    size_t pos;
} cbor_writer_t;

typedef struct {
    bool parsed;
    bool has_op;
    int64_t op;
    bool has_ack_mid;
    uint8_t ack_mid[32];
    size_t ack_mid_len;
    bool has_nid;
    char nid[48];
    bool has_period_ms;
    uint32_t period_ms;
} command_frame_t;

static bool publish_telemetry(void);

static const char *wifi_auth_mode_to_str(wifi_auth_mode_t mode) {
    switch (mode) {
        case WIFI_AUTH_OPEN:
            return "OPEN";
        case WIFI_AUTH_WEP:
            return "WEP";
        case WIFI_AUTH_WPA_PSK:
            return "WPA_PSK";
        case WIFI_AUTH_WPA2_PSK:
            return "WPA2_PSK";
        case WIFI_AUTH_WPA_WPA2_PSK:
            return "WPA_WPA2_PSK";
        case WIFI_AUTH_WPA2_ENTERPRISE:
            return "WPA2_ENTERPRISE";
        case WIFI_AUTH_WPA3_PSK:
            return "WPA3_PSK";
        case WIFI_AUTH_WPA2_WPA3_PSK:
            return "WPA2_WPA3_PSK";
        case WIFI_AUTH_WAPI_PSK:
            return "WAPI_PSK";
        case WIFI_AUTH_OWE:
            return "OWE";
        default:
            return "UNKNOWN";
    }
}

static const char *wifi_reason_to_str(uint8_t reason) {
    switch ((wifi_err_reason_t) reason) {
        case WIFI_REASON_AUTH_EXPIRE:
            return "AUTH_EXPIRE";
        case WIFI_REASON_AUTH_FAIL:
            return "AUTH_FAIL";
        case WIFI_REASON_ASSOC_FAIL:
            return "ASSOC_FAIL";
        case WIFI_REASON_HANDSHAKE_TIMEOUT:
            return "HANDSHAKE_TIMEOUT";
        case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
            return "4WAY_HANDSHAKE_TIMEOUT";
        case WIFI_REASON_CONNECTION_FAIL:
            return "CONNECTION_FAIL";
        case WIFI_REASON_NO_AP_FOUND:
            return "NO_AP_FOUND";
        case WIFI_REASON_NO_AP_FOUND_W_COMPATIBLE_SECURITY:
            return "NO_AP_FOUND_W_COMPATIBLE_SECURITY";
        case WIFI_REASON_NO_AP_FOUND_IN_AUTHMODE_THRESHOLD:
            return "NO_AP_FOUND_IN_AUTHMODE_THRESHOLD";
        case WIFI_REASON_NO_AP_FOUND_IN_RSSI_THRESHOLD:
            return "NO_AP_FOUND_IN_RSSI_THRESHOLD";
        case WIFI_REASON_BEACON_TIMEOUT:
            return "BEACON_TIMEOUT";
        case WIFI_REASON_ASSOC_LEAVE:
            return "ASSOC_LEAVE";
        case WIFI_REASON_ROAMING:
            return "ROAMING";
        default:
            return "UNMAPPED";
    }
}

static const char *wifi_reason_hint(uint8_t reason) {
    switch ((wifi_err_reason_t) reason) {
        case WIFI_REASON_AUTH_FAIL:
        case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
        case WIFI_REASON_HANDSHAKE_TIMEOUT:
            return "Check Wi-Fi password/security mode. WPA3-only APs can fail with ESP32 STA.";
        case WIFI_REASON_NO_AP_FOUND:
            return "AP not seen. Verify SSID spelling, 2.4GHz enabled, and signal strength.";
        case WIFI_REASON_NO_AP_FOUND_W_COMPATIBLE_SECURITY:
        case WIFI_REASON_NO_AP_FOUND_IN_AUTHMODE_THRESHOLD:
            return "AP security does not match station auth threshold. Lower threshold or use WPA2/WPA2-WPA3.";
        case WIFI_REASON_NO_AP_FOUND_IN_RSSI_THRESHOLD:
        case WIFI_REASON_BEACON_TIMEOUT:
            return "Signal is weak/unstable. Move closer, improve power, or reduce channel congestion.";
        default:
            return "";
    }
}

static void build_node_identity_and_topics(void) {
    uint8_t mac[6] = {0};
    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_WIFI_STA));

    snprintf(
        s_node_id,
        sizeof(s_node_id),
        "NID_%02X%02X%02X%02X%02X%02X",
        mac[0],
        mac[1],
        mac[2],
        mac[3],
        mac[4],
        mac[5]);

    snprintf(s_topic_tele, sizeof(s_topic_tele), "tele/%s/v1", s_node_id);
    snprintf(s_topic_inv, sizeof(s_topic_inv), "inv/%s/v1", s_node_id);
    snprintf(s_topic_ack, sizeof(s_topic_ack), "ack/%s/v1", s_node_id);
    snprintf(s_topic_cmd_node, sizeof(s_topic_cmd_node), "cmnd/node/%s/v1", s_node_id);
    snprintf(s_topic_cmd_group, sizeof(s_topic_cmd_group), "cmnd/group/%s/v1", NODE_GROUP);
}

static uint32_t uptime_ms(void) {
    return (uint32_t) (esp_timer_get_time() / 1000ULL);
}

static bool cbor_read_n(cbor_reader_t *reader, uint8_t *out, size_t n) {
    if (reader->pos + n > reader->len) {
        return false;
    }
    if (out != NULL) {
        memcpy(out, reader->data + reader->pos, n);
    }
    reader->pos += n;
    return true;
}

static bool cbor_read_head(cbor_reader_t *reader, uint8_t *major, uint8_t *ai) {
    uint8_t head = 0;
    if (!cbor_read_n(reader, &head, 1)) {
        return false;
    }
    *major = (head >> 5U) & 0x07U;
    *ai = head & 0x1FU;
    return true;
}

static bool cbor_read_ai_value(cbor_reader_t *reader, uint8_t ai, uint64_t *value) {
    uint8_t b = 0;
    uint8_t buf[8] = {0};

    if (ai < 24U) {
        *value = ai;
        return true;
    }
    if (ai == 24U) {
        if (!cbor_read_n(reader, &b, 1)) {
            return false;
        }
        *value = b;
        return true;
    }
    if (ai == 25U) {
        if (!cbor_read_n(reader, buf, 2)) {
            return false;
        }
        *value = ((uint64_t) buf[0] << 8U) | (uint64_t) buf[1];
        return true;
    }
    if (ai == 26U) {
        if (!cbor_read_n(reader, buf, 4)) {
            return false;
        }
        *value = ((uint64_t) buf[0] << 24U) | ((uint64_t) buf[1] << 16U) | ((uint64_t) buf[2] << 8U) |
                 (uint64_t) buf[3];
        return true;
    }
    if (ai == 27U) {
        if (!cbor_read_n(reader, buf, 8)) {
            return false;
        }
        *value = ((uint64_t) buf[0] << 56U) | ((uint64_t) buf[1] << 48U) | ((uint64_t) buf[2] << 40U) |
                 ((uint64_t) buf[3] << 32U) | ((uint64_t) buf[4] << 24U) | ((uint64_t) buf[5] << 16U) |
                 ((uint64_t) buf[6] << 8U) | (uint64_t) buf[7];
        return true;
    }
    return false;
}

static bool cbor_read_int64(cbor_reader_t *reader, int64_t *out) {
    uint8_t major = 0;
    uint8_t ai = 0;
    uint64_t v = 0;
    if (!cbor_read_head(reader, &major, &ai)) {
        return false;
    }
    if (!cbor_read_ai_value(reader, ai, &v)) {
        return false;
    }
    if (major == 0U) {
        if (v > INT64_MAX) {
            return false;
        }
        *out = (int64_t) v;
        return true;
    }
    if (major == 1U) {
        if (v > INT64_MAX) {
            return false;
        }
        *out = -1 - (int64_t) v;
        return true;
    }
    return false;
}

static bool cbor_read_map_len(cbor_reader_t *reader, uint64_t *len) {
    uint8_t major = 0;
    uint8_t ai = 0;
    if (!cbor_read_head(reader, &major, &ai)) {
        return false;
    }
    if (major != 5U) {
        return false;
    }
    return cbor_read_ai_value(reader, ai, len);
}

static bool cbor_read_text(cbor_reader_t *reader, char *out, size_t out_cap) {
    uint8_t major = 0;
    uint8_t ai = 0;
    uint64_t len = 0;
    if (!cbor_read_head(reader, &major, &ai)) {
        return false;
    }
    if (major != 3U) {
        return false;
    }
    if (!cbor_read_ai_value(reader, ai, &len)) {
        return false;
    }
    if (reader->pos + len > reader->len || len + 1U > out_cap) {
        return false;
    }
    memcpy(out, reader->data + reader->pos, (size_t) len);
    out[len] = '\0';
    reader->pos += (size_t) len;
    return true;
}

static bool cbor_read_bytes(cbor_reader_t *reader, uint8_t *out, size_t out_cap, size_t *out_len) {
    uint8_t major = 0;
    uint8_t ai = 0;
    uint64_t len = 0;
    if (!cbor_read_head(reader, &major, &ai)) {
        return false;
    }
    if (major != 2U) {
        return false;
    }
    if (!cbor_read_ai_value(reader, ai, &len)) {
        return false;
    }
    if (reader->pos + len > reader->len || len > out_cap) {
        return false;
    }
    memcpy(out, reader->data + reader->pos, (size_t) len);
    reader->pos += (size_t) len;
    *out_len = (size_t) len;
    return true;
}

static bool cbor_skip_item(cbor_reader_t *reader);

static bool cbor_skip_container(cbor_reader_t *reader, uint64_t count, bool is_map) {
    const uint64_t items = is_map ? (count * 2U) : count;
    for (uint64_t i = 0; i < items; i++) {
        if (!cbor_skip_item(reader)) {
            return false;
        }
    }
    return true;
}

static bool cbor_skip_item(cbor_reader_t *reader) {
    uint8_t major = 0;
    uint8_t ai = 0;
    uint64_t len = 0;
    if (!cbor_read_head(reader, &major, &ai)) {
        return false;
    }
    if (!cbor_read_ai_value(reader, ai, &len)) {
        return false;
    }

    if (major == 0U || major == 1U) {
        return true;
    }
    if (major == 2U || major == 3U) {
        return cbor_read_n(reader, NULL, (size_t) len);
    }
    if (major == 4U) {
        return cbor_skip_container(reader, len, false);
    }
    if (major == 5U) {
        return cbor_skip_container(reader, len, true);
    }
    if (major == 6U) {
        return cbor_skip_item(reader);
    }
    if (major == 7U) {
        return true;
    }
    return false;
}

static bool parse_period_args(cbor_reader_t *reader, command_frame_t *frame) {
    uint64_t count = 0;
    if (!cbor_read_map_len(reader, &count)) {
        return false;
    }

    for (uint64_t i = 0; i < count; i++) {
        char key[32] = {0};
        if (!cbor_read_text(reader, key, sizeof(key))) {
            if (!cbor_skip_item(reader)) {
                return false;
            }
            if (!cbor_skip_item(reader)) {
                return false;
            }
            continue;
        }

        if (strcmp(key, "period_ms") == 0 || strcmp(key, "publish_period_ms") == 0) {
            int64_t value = 0;
            if (!cbor_read_int64(reader, &value)) {
                return false;
            }
            if (value >= 500 && value <= 3600000) {
                frame->has_period_ms = true;
                frame->period_ms = (uint32_t) value;
            }
            continue;
        }

        if (!cbor_skip_item(reader)) {
            return false;
        }
    }
    return true;
}

static bool parse_cbor_command(const uint8_t *payload, size_t payload_len, command_frame_t *out) {
    memset(out, 0, sizeof(*out));
    cbor_reader_t reader = {
        .data = payload,
        .len = payload_len,
        .pos = 0,
    };
    uint64_t count = 0;
    if (!cbor_read_map_len(&reader, &count)) {
        return false;
    }

    for (uint64_t i = 0; i < count; i++) {
        int64_t key = 0;
        if (!cbor_read_int64(&reader, &key)) {
            return false;
        }

        if (key == KINT_CMD) {
            int64_t op = 0;
            if (!cbor_read_int64(&reader, &op)) {
                return false;
            }
            out->has_op = true;
            out->op = op;
            continue;
        }
        if (key == KINT_MID) {
            size_t mid_len = 0;
            if (!cbor_read_bytes(&reader, out->ack_mid, sizeof(out->ack_mid), &mid_len)) {
                return false;
            }
            out->has_ack_mid = true;
            out->ack_mid_len = mid_len;
            continue;
        }
        if (key == KINT_NID) {
            if (!cbor_read_text(&reader, out->nid, sizeof(out->nid))) {
                return false;
            }
            out->has_nid = true;
            continue;
        }
        if (key == KINT_ARGS) {
            if (!parse_period_args(&reader, out)) {
                return false;
            }
            continue;
        }
        if (!cbor_skip_item(&reader)) {
            return false;
        }
    }

    out->parsed = true;
    return true;
}

static bool cbor_write_n(cbor_writer_t *writer, const uint8_t *bytes, size_t n) {
    if (writer->pos + n > writer->cap) {
        return false;
    }
    memcpy(writer->data + writer->pos, bytes, n);
    writer->pos += n;
    return true;
}

static bool cbor_write_head_and_value(cbor_writer_t *writer, uint8_t major, uint64_t value) {
    uint8_t tmp[9] = {0};
    size_t n = 0;
    if (value < 24U) {
        tmp[n++] = (uint8_t) ((major << 5U) | (uint8_t) value);
    } else if (value <= 0xFFU) {
        tmp[n++] = (uint8_t) ((major << 5U) | 24U);
        tmp[n++] = (uint8_t) value;
    } else if (value <= 0xFFFFU) {
        tmp[n++] = (uint8_t) ((major << 5U) | 25U);
        tmp[n++] = (uint8_t) ((value >> 8U) & 0xFFU);
        tmp[n++] = (uint8_t) (value & 0xFFU);
    } else if (value <= 0xFFFFFFFFULL) {
        tmp[n++] = (uint8_t) ((major << 5U) | 26U);
        tmp[n++] = (uint8_t) ((value >> 24U) & 0xFFU);
        tmp[n++] = (uint8_t) ((value >> 16U) & 0xFFU);
        tmp[n++] = (uint8_t) ((value >> 8U) & 0xFFU);
        tmp[n++] = (uint8_t) (value & 0xFFU);
    } else {
        tmp[n++] = (uint8_t) ((major << 5U) | 27U);
        tmp[n++] = (uint8_t) ((value >> 56U) & 0xFFU);
        tmp[n++] = (uint8_t) ((value >> 48U) & 0xFFU);
        tmp[n++] = (uint8_t) ((value >> 40U) & 0xFFU);
        tmp[n++] = (uint8_t) ((value >> 32U) & 0xFFU);
        tmp[n++] = (uint8_t) ((value >> 24U) & 0xFFU);
        tmp[n++] = (uint8_t) ((value >> 16U) & 0xFFU);
        tmp[n++] = (uint8_t) ((value >> 8U) & 0xFFU);
        tmp[n++] = (uint8_t) (value & 0xFFU);
    }
    return cbor_write_n(writer, tmp, n);
}

static bool cbor_write_int(cbor_writer_t *writer, int64_t value) {
    if (value >= 0) {
        return cbor_write_head_and_value(writer, 0U, (uint64_t) value);
    }
    return cbor_write_head_and_value(writer, 1U, (uint64_t) (-1 - value));
}

static bool cbor_write_text(cbor_writer_t *writer, const char *value) {
    const size_t len = strlen(value);
    return cbor_write_head_and_value(writer, 3U, (uint64_t) len) &&
           cbor_write_n(writer, (const uint8_t *) value, len);
}

static bool cbor_write_bytes(cbor_writer_t *writer, const uint8_t *value, size_t len) {
    return cbor_write_head_and_value(writer, 2U, (uint64_t) len) && cbor_write_n(writer, value, len);
}

static bool cbor_write_bool(cbor_writer_t *writer, bool value) {
    const uint8_t b = value ? 0xF5 : 0xF4;
    return cbor_write_n(writer, &b, 1);
}

static int32_t wifi_rssi(void) {
    wifi_ap_record_t ap = {0};
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        return ap.rssi;
    }
    return 0;
}

static void add_channel_number(cJSON *channels, const char *cid, const char *unit, double value, uint32_t t_up_ms) {
    cJSON *channel = cJSON_CreateObject();
    cJSON_AddStringToObject(channel, KC_CID, cid);
    cJSON_AddStringToObject(channel, KC_UNIT, unit);
    cJSON_AddNumberToObject(channel, KC_VAL, value);
    cJSON_AddNumberToObject(channel, KC_TUP, (double) t_up_ms);
    cJSON_AddItemToArray(channels, channel);
}

static void add_channel_bool(cJSON *channels, const char *cid, bool value, uint32_t t_up_ms) {
    cJSON *channel = cJSON_CreateObject();
    cJSON_AddStringToObject(channel, KC_CID, cid);
    cJSON_AddStringToObject(channel, KC_UNIT, "bool");
    cJSON_AddBoolToObject(channel, KC_VAL, value);
    cJSON_AddNumberToObject(channel, KC_TUP, (double) t_up_ms);
    cJSON_AddItemToArray(channels, channel);
}

#if APP_HAS_CAMERA
static bool init_camera(void) {
    camera_config_t config = {
        .pin_pwdn = 32,
        .pin_reset = -1,
        .pin_xclk = 0,
        .pin_sccb_sda = 26,
        .pin_sccb_scl = 27,
        .pin_d7 = 35,
        .pin_d6 = 34,
        .pin_d5 = 39,
        .pin_d4 = 36,
        .pin_d3 = 21,
        .pin_d2 = 19,
        .pin_d1 = 18,
        .pin_d0 = 5,
        .pin_vsync = 25,
        .pin_href = 23,
        .pin_pclk = 22,
        .xclk_freq_hz = 20000000,
        .ledc_timer = LEDC_TIMER_0,
        .ledc_channel = LEDC_CHANNEL_0,
        .pixel_format = PIXFORMAT_JPEG,
        .frame_size = FRAMESIZE_QQVGA,
        .jpeg_quality = 15,
        .fb_count = 1,
        .fb_location = CAMERA_FB_IN_DRAM,
        .grab_mode = CAMERA_GRAB_WHEN_EMPTY,
    };

    if (psramFound()) {
        config.frame_size = FRAMESIZE_QVGA;
        config.jpeg_quality = 12;
        config.fb_count = 2;
        config.fb_location = CAMERA_FB_IN_PSRAM;
    }

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "esp_camera_init failed: %s", esp_err_to_name(err));
        return false;
    }

    sensor_t *sensor = esp_camera_sensor_get();
    if (sensor != NULL) {
        sensor->set_brightness(sensor, 1);
        sensor->set_saturation(sensor, -1);
    }

    ESP_LOGI(TAG, "Camera ready");
    return true;
}

static camera_capture_stats_t capture_camera(void) {
    camera_capture_stats_t stats = {0};
    const int64_t start_us = esp_timer_get_time();
    camera_fb_t *fb = esp_camera_fb_get();
    const int64_t elapsed_us = esp_timer_get_time() - start_us;

    stats.capture_ms = (uint32_t) (elapsed_us / 1000ULL);
    if (fb == NULL) {
        return stats;
    }

    stats.ok = true;
    stats.jpeg_len = fb->len;
    stats.width = fb->width;
    stats.height = fb->height;
    esp_camera_fb_return(fb);
    return stats;
}
#else
static bool init_camera(void) {
    ESP_LOGW(TAG, "esp_camera.h not found in this build; running in no-camera mode");
    return false;
}

static camera_capture_stats_t capture_camera(void) {
    camera_capture_stats_t stats = {0};
    return stats;
}
#endif

static void append_network_info(cJSON *root) {
    cJSON *net = cJSON_CreateObject();
    cJSON_AddStringToObject(net, "ssid", WIFI_SSID);
    cJSON_AddNumberToObject(net, "rssi", wifi_rssi());

    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (netif != NULL) {
        esp_netif_ip_info_t ip = {0};
        if (esp_netif_get_ip_info(netif, &ip) == ESP_OK) {
            char ip_buf[16];
            snprintf(ip_buf, sizeof(ip_buf), IPSTR, IP2STR(&ip.ip));
            cJSON_AddStringToObject(net, "ip", ip_buf);
        }
    }

    cJSON_AddItemToObject(root, K_NET, net);
}

static bool mqtt_publish_json(const char *topic, cJSON *root, int qos) {
    if (s_mqtt_client == NULL || !s_mqtt_connected) {
        return false;
    }

    char *payload = cJSON_PrintUnformatted(root);
    if (payload == NULL) {
        return false;
    }

    int msg_id = esp_mqtt_client_publish(s_mqtt_client, topic, payload, 0, qos, 0);
    free(payload);
    return msg_id >= 0;
}

static bool mqtt_publish_binary(const char *topic, const uint8_t *payload, size_t len, int qos) {
    if (s_mqtt_client == NULL || !s_mqtt_connected) {
        return false;
    }
    int msg_id = esp_mqtt_client_publish(s_mqtt_client, topic, (const char *) payload, (int) len, qos, 0);
    return msg_id >= 0;
}

static bool publish_ack_cbor(
    const uint8_t *ack_mid,
    size_t ack_mid_len,
    int rc,
    const char *detail,
    bool include_reboot,
    bool reboot_required) {
    uint8_t payload[256] = {0};
    cbor_writer_t writer = {
        .data = payload,
        .cap = sizeof(payload),
        .pos = 0,
    };

    uint64_t map_items = 7;
    if (detail != NULL && detail[0] != '\0') {
        map_items++;
    }
    if (include_reboot) {
        map_items++;
    }

    if (!cbor_write_head_and_value(&writer, 5U, map_items)) {
        return false;
    }

    if (!cbor_write_int(&writer, KINT_VER) || !cbor_write_int(&writer, 1) || !cbor_write_int(&writer, KINT_TYP) ||
        !cbor_write_int(&writer, MSG_TYPE_ACK) || !cbor_write_int(&writer, KINT_NID) ||
        !cbor_write_text(&writer, s_node_id) || !cbor_write_int(&writer, KINT_SEQ) ||
        !cbor_write_int(&writer, (int64_t) ++s_seq) || !cbor_write_int(&writer, KINT_TUP) ||
        !cbor_write_int(&writer, (int64_t) uptime_ms()) || !cbor_write_int(&writer, KINT_ACK_MID) ||
        !cbor_write_bytes(&writer, ack_mid, ack_mid_len) || !cbor_write_int(&writer, KINT_RC) ||
        !cbor_write_int(&writer, rc)) {
        return false;
    }

    if (detail != NULL && detail[0] != '\0') {
        if (!cbor_write_int(&writer, KINT_DETAIL) || !cbor_write_text(&writer, detail)) {
            return false;
        }
    }
    if (include_reboot) {
        if (!cbor_write_int(&writer, KINT_REBOOT) || !cbor_write_bool(&writer, reboot_required)) {
            return false;
        }
    }

    return mqtt_publish_binary(s_topic_ack, payload, writer.pos, 1);
}

static bool maybe_handle_cbor_command(const uint8_t *payload, int len) {
    command_frame_t frame = {0};
    if (!parse_cbor_command(payload, (size_t) len, &frame)) {
        return false;
    }

    int rc = ACK_RC_OK;
    const char *detail = "ok";
    bool do_reboot = false;

    if (frame.has_nid && strcmp(frame.nid, s_node_id) != 0) {
        rc = ACK_RC_WRONG_TARGET;
        detail = "wrong_target";
    } else if (!frame.has_op) {
        rc = ACK_RC_INVALID_SCHEMA;
        detail = "missing_op";
    } else if (frame.op == CMD_OP_READ_NOW) {
        (void) publish_telemetry();
        detail = "read_now";
    } else if (frame.op == CMD_OP_SET_PERIOD) {
        if (!frame.has_period_ms) {
            rc = ACK_RC_INVALID_SCHEMA;
            detail = "missing_period";
        } else {
            s_telemetry_period_ms = frame.period_ms;
            detail = "period_updated";
        }
    } else if (frame.op == CMD_OP_REBOOT) {
        detail = "rebooting";
        do_reboot = true;
    } else if (frame.op == CMD_OP_SET_CONFIG || frame.op == CMD_OP_OTA) {
        rc = ACK_RC_UNSUPPORTED_SENSOR;
        detail = "unsupported_op";
    } else {
        rc = ACK_RC_INVALID_SCHEMA;
        detail = "unknown_op";
    }

    const uint8_t empty_mid[1] = {0};
    const uint8_t *ack_mid = frame.has_ack_mid ? frame.ack_mid : empty_mid;
    const size_t ack_mid_len = frame.has_ack_mid ? frame.ack_mid_len : 0;
    (void) publish_ack_cbor(ack_mid, ack_mid_len, rc, detail, do_reboot, do_reboot);

    if (do_reboot && rc == ACK_RC_OK) {
        vTaskDelay(pdMS_TO_TICKS(250));
        esp_restart();
    }
    return true;
}

static bool publish_inventory(void) {
    cJSON *root = cJSON_CreateObject();
    const uint32_t now_ms = uptime_ms();

    cJSON_AddNumberToObject(root, K_VER, 1);
    cJSON_AddNumberToObject(root, K_TYP, MSG_TYPE_INVENTORY);
    cJSON_AddStringToObject(root, K_NID, s_node_id);
    cJSON_AddNumberToObject(root, K_SEQ, (double) ++s_seq);
    cJSON_AddNumberToObject(root, K_TUP, (double) now_ms);
    cJSON_AddStringToObject(root, K_HW, "esp32cam-ai-thinker");
#ifdef APP_VERSION
    cJSON_AddStringToObject(root, K_FW, APP_VERSION);
#else
    cJSON_AddStringToObject(root, K_FW, "esp32-cam-fw");
#endif

    cJSON *caps = cJSON_CreateArray();
    cJSON_AddItemToArray(caps, cJSON_CreateString("wifi"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("mqtt"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("telemetry"));
    if (s_camera_ready) {
        cJSON_AddItemToArray(caps, cJSON_CreateString("camera"));
    }
    cJSON_AddItemToObject(root, K_CAPS, caps);

    append_network_info(root);
    const bool ok = mqtt_publish_json(s_topic_inv, root, 1);
    cJSON_Delete(root);
    return ok;
}

static bool publish_telemetry(void) {
    cJSON *root = cJSON_CreateObject();
    const uint32_t now_ms = uptime_ms();

    cJSON_AddNumberToObject(root, K_VER, 1);
    cJSON_AddNumberToObject(root, K_TYP, MSG_TYPE_TELEMETRY);
    cJSON_AddStringToObject(root, K_NID, s_node_id);
    cJSON_AddNumberToObject(root, K_SEQ, (double) ++s_seq);
    cJSON_AddNumberToObject(root, K_TUP, (double) now_ms);

    cJSON *sensors = cJSON_CreateArray();
    cJSON *sensor = cJSON_CreateObject();
    cJSON_AddStringToObject(sensor, KS_SID, SENSOR_SID);
    cJSON_AddStringToObject(sensor, KS_STYPE, SENSOR_STYPE);

    cJSON *channels = cJSON_CreateArray();
    camera_capture_stats_t stats = capture_camera();
    add_channel_bool(channels, "capture_ok", stats.ok, now_ms);
    add_channel_bool(channels, "camera_ready", s_camera_ready, now_ms);
    add_channel_number(channels, "capture_ms", "ms", (double) stats.capture_ms, now_ms);
    add_channel_number(channels, "jpeg_len", "B", (double) stats.jpeg_len, now_ms);
    add_channel_number(channels, "frame_w", "px", (double) stats.width, now_ms);
    add_channel_number(channels, "frame_h", "px", (double) stats.height, now_ms);
    add_channel_number(channels, "wifi_rssi", "dBm", (double) wifi_rssi(), now_ms);
    add_channel_number(channels, "heap_free", "B", (double) esp_get_free_heap_size(), now_ms);

    cJSON_AddItemToObject(sensor, KS_CHANS, channels);
    cJSON_AddItemToArray(sensors, sensor);
    cJSON_AddItemToObject(root, K_SENSORS, sensors);

    const bool ok = mqtt_publish_json(s_topic_tele, root, 1);
    cJSON_Delete(root);
    return ok;
}

static void maybe_handle_json_command(const uint8_t *payload, int len) {
    char *buf = calloc((size_t) len + 1, 1);
    if (buf == NULL) {
        return;
    }
    memcpy(buf, payload, (size_t) len);
    cJSON *root = cJSON_Parse(buf);
    free(buf);
    if (root == NULL) {
        ESP_LOGW(TAG, "Command payload is not JSON; expected CBOR/JSON schema_v1 map");
        return;
    }

    const cJSON *op = cJSON_GetObjectItem(root, "30");
    if (cJSON_IsNumber(op) && (int) op->valuedouble == 14) {
        ESP_LOGI(TAG, "READ_NOW command accepted (JSON mode)");
        (void) publish_telemetry();
    } else if (cJSON_IsNumber(op) && (int) op->valuedouble == 11) {
        const cJSON *args = cJSON_GetObjectItem(root, "31");
        if (cJSON_IsObject(args)) {
            const cJSON *period = cJSON_GetObjectItem(args, "period_ms");
            if (!cJSON_IsNumber(period)) {
                period = cJSON_GetObjectItem(args, "publish_period_ms");
            }
            if (cJSON_IsNumber(period)) {
                const uint32_t candidate = (uint32_t) period->valuedouble;
                if (candidate >= 500U) {
                    s_telemetry_period_ms = candidate;
                    ESP_LOGI(TAG, "Telemetry period updated to %u ms", (unsigned) s_telemetry_period_ms);
                }
            }
        }
    } else if (cJSON_IsNumber(op) && (int) op->valuedouble == 13) {
        ESP_LOGI(TAG, "REBOOT command accepted (JSON mode)");
        esp_restart();
    } else {
        ESP_LOGW(TAG, "Unsupported JSON command op");
    }
    cJSON_Delete(root);
}

static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    (void) handler_args;
    (void) base;
    esp_mqtt_event_handle_t event = event_data;

    switch ((esp_mqtt_event_id_t) event_id) {
        case MQTT_EVENT_CONNECTED:
            s_mqtt_connected = true;
            ESP_LOGI(TAG, "MQTT connected");
            esp_mqtt_client_subscribe(s_mqtt_client, s_topic_cmd_node, 1);
            esp_mqtt_client_subscribe(s_mqtt_client, s_topic_cmd_group, 1);
            publish_inventory();
            break;
        case MQTT_EVENT_DISCONNECTED:
            s_mqtt_connected = false;
            ESP_LOGW(TAG, "MQTT disconnected");
            break;
        case MQTT_EVENT_DATA: {
            ESP_LOGI(TAG, "MQTT data on topic %.*s", event->topic_len, event->topic);
            if (!maybe_handle_cbor_command((const uint8_t *) event->data, event->data_len)) {
                maybe_handle_json_command((const uint8_t *) event->data, event->data_len);
            }
            break;
        }
        default:
            break;
    }
}

static void start_mqtt(void) {
#if ESP_IDF_VERSION_MAJOR >= 5
    const esp_mqtt_client_config_t cfg = {
        .broker.address.uri = MQTT_URI,
        .credentials.username = MQTT_USERNAME,
        .credentials.authentication.password = MQTT_PASSWORD,
        .session.keepalive = 60,
    };
#else
    const esp_mqtt_client_config_t cfg = {
        .uri = MQTT_URI,
        .username = MQTT_USERNAME,
        .password = MQTT_PASSWORD,
        .keepalive = 60,
    };
#endif

    s_mqtt_client = esp_mqtt_client_init(&cfg);
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(s_mqtt_client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL));
    ESP_ERROR_CHECK(esp_mqtt_client_start(s_mqtt_client));
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data) {
    (void) arg;

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "WiFi start: connecting to SSID '%s'", WIFI_SSID);
        esp_wifi_connect();
        return;
    }

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_CONNECTED) {
        const wifi_event_sta_connected_t *connected = (const wifi_event_sta_connected_t *) event_data;
        char ssid[33] = {0};
        size_t ssid_len = connected->ssid_len;
        if (ssid_len > sizeof(ssid) - 1U) {
            ssid_len = sizeof(ssid) - 1U;
        }
        memcpy(ssid, connected->ssid, ssid_len);
        ESP_LOGI(
            TAG,
            "WiFi associated: ssid=%s channel=%u auth=%s",
            ssid,
            (unsigned) connected->channel,
            wifi_auth_mode_to_str(connected->authmode));
        return;
    }

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *disc = (const wifi_event_sta_disconnected_t *) event_data;
        const char *reason_str = wifi_reason_to_str(disc->reason);
        const char *hint = wifi_reason_hint(disc->reason);
        xEventGroupClearBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
        ESP_LOGW(
            TAG,
            "WiFi disconnected: reason=%u (%s), rssi=%d; reconnecting",
            (unsigned) disc->reason,
            reason_str,
            (int) disc->rssi);
        if (hint[0] != '\0') {
            ESP_LOGW(TAG, "WiFi hint: %s", hint);
        }
        esp_wifi_connect();
        return;
    }

    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *got_ip = (const ip_event_got_ip_t *) event_data;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
        ESP_LOGI(
            TAG,
            "WiFi connected: ip=" IPSTR " gw=" IPSTR " netmask=" IPSTR,
            IP2STR(&got_ip->ip_info.ip),
            IP2STR(&got_ip->ip_info.gw),
            IP2STR(&got_ip->ip_info.netmask));
    }
}

static void init_wifi(void) {
    s_wifi_event_group = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL));

    wifi_config_t wifi_config = {0};
    strncpy((char *) wifi_config.sta.ssid, WIFI_SSID, sizeof(wifi_config.sta.ssid) - 1U);
    strncpy((char *) wifi_config.sta.password, WIFI_PASSWORD, sizeof(wifi_config.sta.password) - 1U);
    wifi_config.sta.threshold.authmode = WIFI_MIN_AUTHMODE;
    wifi_config.sta.pmf_cfg.capable = true;
    wifi_config.sta.pmf_cfg.required = false;
    ESP_LOGI(TAG, "WiFi config: ssid=%s min_auth=%s", WIFI_SSID, wifi_auth_mode_to_str(WIFI_MIN_AUTHMODE));

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
}

static void telemetry_task(void *arg) {
    (void) arg;
    TickType_t last_wake = xTaskGetTickCount();
    uint32_t elapsed_for_inv = 0;

    while (true) {
        const EventBits_t bits = xEventGroupGetBits(s_wifi_event_group);
        const bool wifi_ok = (bits & WIFI_CONNECTED_BIT) != 0;

        if (wifi_ok && s_mqtt_connected) {
            if (!publish_telemetry()) {
                ESP_LOGW(TAG, "Telemetry publish failed");
            }
            elapsed_for_inv += s_telemetry_period_ms;
            if (elapsed_for_inv >= INVENTORY_PERIOD_MS) {
                if (!publish_inventory()) {
                    ESP_LOGW(TAG, "Inventory publish failed");
                }
                elapsed_for_inv = 0;
            }
        }

        uint32_t period = s_telemetry_period_ms;
        if (period < 500U) {
            period = 500U;
        }
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(period));
    }
}

void app_main(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    if (strcmp(WIFI_SSID, "CHANGE_ME_SSID") == 0) {
        ESP_LOGW(TAG, "WIFI_SSID is still default; set build flags before deployment");
    }

    build_node_identity_and_topics();
    ESP_LOGI(TAG, "Node ID: %s", s_node_id);
    ESP_LOGI(TAG, "MQTT URI: %s", MQTT_URI);
    ESP_LOGI(TAG, "ACK topic: %s", s_topic_ack);

    init_wifi();
    s_camera_ready = init_camera();
    start_mqtt();

    xTaskCreate(telemetry_task, "telemetry_task", 6144, NULL, 5, NULL);
}
