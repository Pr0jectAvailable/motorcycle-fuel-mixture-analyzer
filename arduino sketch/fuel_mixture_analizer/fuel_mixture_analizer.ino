#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_AHTX0.h>
#include <Adafruit_BMP280.h>

// ---------- Пины ----------
const int MQ2_PIN = A7;
const int MQ7_1_PIN = A6;
const int MQ7_2_PIN = A3;
const int RPM_PIN = A0;

const int HEATER_1_PIN = 6;
const int HEATER_2_PIN = 9;
const int LED_PIN = 13;

// ---------- Циклы нагрева MQ-7 ----------
const unsigned long CLEAN_TIME = 60000;
const unsigned long COOLDOWN_TIME = 10000;
const unsigned long MEASURE_TIME = CLEAN_TIME + COOLDOWN_TIME;
const int PWM_5V = 255;
const int PWM_1_4V = 74;

// ---------- Обороты ----------
const unsigned long RPM_TIMEOUT = 1000000;
volatile unsigned long lastPulseTime = 0;
volatile unsigned long pulsePeriod = 0;

// ---------- Состояния датчиков ----------
enum SensorState { MEASURE, CLEAN, COOLDOWN };
SensorState state1 = MEASURE, state2 = CLEAN;
unsigned long stateTimer1 = 0, stateTimer2 = 0;
bool isWarmedUp = false;

// ---------- Датчики среды ----------
Adafruit_AHTX0 aht;
Adafruit_BMP280 bmp;
bool ahtOk = false, bmpOk = false;

// ---------- Кольцевой буфер (минимум — 50 записей = 10 сек) ----------
struct DataPoint {
    uint16_t mq2;
    uint16_t mq7_1;
    uint16_t mq7_2;
    uint16_t rpm;       // rpm × 10
};

const int BUF_SIZE = 50;          // 50 × 8 байт = 400 байт
DataPoint buffer[BUF_SIZE];
int bufWriteIndex = 0;
int bufCount = 0;

void rpmInterrupt() {
    unsigned long now = micros();
    if (lastPulseTime != 0) pulsePeriod = now - lastPulseTime;
    lastPulseTime = now;
}

void setHeater(int pin, SensorState st) {
    analogWrite(pin, st == CLEAN ? PWM_5V : PWM_1_4V);
}

void setup() {
    Serial.begin(115200);
    delay(100);               // подождать стабилизации
    while (Serial.available()) Serial.read();  // очистить буфер
    delay(100);               // подождать стабилизации
    while (Serial.available()) Serial.read();  // очистить буфер
    pinMode(LED_PIN, OUTPUT);
    pinMode(HEATER_1_PIN, OUTPUT);
    pinMode(HEATER_2_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);
    analogWrite(HEATER_1_PIN, PWM_5V);
    analogWrite(HEATER_2_PIN, PWM_5V);
    attachInterrupt(digitalPinToInterrupt(RPM_PIN), rpmInterrupt, RISING);

    Wire.begin();
    if (aht.begin()) ahtOk = true;
    if (bmp.begin()) bmpOk = true;
}

