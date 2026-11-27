/*
 * Da Vinci plotter controller for Arduino Nano ESP32 (ESP32-S3, 3.3 V logic).
 * Port of firmware/plotter/plotter.ino. Same line protocol over USB serial,
 * TCP port 23 and an HTTP jog page. Settings live in NVS via Preferences.
 * See README.md in this folder for the pin map, wiring and power.
 *
 * Pins are Nano ESP32 "Arduino pin" names (Pins_Arduino.h, arduino_nano_nora).
 * Strapping pins (GPIO0/3/45/46), USB (GPIO19/20) and UART0 (D0/D1) are unused.
 * ENABLE is active low and is driven HIGH (disabled) from the first line of
 * setup(). Add an external 10k pull-up to 3.3 V on the ENABLE net, because the
 * GPIO is high-Z during reset before setup() runs.
 */
#include <Arduino.h>
#include <string.h>
#include <ctype.h>
#include <stdlib.h>
#include <math.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WebServer.h>

static const uint8_t X_STEP=D2, X_DIR=D3, Y_STEP=D4, Y_DIR=D5, Z_STEP=D6, Z_DIR=D7;
static const uint8_t ENABLE_PIN=D8;                 // shared, active low, 3.3 V
static const uint8_t ENDSTOP_PIN[3]={D9,D10,D11};   // optical slot sensors, X Y Z
#define ENDSTOP_BLOCKED_LEVEL HIGH                  // open-collector + pull-up: beam blocked = HIGH
// Status LEDs: pin -> 220 ohm -> LED -> GND, so HIGH lights the LED.
// A3 (GPIO4) is used for alarm and D12 for heartbeat; A0-A2 are untouched.
static const uint8_t LED_READY=A0, LED_BUSY=A1, LED_ALARM=A3, LED_HEART=D12;

static const float MAX_FEED_MM_MIN=600.0f;
static const float MAX_Z_FEED_MM_MIN=120.0f;
static const uint8_t LINE_CAP=96;
#define ACCEL_STEPS_PER_S2 500.0f   // ponytail: same tunables as the Uno. ESP32 can go faster; measure first.
#define START_RATE_SPS 20.0f
#define MAX_STEP_RATE_SPS 1000.0f
#define JOG_FEED_MM_MIN 300.0f

struct Axis { uint8_t stepPin, dirPin; float stepsPerMm, minMm, maxMm, posMm; };
Axis ax[3]={{X_STEP,X_DIR,5.0f,0,0,0},{Y_STEP,Y_DIR,5.0f,0,0,0},{Z_STEP,Z_DIR,160.0f,0,0,0}};
bool armed=false, absoluteMode=true, penDown=false, endstopsOn=false;
bool positionSet[3]={false,false,false};
bool penUpSet=false, penDownSet=false;
float penUpZ=0, penDownZ=0;
bool calibrated=false, busy=false, errorLatched=false; // calibrated = max X/Y taught (M211)
unsigned long lastLineMs=0;

Preferences prefs;
Print *out=&Serial;      // where replies go for the command currently being processed
String wifiSsid, wifiPass;

// ---- input ports: USB serial and up to two TCP clients ----
struct Port { Stream *io; char buf[LINE_CAP]; uint8_t len; bool overflow; };
Port serialPort={nullptr,{0},0,false};
Port tcpPort[2]={{nullptr,{0},0,false},{nullptr,{0},0,false}};
WiFiClient tcpClient[2];
WiFiServer tcpServer(23);
WebServer httpServer(80);

// Collects one command's reply so the HTTP handler can return it.
class StrPrint : public Print {
public:
  String s;
  size_t write(uint8_t c) override { s += (char)c; return 1; }
  size_t write(const uint8_t *b, size_t n) override { for (size_t i=0;i<n;i++) s += (char)b[i]; return n; }
};

