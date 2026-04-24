# SleepSense AI

Real-time sleep stage prediction using accelerometer (MPU6050) and heart rate (HW-827) sensor data from an ESP32, streamed over MQTT to a live web dashboard.

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-1.8-orange?logo=scikitlearn&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi&logoColor=white)
![MQTT](https://img.shields.io/badge/MQTT-HiveMQ-yellow?logo=mqtt&logoColor=white)
![ESP32](https://img.shields.io/badge/ESP32-DevKit%20V1-red?logo=espressif&logoColor=white)

---

## Overview

SleepSense AI classifies sleep into **6 stages** in real time:

| Stage | Name | Description |
|-------|------|-------------|
| **P** | Pre-Sleep | Body is preparing for sleep |
| **W** | Wake | Conscious wakefulness |
| **N1** | Light Sleep | NREM Stage 1 — drifting off |
| **N2** | Moderate Sleep | NREM Stage 2 — sleep spindles |
| **N3** | Deep Sleep | NREM Stage 3 — slow-wave restorative |
| **R** | REM | Rapid eye movement — dreaming |

A Random Forest classifier (99.8% accuracy) was trained on polysomnography data from 2 participants (~528K samples), using accelerometer + heart rate features with rolling-window engineering.

---

## Architecture

```
┌─────────────────────────────────────┐
│           ESP32 DevKit V1           │
│  ┌───────────┐   ┌───────────────┐  │
│  │  MPU6050  │   │    HW-827     │  │
│  │ ACC X,Y,Z │   │   Heart Rate  │  │
│  └─────┬─────┘   └──────┬────────┘  │
│    I2C │          Analog │           │
│  (GPIO21/22)      (GPIO34)           │
└────────┼─────────────────┼───────────┘
         │    MQTT / TLS   │
         └────────┬────────┘
                  ▼
        ┌─────────────────┐
        │  HiveMQ Cloud   │
        │  (esp32/heartrate)│
        └────────┬────────┘
                 │ subscribe
                 ▼
        ┌─────────────────────────────┐
        │   realtime_predictor.py     │
        │   ┌───────────────────┐     │
        │   │  Sensor Buffer    │     │
        │   │  Feature Engine   │     │
        │   │  RF Classifier    │     │
        │   └────────┬──────────┘     │
        │   FastAPI  │  WebSocket     │
        └────────────┼────────────────┘
                     ▼
        ┌─────────────────────────────┐
        │      Live Dashboard         │
        │  BPM · Hypnogram · Accel    │
        │  Stage · Distribution       │
        └─────────────────────────────┘
```

---

## Project Structure

```
datasets/
├── README.md                        # This file
├── train_sleep_model.py             # Model training pipeline
├── realtime_predictor.py            # FastAPI backend + MQTT subscriber
├── sleep_model.joblib               # Trained Random Forest model (238 MB)
├── feature_config.json              # Feature names & stage colors
├── compressed_S002_whole_df.csv     # Training data — Subject 002
├── compressed_S003_whole_df.csv     # Data — Subject 003 (pre-sleep only)
├── compressed_S004_whole_df.csv     # Data — Subject 004 (pre-sleep only)
├── compressed_S005_whole_df.csv     # Data — Subject 005 (pre-sleep only)
├── compressed_S006_whole_df.csv     # Training data — Subject 006
├── participant_info.csv             # Subject demographics
└── dashboard/
    ├── index.html                   # Dashboard page
    ├── index.css                    # Dark glassmorphic theme
    └── app.js                       # WebSocket client + Chart.js charts
```

---

## Hardware Setup

### Components Required

| # | Component | Purpose |
|---|-----------|---------|
| 1 | ESP32 DevKit V1 | Microcontroller |
| 2 | MPU6050 (GY-521) | 3-axis accelerometer (I2C) |
| 3 | HW-827 pulse sensor | Optical heart rate (analog) |
| 4 | Breadboard + jumper wires | Prototyping |

### Wiring

**MPU6050 → ESP32 (I2C)**

| MPU6050 | ESP32 | Notes |
|---------|-------|-------|
| VCC | **3.3V** | ⚠️ NOT 5V |
| GND | GND | |
| SDA | **GPIO 21** | Default I2C data |
| SCL | **GPIO 22** | Default I2C clock |
| AD0 | GND | Sets address to 0x68 |

**HW-827 → ESP32 (Analog)**

| HW-827 | ESP32 | Notes |
|--------|-------|-------|
| VCC (red) | **3.3V** | |
| GND (black) | GND | |
| Signal (purple) | **GPIO 34** | ADC1 — input-only pin |

> **Important:** Use ADC1 pins (GPIO 32–39) for analog reads. ADC2 is disabled when WiFi is active.

### ESP32 Firmware

The Arduino sketch publishes sensor data to HiveMQ Cloud every 5 seconds:

```
Topic: esp32/heartrate
Payload: {"bpm":115.8,"acc_x":-121,"acc_y":5,"acc_z":-17,"device":"ESP32","sensor":"HW-827+MPU6050"}
```

Flash the `.ino` file from the `seg_overfit.zip/` directory using Arduino IDE with the ESP32 board package installed.

---

## Setup & Installation

### Prerequisites

- Python 3.10+
- pip

### 1. Install Dependencies

```bash
pip install scikit-learn pandas numpy joblib fastapi uvicorn paho-mqtt websockets
```

### 2. Train the Model (optional — pre-trained model included)

```bash
python train_sleep_model.py
```

Output:
```
Step 1: Loading datasets
  S002: 264,761 rows — 5 stages (P, W, N1, N2, R)
  S006: 263,622 rows — 5 stages (P, W, N1, N2, N3)
  Combined: 528,383 rows

Step 4: Training Random Forest classifier...
  ✅ Training complete in 59.3s

Step 5: Evaluation
  Overall Accuracy: 99.85%

Step 6: Saving model
  ✅ sleep_model.joblib (238 MB)
```

### 3. Run the Dashboard Server

```bash
python realtime_predictor.py
```

Open **http://localhost:8000** in your browser.

---

## Usage

### With ESP32 Hardware

1. Wire up MPU6050 + HW-827 as shown above
2. Flash the Arduino sketch to your ESP32
3. Run `python realtime_predictor.py`
4. Open http://localhost:8000
5. The dashboard will show live BPM, accelerometer data, and predicted sleep stage

### Without Hardware (Simulation)

1. Run `python realtime_predictor.py`
2. Open http://localhost:8000
3. Click **"Auto"** button (bottom-right) to inject simulated sensor data
4. After 64 samples (~50 seconds), predictions will start appearing

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serve dashboard |
| `GET` | `/api/status` | MQTT status, sample count, uptime |
| `GET` | `/api/history?n=200` | Last N prediction records |
| `POST` | `/api/simulate` | Inject a simulated sensor sample |
| `WS` | `/ws` | Real-time prediction stream |

### WebSocket Message Format

```json
{
  "ts": "2026-04-25T01:30:00.123456",
  "acc_x": -121,
  "acc_y": 5,
  "acc_z": -17,
  "hr": 72.5,
  "stage": "N2",
  "conf": 0.9412,
  "n": 128
}
```

---

## Model Details

### Features (44 total)

| Category | Features |
|----------|----------|
| Raw | `acc_x`, `acc_y`, `acc_z`, `hr`, `acc_mag` |
| Rolling mean/std/min/max | For each of the 5 raw signals (window=64) |
| Movement intensity | Std of acceleration magnitude over window |
| HR delta | Rate of change + rolling mean |
| Axis range | Max − min per axis over window |
| Lag features | Values at t−1, t−2, t−3, t−5, t−10 |
| Zero-crossing rate | Per accelerometer axis |

### Training Data

Only **S002** and **S006** were used (the others contain only pre-sleep labels):

| Class | Count | Percentage |
|-------|-------|------------|
| N2 | 153,205 | 29.0% |
| P | 140,758 | 26.6% |
| W | 126,502 | 23.9% |
| N1 | 45,233 | 8.6% |
| N3 | 42,270 | 8.0% |
| R | 20,415 | 3.9% |

Class imbalance handled via `class_weight="balanced"` in Random Forest.

### Performance

```
              precision    recall  f1-score   support
          N1       1.00      1.00      1.00      9047
          N2       1.00      1.00      1.00     30641
          N3       1.00      1.00      1.00      8454
           P       1.00      1.00      1.00     28152
           R       1.00      1.00      1.00      4083
           W       1.00      1.00      1.00     25300

    accuracy                           1.00    105677
```

---

## MQTT Configuration

| Setting | Value |
|---------|-------|
| Broker | `indigobumble-39b622a1.a02.usw2.aws.hivemq.cloud` |
| Port | `8883` (TLS) |
| Topic | `esp32/heartrate` |
| Protocol | MQTT v3.1.1 |

Credentials are set in `realtime_predictor.py` and the Arduino sketch. Override with environment variables:

```bash
export HIVEMQ_USER="your_username"
export HIVEMQ_PASS="your_password"
```

---

## Tech Stack

- **ML**: scikit-learn (Random Forest), pandas, numpy
- **Backend**: FastAPI, uvicorn, paho-mqtt, WebSockets
- **Frontend**: Vanilla HTML/CSS/JS, Chart.js
- **Hardware**: ESP32, MPU6050, HW-827
- **Broker**: HiveMQ Cloud (MQTT over TLS)

---

## License

This project is for academic / research purposes.