void loop() {
    if (!isWarmedUp) {
        if (millis() >= 600000) {
            isWarmedUp = true;
            digitalWrite(LED_PIN, LOW);
            state1 = MEASURE;
            state2 = CLEAN;
            stateTimer1 = stateTimer2 = millis();
            setHeater(HEATER_1_PIN, state1);
            setHeater(HEATER_2_PIN, state2);
        } else {
            static unsigned long lastWarmupMsg = 0;
            if (millis() - lastWarmupMsg >= 1000) {
                lastWarmupMsg = millis();
                unsigned long remaining = (600000 - millis()) / 1000;
                Serial.print("WARMUP ");
                Serial.println(remaining);
            }
            if (Serial.available()) {
                String cmd = Serial.readStringUntil('\n');
                cmd.trim();
                if (cmd == "DOWNLOAD") sendBufferToPC();
                else if (cmd == "CLEAR") clearBuffer();
            }
            delay(50);
            return;
        }
    }

    // Чередование фаз MQ-7
    unsigned long now = millis();
    if (state1 == MEASURE && now - stateTimer1 >= MEASURE_TIME) {
        state1 = CLEAN; stateTimer1 = now; setHeater(HEATER_1_PIN, state1);
    } else if (state1 == CLEAN && now - stateTimer1 >= CLEAN_TIME) {
        state1 = COOLDOWN; stateTimer1 = now; setHeater(HEATER_1_PIN, state1);
    } else if (state1 == COOLDOWN && now - stateTimer1 >= COOLDOWN_TIME) {
        state1 = MEASURE; stateTimer1 = now; setHeater(HEATER_1_PIN, state1);
    }

    if (state2 == MEASURE && now - stateTimer2 >= MEASURE_TIME) {
        state2 = CLEAN; stateTimer2 = now; setHeater(HEATER_2_PIN, state2);
    } else if (state2 == CLEAN && now - stateTimer2 >= CLEAN_TIME) {
        state2 = COOLDOWN; stateTimer2 = now; setHeater(HEATER_2_PIN, state2);
    } else if (state2 == COOLDOWN && now - stateTimer2 >= COOLDOWN_TIME) {
        state2 = MEASURE; stateTimer2 = now; setHeater(HEATER_2_PIN, state2);
    }

    // Считывание датчиков
    uint16_t mq2 = analogRead(MQ2_PIN);
    uint16_t mq7_1 = analogRead(MQ7_1_PIN);
    uint16_t mq7_2 = analogRead(MQ7_2_PIN);

    float rpm = 0;
    noInterrupts();
    if (micros() - lastPulseTime < RPM_TIMEOUT && pulsePeriod > 0)
        rpm = 1.0 / (pulsePeriod / 1000000.0) * 60.0;
    interrupts();
    uint16_t rpm_scaled = (uint16_t)(rpm * 10);

    float temp = NAN, hum = NAN, press = NAN;
    if (ahtOk) {
        sensors_event_t humidity, temperature;
        aht.getEvent(&humidity, &temperature);
        temp = temperature.temperature;
        hum = humidity.relative_humidity;
    }
    if (bmpOk) press = bmp.readPressure() / 100.0F;

    // Отправка в Serial (реального времени)
    Serial.print(mq2);
    Serial.print(",");
    Serial.print(mq7_1);
    Serial.print(",");
    Serial.print(mq7_2);
    Serial.print(",");
    Serial.print(rpm);
    Serial.print(",");
    Serial.print(state1 == MEASURE ? "M" : (state1 == COOLDOWN ? "O" : "C"));
    Serial.print(",");
    Serial.print(state2 == MEASURE ? "M" : (state2 == COOLDOWN ? "O" : "C"));
    Serial.print(",");
    Serial.print(temp);
    Serial.print(",");
    Serial.print(hum);
    Serial.print(",");
    Serial.println(press);

    // Запись в буфер каждые 200 мс
    static unsigned long lastSave = 0;
    if (millis() - lastSave >= 200) {
        lastSave = millis();
        buffer[bufWriteIndex] = {mq2, mq7_1, mq7_2, rpm_scaled};
        bufWriteIndex = (bufWriteIndex + 1) % BUF_SIZE;
        if (bufCount < BUF_SIZE) bufCount++;
    }

    // Обработка команд
    if (Serial.available()) {
        String cmd = Serial.readStringUntil('\n');
        cmd.trim();
        if (cmd == "DOWNLOAD") sendBufferToPC();
        else if (cmd == "CLEAR") clearBuffer();
    }

    delay(50);
}

void sendBufferToPC() {
    Serial.println("DATA_START");
    int start = (bufWriteIndex - bufCount + BUF_SIZE) % BUF_SIZE;
    for (int i = 0; i < bufCount; i++) {
        int idx = (start + i) % BUF_SIZE;
        DataPoint &d = buffer[idx];
        Serial.print(d.mq2);
        Serial.print(",");
        Serial.print(d.mq7_1);
        Serial.print(",");
        Serial.print(d.mq7_2);
        Serial.print(",");
        Serial.println(d.rpm);
    }
    Serial.println("DATA_END");
}

void clearBuffer() {
    bufWriteIndex = 0;
    bufCount = 0;
}