void replyError(const __FlashStringHelper *s) { errorLatched=true; out->print(F("error: ")); out->println(s); }
void replyError(const char *s) { errorLatched=true; out->print(F("error: ")); out->println(s); }

// Park every driver input at a known level and switch the drivers OFF.
void pinsFloat() {
  for (uint8_t i=0;i<3;i++) {
    digitalWrite(ax[i].stepPin,LOW); pinMode(ax[i].stepPin,OUTPUT);
    digitalWrite(ax[i].dirPin,LOW);  pinMode(ax[i].dirPin,OUTPUT);
  }
  digitalWrite(ENABLE_PIN,HIGH); pinMode(ENABLE_PIN,OUTPUT); // HIGH = disabled
}
void disarm() {
  armed=false; penDown=false; pinsFloat();
  for(uint8_t i=0;i<3;i++) positionSet[i]=false;
}
bool posKnown() { return positionSet[0]&&positionSet[1]&&positionSet[2]; }
void enableDrivers() {
  digitalWrite(ENABLE_PIN,HIGH); pinMode(ENABLE_PIN,OUTPUT);
  for(uint8_t i=0;i<3;i++){digitalWrite(ax[i].stepPin,LOW);pinMode(ax[i].stepPin,OUTPUT);digitalWrite(ax[i].dirPin,LOW);pinMode(ax[i].dirPin,OUTPUT);}
  digitalWrite(ENABLE_PIN,LOW);
  armed=true;
}
bool readyConfig() {
  for (uint8_t i=0;i<3;i++) if (ax[i].stepsPerMm<=0 || ax[i].maxMm<=ax[i].minMm) return false;
  return true;
}
bool endstopBlocked(uint8_t i) { return digitalRead(ENDSTOP_PIN[i])==ENDSTOP_BLOCKED_LEVEL; }

// ---- NVS calibration (replaces the Uno's EEPROM record) ----
float getValid(const char *key, float def, float lo, float hi) {
  float v=prefs.getFloat(key, def);
  return (v>=lo && v<=hi) ? v : def;
}
void loadCal() {
  ax[0].stepsPerMm=getValid("sx",5.0f,0.1f,2000.0f);
  ax[1].stepsPerMm=getValid("sy",5.0f,0.1f,2000.0f);
  ax[2].stepsPerMm=getValid("sz",160.0f,0.1f,2000.0f);
  ax[0].maxMm=getValid("mx",0.0f,0.0f,600.0f);
  ax[1].maxMm=getValid("my",0.0f,0.0f,600.0f);
  calibrated = prefs.getBool("cal",false) && ax[0].maxMm>0 && ax[1].maxMm>0;
  endstopsOn = prefs.getBool("esw",false);
}
void saveCal() {
  prefs.putFloat("sx",ax[0].stepsPerMm); prefs.putFloat("sy",ax[1].stepsPerMm); prefs.putFloat("sz",ax[2].stepsPerMm);
  prefs.putFloat("mx",ax[0].maxMm);      prefs.putFloat("my",ax[1].maxMm);
  prefs.putBool("cal",calibrated);
}

// Each LED is written only when its state changes, so this is cheap in the step loop.
void writeLed(uint8_t idx, uint8_t pin, bool on) {
  static uint8_t lastState[4]={2,2,2,2};
  if(lastState[idx]!=(on?1:0)) { digitalWrite(pin,on?HIGH:LOW); lastState[idx]=on?1:0; }
}
void updateLeds() {
  unsigned long now=millis();
  bool needCal=!calibrated||!posKnown();
  bool alarm=errorLatched||(needCal&&((now/250UL)&1UL));              // 2 Hz blink
  bool ready=!busy&&!errorLatched&&!needCal;                          // solid when idle
  bool moving=busy&&(((now-lastLineMs)<2000UL)?((now/125UL)&1UL):1UL); // 4 Hz while job lines stream
  bool heart=(now/500UL)&1UL;                                         // 1 Hz heartbeat
  writeLed(0,LED_READY,ready); writeLed(1,LED_BUSY,moving);
  writeLed(2,LED_ALARM,alarm); writeLed(3,LED_HEART,heart);
}

