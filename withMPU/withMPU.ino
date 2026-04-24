#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <Wire.h>              // I2C for MPU6050

// ─── WiFi Credentials ──────────────────────────
const char* ssid     = "WIFI";
const char* password = "PASS";

// ─── HiveMQ CLOUD Cluster ──────────────────────
const char* mqtt_server = "indigobumble-39b622a1.a02.usw2.aws.hivemq.cloud";
const int   mqtt_port   = 8883;
const char* mqtt_user   = "hivemq.webclient.1776682804651";
const char* mqtt_pass   = "Up:#KhGRYou7g603Q>l<";
const char* mqtt_topic  = "esp32/heartrate";
const char* client_id   = "esp32-pulse-001";

// ─── Pin Definitions ───────────────────────────
#define PULSE_PIN        34
#define MPU6050_ADDR     0x68
#define SDA_PIN          21
#define SCL_PIN          22

// ─── Timing ────────────────────────────────────
#define SAMPLE_INTERVAL  2
#define BPM_CALC_TIME    5000

// ─── TLS Client ────────────────────────────────
WiFiClientSecure espClient;
PubSubClient     client(espClient);

// ─── BPM Variables ─────────────────────────────
int   threshold    = 2048;
bool  beatDetected = false;
unsigned long lastBeatTime = 0;
unsigned long lastPublish  = 0;
float currentBPM   = 0;

// ─── MPU6050 Variables ─────────────────────────
int16_t acc_x = 0, acc_y = 0, acc_z = 0;


// ═══════════════════════════════════════════════
// MPU6050 Functions (raw I2C — no library needed)
// ═══════════════════════════════════════════════

void mpu6050_write(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(reg);
    Wire.write(value);
    Wire.endTransmission();
}

void mpu6050_init() {
    // Wake up MPU6050 (clear sleep bit in PWR_MGMT_1)
    mpu6050_write(0x6B, 0x00);
    delay(100);

    // Set accelerometer range to ±2g (most sensitive)
    // Register 0x1C: ACCEL_CONFIG — Bits 4:3 = 00 → ±2g
    mpu6050_write(0x1C, 0x00);

    // Set DLPF to ~44 Hz bandwidth
    // Register 0x1A: CONFIG
    mpu6050_write(0x1A, 0x03);

    Serial.println("  MPU6050 initialized (±2g, 44Hz DLPF)");
}

bool mpu6050_check() {
    Wire.beginTransmission(MPU6050_ADDR);
    uint8_t error = Wire.endTransmission();
    return (error == 0);
}

void mpu6050_read_accel() {
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(0x3B);  // ACCEL_XOUT_H register
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)6, (uint8_t)true);

    if (Wire.available() == 6) {
        acc_x = (Wire.read() << 8) | Wire.read();
        acc_y = (Wire.read() << 8) | Wire.read();
        acc_z = (Wire.read() << 8) | Wire.read();

        // Scale to ~-128 to 128 (divide by 128 from ±2g raw range)
        acc_x = acc_x / 128;
        acc_y = acc_y / 128;
        acc_z = acc_z / 128;
    }
}


// ═══════════════════════════════════════════════
// WiFi & MQTT
// ═══════════════════════════════════════════════

void setup_wifi() {
    Serial.print("Connecting to WiFi");
    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\n✅ WiFi connected: " + WiFi.localIP().toString());
}

void reconnect_mqtt() {
    while (!client.connected()) {
        Serial.print("Connecting to HiveMQ Cloud...");
        if (client.connect(client_id, mqtt_user, mqtt_pass)) {
            Serial.println("✅ Connected to HiveMQ Cloud!");
            client.publish("esp32/status", "ESP32 Online");
        } else {
            Serial.print("❌ Failed, rc=");
            Serial.print(client.state());
            Serial.println(" | Retry in 5s");
            delay(5000);
        }
    }
}


// ═══════════════════════════════════════════════
// Setup
// ═══════════════════════════════════════════════

void setup() {
    Serial.begin(115200);
    Serial.println("\n════════════════════════════════════════");
    Serial.println("  SleepSense — ESP32 Sensor Hub");
    Serial.println("════════════════════════════════════════\n");

    // ── WiFi ───────────────────────────────────
    setup_wifi();

    // ── I2C & MPU6050 ──────────────────────────
    Wire.begin(SDA_PIN, SCL_PIN);
    delay(100);

    if (mpu6050_check()) {
        Serial.println("✅ MPU6050 found at 0x68");
        mpu6050_init();
    } else {
        Serial.println("❌ MPU6050 NOT found — check wiring!");
        Serial.println("   SDA → GPIO21, SCL → GPIO22, VCC → 3.3V, GND → GND");
    }

    // ── MQTT ───────────────────────────────────
    espClient.setInsecure();
    client.setServer(mqtt_server, mqtt_port);
    client.setKeepAlive(60);

    Serial.println("✅ Pulse Sensor Ready on GPIO34");
    Serial.println("✅ Publishing to: " + String(mqtt_topic));
    Serial.println();
}


// ═══════════════════════════════════════════════
// Main Loop
// ═══════════════════════════════════════════════

void loop() {
    if (!client.connected()) reconnect_mqtt();
    client.loop();

    // ── Read Pulse Sensor ──────────────────────
    int sensorValue = analogRead(PULSE_PIN);

    if (sensorValue > threshold && !beatDetected) {
        beatDetected = true;
        unsigned long now = millis();

        if (lastBeatTime > 0) {
            float interval_ms = now - lastBeatTime;
            currentBPM = 60000.0 / interval_ms;
        }
        lastBeatTime = now;
    }

    if (sensorValue < threshold - 200) {
        beatDetected = false;
    }

    // ── Publish every 5 seconds ────────────────
    if (millis() - lastPublish >= BPM_CALC_TIME) {

        // Read accelerometer before publishing
        mpu6050_read_accel();

        if (currentBPM > 40 && currentBPM < 200) {
            char payload[160];
            snprintf(payload, sizeof(payload),
                "{\"bpm\":%.1f,\"acc_x\":%d,\"acc_y\":%d,\"acc_z\":%d,\"device\":\"ESP32\",\"sensor\":\"HW-827+MPU6050\"}",
                currentBPM, acc_x, acc_y, acc_z);

            client.publish(mqtt_topic, payload);
            Serial.printf("📤 Published → %s\n    Payload: %s\n", mqtt_topic, payload);
        } else {
            // Still publish accelerometer data even if BPM is out of range
            char payload[160];
            snprintf(payload, sizeof(payload),
                "{\"bpm\":0,\"acc_x\":%d,\"acc_y\":%d,\"acc_z\":%d,\"device\":\"ESP32\",\"sensor\":\"HW-827+MPU6050\"}",
                acc_x, acc_y, acc_z);

            client.publish(mqtt_topic, payload);
            Serial.printf("⚠️  BPM=%.1f out of range — ACC=[%d, %d, %d]\n",
                currentBPM, acc_x, acc_y, acc_z);
        }

        lastPublish = millis();
    }

    delay(SAMPLE_INTERVAL);
}