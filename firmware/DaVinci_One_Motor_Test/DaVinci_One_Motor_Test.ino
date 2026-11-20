/* Da Vinci 3DP01 MOTOR R2 / Allegro A4988 + Elegoo Uno.
   Read the adjacent README.md before wiring. Uno USB power, driver VDD = 3.3 V.
   Header control positions B2-B6 MUST be verified before use.
   Full-step test: verified MS1/MS2/MS3 LOW; RESET and SLEEP HIGH.
   D8/ENA needs an external 10k pull-up to driver 3.3 V.
   Serial Monitor: 115200 baud. Send s for ONE short test; x aborts.
   Never reconnect a motor or change wiring while powered.
*/
#include <Arduino.h>

const byte STEP_PIN = 2;
const byte DIR_PIN = 5;
const byte ENABLE_PIN = 8; // LOW enables A4988 outputs

bool abortRequested() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'x' || c == 'X') return true;
  }
  return false;
}

bool waitChecked(unsigned long duration) {
  unsigned long started = millis();
  while (millis() - started < duration) {
    if (abortRequested()) return false;
    delay(1);
  }
  return true;
}

bool moveSteps(bool direction) {
  digitalWrite(DIR_PIN, direction ? HIGH : LOW);
  if (!waitChecked(10)) return false;
  for (byte i = 0; i < 40; ++i) {
    if (abortRequested()) return false;
    digitalWrite(STEP_PIN, HIGH);
    delayMicroseconds(5);
    digitalWrite(STEP_PIN, LOW);
    if (!waitChecked(50)) return false;
  }
  return true;
}

void setup() {
  digitalWrite(ENABLE_PIN, HIGH); // set latch before making it an output
  pinMode(ENABLE_PIN, OUTPUT);
  digitalWrite(STEP_PIN, LOW);
  pinMode(STEP_PIN, OUTPUT);
  digitalWrite(DIR_PIN, LOW);
  pinMode(DIR_PIN, OUTPUT);
  Serial.begin(115200);
  Serial.println(F("Outputs disabled. Send s for 40 steps each way; x aborts."));
}

void loop() {
  if (!Serial.available()) return;
  char command = Serial.read();
  if (command != 's' && command != 'S') return;
  while (Serial.available()) Serial.read();
  Serial.println(F("Single test starting."));
  digitalWrite(ENABLE_PIN, LOW);
  bool completed = waitChecked(10) && moveSteps(false)
                   && waitChecked(200) && moveSteps(true);
  digitalWrite(STEP_PIN, LOW);
  digitalWrite(ENABLE_PIN, HIGH);
  Serial.println(completed ? F("Done; outputs disabled.")
                           : F("Aborted; outputs disabled."));
  while (Serial.available()) Serial.read();
}