bool setParameter(const char *word) {
  const char *eq=strchr(word,'='); if (!eq) return false;
  char key[12]; size_t n=eq-word; if(n==0||n>=sizeof(key)) return false;
  memcpy(key,word,n); key[n]='\0'; char *end=0; float v=(float)strtod(eq+1,&end);
  if(end==eq+1||*end||!isfinite(v)) return false;
  if(!strcmp(key,"$XMM")) {if(v<0.1f||v>2000)return false; ax[0].stepsPerMm=v;}
  else if(!strcmp(key,"$YMM")) {if(v<0.1f||v>2000)return false; ax[1].stepsPerMm=v;}
  else if(!strcmp(key,"$ZMM")) {if(v<0.1f||v>2000)return false; ax[2].stepsPerMm=v;}
  else if(!strcmp(key,"$XMIN")) {if(v<0||v>600)return false; ax[0].minMm=v;}
  else if(!strcmp(key,"$XMAX")) {if(v<0||v>600)return false; ax[0].maxMm=v;}
  else if(!strcmp(key,"$YMIN")) {if(v<0||v>600)return false; ax[1].minMm=v;}
  else if(!strcmp(key,"$YMAX")) {if(v<0||v>600)return false; ax[1].maxMm=v;}
  else if(!strcmp(key,"$ZMIN")) {if(v<0||v>600)return false; ax[2].minMm=v;}
  else if(!strcmp(key,"$ZMAX")) {if(v<0||v>600)return false; ax[2].maxMm=v;}
  else if(!strcmp(key,"$XPOS")) {ax[0].posMm=v; positionSet[0]=true;}
  else if(!strcmp(key,"$YPOS")) {ax[1].posMm=v; positionSet[1]=true;}
  else if(!strcmp(key,"$ZPOS")) {ax[2].posMm=v; positionSet[2]=true;}
  else if(!strcmp(key,"$PENUP")) {if(v<0||v>600)return false; penUpZ=v; penUpSet=true;}
  else if(!strcmp(key,"$PENDOWN")) {if(v<0||v>600)return false; penDownZ=v; penDownSet=true;}
  else if(!strcmp(key,"$ENDSTOPS")) {if(v!=0.0f&&v!=1.0f)return false; endstopsOn=(v==1.0f); prefs.putBool("esw",endstopsOn);}
  else return false;
  return true;
}

// $SSID= and $PASS= are serial-only (never accepted from TCP or HTTP) and
// keep their case. Values run to end of line, so they may contain spaces.
bool prefixCI(const char *s, const char *p) {
  for(;*p;s++,p++) if(toupper((unsigned char)*s)!=*p) return false;
  return true;
}
void handleWifiParam(const char *line) {
  if(out!=(Print*)&Serial) { replyError(F("Wi-Fi credentials are serial-only")); return; }
  bool isSsid=(line[2]=='S');
  const char *val=line+6;
  size_t n=strlen(val);
  if(isSsid && (n<1||n>32)) { replyError(F("SSID must be 1-32 characters")); return; }
  if(!isSsid && n!=0 && (n<8||n>63)) { replyError(F("PASS must be empty or 8-63 characters")); return; }
  if(isSsid) { wifiSsid=val; prefs.putString("ssid",wifiSsid); }
  else       { wifiPass=val; prefs.putString("pass",wifiPass); }
  WiFi.begin(wifiSsid.c_str(), wifiPass.c_str()); // non-blocking; loop() retries every 15 s
  out->println(F("ok"));
}

// Streaming is stop-and-wait. Any bytes from any port during motion invalidate
// the manual origin and abort the move. Bytes are drained and answered on the
// port that sent them.
bool interrupted() {
  bool hit=false;
  Port *ports[3]={&serialPort,&tcpPort[0],&tcpPort[1]};
  for (uint8_t i=0;i<3;i++) {
    Port *p=ports[i];
    if(!p->io || !p->io->available()) continue;
    hit=true;
    while(p->io->available()) p->io->read();
    p->len=0; p->overflow=false;
    Print *prev=out; out=p->io;
    replyError(F("interrupted; restore position before rearming"));
    out=prev;
  }
  if(hit) disarm();
  return hit;
}

bool moveTo(float target[3], float feed, bool checkLimits) {
  if(!armed) { replyError(F("not armed")); return false; }
  if(feed<=0 || feed>MAX_FEED_MM_MIN) { replyError(F("feed out of range")); return false; }
  if(fabs(target[2]-ax[2].posMm)>0.0001f && feed>MAX_Z_FEED_MM_MIN) { replyError(F("Z feed out of range")); return false; }
  long dest[3], start[3], delta[3], ad[3]; long major=0;
  for(uint8_t i=0;i<3;i++) {
    if(checkLimits && (target[i]<ax[i].minMm-0.0001f || target[i]>ax[i].maxMm+0.0001f)) { replyError(F("travel limit")); return false; }
    dest[i]=lround(target[i]*ax[i].stepsPerMm); start[i]=lround(ax[i].posMm*ax[i].stepsPerMm);
    delta[i]=dest[i]-start[i]; ad[i]=labs(delta[i]); if(ad[i]>major) major=ad[i];
  }
  if(!major) { out->println(F("ok")); return true; }
  // Endstops are assumed at the minimum (origin) end: a blocked sensor stops
  // any axis that is moving toward it.
  bool towardStop[3]={false,false,false};
  for(uint8_t i=0;i<3;i++) towardStop[i]=(delta[i]<0);
  for(uint8_t i=0;i<3;i++) { digitalWrite(ax[i].stepPin,LOW); digitalWrite(ax[i].dirPin,delta[i]>=0?HIGH:LOW); }
  delayMicroseconds(5);
  float distance=sqrtf((target[0]-ax[0].posMm)*(target[0]-ax[0].posMm)+
                       (target[1]-ax[1].posMm)*(target[1]-ax[1].posMm)+
                       (target[2]-ax[2].posMm)*(target[2]-ax[2].posMm));
  float vC=(feed/60.0f)*(float)major/distance;
  if(vC>MAX_STEP_RATE_SPS) vC=MAX_STEP_RATE_SPS;
  if(vC<1.0f) vC=1.0f;
  float vS=(START_RATE_SPS<vC)?START_RATE_SPS:vC;
  float vS2=vS*vS;
  long accum[3]={0,0,0};
  busy=true;
  unsigned long tNext=micros();
  for(long s=0;s<major;s++) {
    if(interrupted()) { busy=false; return false; }
    if(endstopsOn) {
      for(uint8_t i=0;i<3;i++) if(ad[i] && towardStop[i] && endstopBlocked(i)) {
        disarm(); busy=false; replyError(F("endstop hit; position invalid")); return false;
      }
    }
    if(s>0) {
      long m=(s<major-s)?s:major-s;
      float v=sqrtf(vS2+2.0f*ACCEL_STEPS_PER_S2*(float)m);
      if(v>vC) v=vC;
      tNext+=(unsigned long)(1000000.0f/v);
    }
    // Absolute schedule from tNext, so compute time does not drift the steps.
    while((long)(micros()-tNext)<0) {
      // Sleep only when far from the target so the idle task still runs on
      // core 1 during slow starts (avoids the idle-task watchdog).
      if((long)(tNext-micros())>3000L) delay(1);
      if(interrupted()) { busy=false; return false; }
      updateLeds();
    }
    for(uint8_t i=0;i<3;i++) { accum[i]+=ad[i]; if(accum[i]>=major) { digitalWrite(ax[i].stepPin,HIGH); accum[i]-=major; } }
    delayMicroseconds(3); // pulse width >= 2 us
    for(uint8_t i=0;i<3;i++) digitalWrite(ax[i].stepPin,LOW);
  }
  busy=false;
  for(uint8_t i=0;i<3;i++) ax[i].posMm=target[i];
  out->println(F("ok")); return true;
}

void processLine(char *line) {
  errorLatched=false;
  // Wi-Fi credentials keep their case and may hold spaces, so handle them first.
  if(line[0]=='$' && (prefixCI(line,"$SSID=") || prefixCI(line,"$PASS="))) { handleWifiParam(line); return; }
  for(char *p=line;*p;p++) if(*p>='a'&&*p<='z') *p-=32;
  char *save; char *w=strtok_r(line," \t",&save); if(!w) return;
  if(!strcmp(w,"ARM")) {
    if(!readyConfig()||!penUpSet||!penDownSet||fabs(penUpZ-penDownZ)<0.01f||penUpZ<ax[2].minMm||penUpZ>ax[2].maxMm||penDownZ<ax[2].minMm||penDownZ>ax[2].maxMm) { replyError(F("configure measured steps/mm, travel and pen Z endpoints first")); return; }
    if(!positionSet[0]||!positionSet[1]||!positionSet[2]||ax[0].posMm<ax[0].minMm||ax[0].posMm>ax[0].maxMm||ax[1].posMm<ax[1].minMm||ax[1].posMm>ax[1].maxMm||ax[2].posMm<ax[2].minMm||ax[2].posMm>ax[2].maxMm) { replyError(F("set measured position first")); return; }
    if(!armed) enableDrivers();
    out->println(F("ok")); return;
  }
  if(!strcmp(w,"DISARM")) { disarm(); out->println(F("ok")); return; }
  if(w[0]=='$') {
    if(armed) { replyError(F("disarm before configuration")); return; }
    if(!setParameter(w)) { replyError(F("bad configuration")); return; }
    out->println(F("ok")); return;
  }
  if(!strcmp(w,"G21")) { out->println(F("ok")); return; }
  if(!strcmp(w,"G90")) { absoluteMode=true; out->println(F("ok")); return; }
  if(!strcmp(w,"G91")) { absoluteMode=false; out->println(F("ok")); return; }
  if(!strcmp(w,"LIMITS")) {
    out->print(F("ok X")); out->print(ax[0].maxMm,3);
    out->print(F(" Y")); out->print(ax[1].maxMm,3);
    out->print(F(" F")); out->println(MAX_FEED_MM_MIN,0); return;
  }
  if(!strcmp(w,"M5") || !strcmp(w,"M3")) {
    if(!armed) { replyError(F("not armed")); return; }
    if(!penUpSet||!penDownSet) { replyError(F("set measured pen Z endpoints")); return; }
    float t[3]={ax[0].posMm,ax[1].posMm,(!strcmp(w,"M3")?penDownZ:penUpZ)};
    if(moveTo(t,100.0f,true)) { penDown=!strcmp(w,"M3"); }
    return;
  }
  if(!strcmp(w,"M17")) { enableDrivers(); out->println(F("ok")); return; }
  if(!strcmp(w,"M18")) { disarm(); out->println(F("ok")); return; }
  if(!strcmp(w,"M119")) {
    out->print(F("ok ENDSTOPS=")); out->print(endstopsOn?1:0);
    for(uint8_t i=0;i<3;i++) { out->print(' '); out->print("XYZ"[i]); out->print(endstopBlocked(i)?1:0); }
    out->println(); return;
  }
  if(!strcmp(w,"WIFI")) {
    if(WiFi.status()==WL_CONNECTED) { out->print(F("ok WIFI connected IP ")); out->println(WiFi.localIP()); }
    else out->println(F("ok WIFI down"));
    return;
  }
  if(!strcmp(w,"M92")) {
    if(armed) { replyError(F("disarm before configuration")); return; }
    bool any=false;
    while((w=strtok_r(NULL," \t",&save))) {
      char c=w[0]; char *e; float v=(float)strtod(w+1,&e);
      uint8_t i=(c=='X')?0:(c=='Y')?1:(c=='Z')?2:3;
      if(i==3||e==w+1||*e||!isfinite(v)||v<0.1f||v>2000.0f) { replyError(F("M92 needs X/Y/Z steps per mm")); return; }
      ax[i].stepsPerMm=v; any=true;
    }
    if(!any) { replyError(F("M92 needs X/Y/Z steps per mm")); return; }
    saveCal(); out->println(F("ok")); return;
  }
  if(!strcmp(w,"G92") || !strcmp(w,"M210")) {
    bool m210=!strcmp(w,"M210"), any=m210;
    float v[3]={0,0,0}; bool has[3]={m210,m210,m210};
    while(!m210 && (w=strtok_r(NULL," \t",&save))) {
      char *e; float x=(float)strtod(w+1,&e);
      uint8_t i=(w[0]=='X')?0:(w[0]=='Y')?1:(w[0]=='Z')?2:3;
      if(i==3||e==w+1||*e||!isfinite(x)) { replyError(F("G92 takes X/Y/Z values")); return; }
      v[i]=x; has[i]=true; any=true;
    }
    if(!any) { replyError(F("G92 requires an axis")); return; }
    for(uint8_t i=0;i<3;i++) if(has[i]) { ax[i].posMm=v[i]; positionSet[i]=true; }
    out->println(F("ok")); return;
  }
  if(!strcmp(w,"M211")) {
    if(!positionSet[0]||!positionSet[1]) { replyError(F("set origin with M210 first")); return; }
    if(ax[0].posMm<=0||ax[1].posMm<=0||ax[0].posMm>600||ax[1].posMm>600) { replyError(F("max corner must be >0 and <=600 mm")); return; }
    ax[0].maxMm=ax[0].posMm; ax[1].maxMm=ax[1].posMm; calibrated=true;
    saveCal(); out->println(F("ok")); return;
  }
  if(!strcmp(w,"M114")) {
    out->print(F("ok X")); out->print(ax[0].posMm,3);
    out->print(F(" Y")); out->print(ax[1].posMm,3);
    out->print(F(" Z")); out->print(ax[2].posMm,3);
    out->println(posKnown()?F(" known"):F(" unknown")); return;
  }
  if(!strcmp(w,"M115")) {
    out->print(F("ok CAL=")); out->print(calibrated?1:0);
    out->print(F(" ORIGIN=")); out->print(posKnown()?1:0);
    out->print(F(" ARMED=")); out->print(armed?1:0);
    out->print(F(" MAX X")); out->print(ax[0].maxMm,3);
    out->print(F(" Y")); out->print(ax[1].maxMm,3);
    out->print(F(" Z")); out->print(ax[2].maxMm,3);
    out->print(F(" STEPS X")); out->print(ax[0].stepsPerMm,3);
    out->print(F(" Y")); out->print(ax[1].stepsPerMm,3);
    out->print(F(" Z")); out->println(ax[2].stepsPerMm,3); return;
  }
  if(!strcmp(w,"G4")) {
    if(!armed) { replyError(F("not armed")); return; }
    float dwell=0; bool haveP=false;
    while((w=strtok_r(NULL," \t",&save))) {
      if(w[0]!='P'||haveP) { replyError(F("G4 supports one P dwell in ms")); return; }
      char *e; dwell=(float)strtod(w+1,&e);
      if(e==w+1||*e||!isfinite(dwell)||dwell<0||dwell>10000) { replyError(F("dwell out of range")); return; }
      haveP=true;
    }
    if(!haveP) { replyError(F("G4 requires P milliseconds")); return; }
    unsigned long until=millis()+(unsigned long)dwell;
    while((long)(until-millis())>0) {
      if (interrupted()) return;
      updateLeds();
      delay(1);
    }
    out->println(F("ok")); return;
  }
  if(!strcmp(w,"G0") || !strcmp(w,"G1")) {
    bool rapid=!strcmp(w,"G0"), hasX=false,hasY=false,hasZ=false,hasF=false;
    float val[4]={0,0,0,0};
    while((w=strtok_r(NULL," \t",&save))) {
      char c=w[0]; char *e; float v=(float)strtod(w+1,&e);
      if(e==w+1||*e||!isfinite(v)) { replyError(F("bad word")); return; }
      if(c=='X'){val[0]=v;hasX=true;} else if(c=='Y'){val[1]=v;hasY=true;} else if(c=='Z'){val[2]=v;hasZ=true;} else if(c=='F'){val[3]=v;hasF=true;} else { replyError(F("unsupported word")); return; }
    }
    if(!hasX&&!hasY&&!hasZ) { replyError(F("G0/G1 requires an axis")); return; }
    float t[3]; for(uint8_t i=0;i<3;i++) t[i]=ax[i].posMm;
    if(hasX) t[0]=absoluteMode?val[0]:t[0]+val[0];
    if(hasY) t[1]=absoluteMode?val[1]:t[1]+val[1];
    if(hasZ) t[2]=absoluteMode?val[2]:t[2]+val[2];
    float feed=hasF?val[3]:(rapid?600.0f:300.0f);
    moveTo(t,feed,true); return;
  }
  if(!strcmp(w,"J")) {
    // Relative jog. Ignores travel limits, so it works before calibration.
    bool hasAxis=false; float d[3]={0,0,0}, feed=JOG_FEED_MM_MIN;
    while((w=strtok_r(NULL," \t",&save))) {
      char c=w[0]; char *e; float v=(float)strtod(w+1,&e);
      if(e==w+1||*e||!isfinite(v)) { replyError(F("bad word")); return; }
      if(c=='X'){d[0]=v;hasAxis=true;} else if(c=='Y'){d[1]=v;hasAxis=true;} else if(c=='Z'){d[2]=v;hasAxis=true;} else if(c=='F'){feed=v;} else { replyError(F("unsupported word")); return; }
    }
    if(!hasAxis) { replyError(F("J requires an axis")); return; }
    float t[3]; for(uint8_t i=0;i<3;i++) t[i]=ax[i].posMm+d[i];
    moveTo(t,feed,false); return;
  }
  replyError(F("unsupported command"));
}

// Feeds bytes from one port into its line buffer. '!' aborts immediately.
void feedPort(Port &p) {
  while(p.io->available()) {
    char c=(char)p.io->read();
    out=p.io;
    if(c=='!') {
      disarm();
      p.len=0; p.overflow=false;
      replyError(F("aborted; position invalid"));
      continue;
    }
    if(c=='\r') continue;
    if(c=='\n') {
      lastLineMs=millis();
      if(p.overflow) replyError(F("line too long"));
      else { p.buf[p.len]='\0'; processLine(p.buf); }
      p.len=0; p.overflow=false;
    } else if(!p.overflow) {
      if(p.len<LINE_CAP-1) p.buf[p.len++]=c; else p.overflow=true;
    }
  }
}

void acceptTcp() {
  WiFiClient c=tcpServer.available();
  if(!c) return;
  for(uint8_t i=0;i<2;i++) {
    if(!tcpClient[i].connected()) {
      tcpClient[i]=c; tcpPort[i].len=0; tcpPort[i].overflow=false;
      return;
    }
  }
  c.stop(); // ponytail: two TCP clients max
}

static const char PAGE[] PROGMEM = R"HTML(<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Da Vinci plotter</title>
<style>body{font-family:sans-serif;margin:16px;max-width:420px}button{font-size:1.1em;padding:10px;margin:3px;min-width:72px}pre{background:#eee;padding:8px;white-space:pre-wrap}</style></head>
<body><h3>Da Vinci plotter</h3>
<label>Step <select id="s"><option>0.5</option><option selected>1</option><option>5</option><option>10</option></select> mm</label>
<div><button onclick="j('Y',1,300)">Y+</button><br>
<button onclick="j('X',-1,300)">X-</button><button onclick="j('X',1,300)">X+</button><br>
<button onclick="j('Y',-1,300)">Y-</button><br>
<button onclick="j('Z',1,100)">Z+</button><button onclick="j('Z',-1,100)">Z-</button></div>
<p><button onclick="c('M3')">Pen down</button><button onclick="c('M5')">Pen up</button></p>
<p><button onclick="c('M17')">Enable</button><button onclick="c('M18')">Disable</button><button onclick="c('M115')">Status</button></p>
<form onsubmit="c(document.getElementById('raw').value);return false"><input id="raw" placeholder="raw command, e.g. M114"> <button>Send</button></form>
<pre id="log">ready</pre>
<script>
function show(t){document.getElementById('log').textContent=t}
function c(x){fetch('/cmd?c='+encodeURIComponent(x)).then(r=>r.text()).then(show).catch(()=>show('request failed'))}
function j(a,d,f){c('J '+a+(d*parseFloat(document.getElementById('s').value))+' F'+f)}
</script></body></html>)HTML";

void handleCmd() {
  String c=httpServer.arg("c");
  if(c.length()>=LINE_CAP) { httpServer.send(400,"text/plain","error: line too long\n"); return; }
  char buf[LINE_CAP]; strcpy(buf,c.c_str());
  StrPrint sp; Print *prev=out; out=&sp;
  processLine(buf);
  out=prev;
  httpServer.send(200,"text/plain", sp.s.length()? sp.s : String("ok\n"));
}

void setup() {
  pinMode(ENABLE_PIN,INPUT_PULLUP);  // pull-up = disabled until pinsFloat() drives HIGH
  pinsFloat();
  for(uint8_t i=0;i<3;i++) pinMode(ENDSTOP_PIN[i],INPUT_PULLUP);
  pinMode(LED_READY,OUTPUT); pinMode(LED_BUSY,OUTPUT); pinMode(LED_ALARM,OUTPUT); pinMode(LED_HEART,OUTPUT);
  Serial.begin(115200);
  serialPort.io=&Serial; out=&Serial;
  prefs.begin("plotter",false);
  loadCal();
  wifiSsid=prefs.getString("ssid",""); wifiPass=prefs.getString("pass","");
  WiFi.mode(WIFI_STA);
  if(wifiSsid.length()) WiFi.begin(wifiSsid.c_str(), wifiPass.c_str());
  tcpServer.begin(); tcpServer.setNoDelay(true);
  for(uint8_t i=0;i<2;i++) tcpPort[i].io=&tcpClient[i];
  httpServer.on("/", [](){ httpServer.send(200,"text/html",PAGE); });
  httpServer.on("/cmd", handleCmd);
  httpServer.begin();
  Serial.println(F("DaVinci plotter (ESP32) ready; unarmed; G21 G90; send measured config, then ARM, M5"));
}

void loop() {
  updateLeds();
  static unsigned long lastWifiTry=0;
  if(wifiSsid.length() && WiFi.status()!=WL_CONNECTED && millis()-lastWifiTry>15000UL) {
    lastWifiTry=millis(); WiFi.begin(wifiSsid.c_str(), wifiPass.c_str());
  }
  acceptTcp();
  feedPort(serialPort);
  feedPort(tcpPort[0]);
  feedPort(tcpPort[1]);
  httpServer.handleClient();
  out=&Serial;
}
