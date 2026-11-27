/*
 * Da Vinci plotter controller for an Uno + CNC Shield V3 style STEP/DIR
 * interface. Pin mapping follows the repo's documented common mapping:
 * X 2/5, Y 3/6, Z 4/7, shared active-low ENABLE 8. The documentation says
 * this mapping is not electrically verified on every machine. Verify the
 * actual shield/driver wiring before connecting motor power.
 *
 * No settings are guessed: travel, steps/mm and pen endpoints must be
 * measured and entered while disarmed. $ settings are RAM-only and reset at
 * boot. Steps/mm (M92) and taught max X/Y (M211) are saved in EEPROM. The
 * origin is never saved: after each boot, jog to the origin and send M210.
 * Calibrate by jogging, see docs/hardware.md. Optional photo-interrupter
 * endstops on D9 (X), D10 (Y), D11 (Z), off by default ($ESEN). Status LEDs:
 * A0 ready, A1 busy, A2 alarm, D13 heartbeat. No servo is assumed.
 * Z is the bed axis.
 */
#include <Arduino.h>
#include <stdlib.h>
#include <math.h>
#include <EEPROM.h>

static const uint8_t X_STEP=2, X_DIR=5, Y_STEP=3, Y_DIR=6, Z_STEP=4, Z_DIR=7;
static const uint8_t ENABLE_PIN=8; // CNC Shield V3 common shared active-low enable
static const float MAX_FEED_MM_MIN=1500.0f;
static const float MAX_Z_FEED_MM_MIN=120.0f;
static const uint8_t LINE_CAP=96;
// Motion tunables (major-axis steps). Measure on the machine before raising.
#define ACCEL_STEPS_PER_S2 500.0f   // accel and decel rate
#define START_RATE_SPS 20.0f        // speed at move start and end (never a full stall)
#define MAX_STEP_RATE_SPS 1000.0f    // hard cap, same as the old 1 kstep/s limit
// Status LEDs: pin -> 220 ohm -> LED -> GND, so HIGH lights the LED.
static const uint8_t LED_READY=A0, LED_BUSY=A1, LED_ALARM=A2, LED_HEART=13;
#define JOG_FEED_MM_MIN 300.0f

struct Axis { uint8_t stepPin, dirPin; float stepsPerMm, minMm, maxMm, posMm; };
Axis ax[3]={{X_STEP,X_DIR,0,0,0,0},{Y_STEP,Y_DIR,0,0,0,0},{Z_STEP,Z_DIR,0,0,0,0}};
bool armed=false, absoluteMode=true, penDown=false;
bool positionSet[3]={false,false,false};
bool penUpSet=false, penDownSet=false;
float penUpZ=0, penDownZ=0;
char lineBuf[LINE_CAP]; uint8_t lineLen=0; bool lineOverflow=false;
bool calibrated=false, busy=false, errorLatched=false; // calibrated = max X/Y taught (M211)
unsigned long lastLineMs=0;

void replyError(const __FlashStringHelper *s) { errorLatched=true; Serial.print(F("error: ")); Serial.println(s); }
void replyError(const char *s) { errorLatched=true; Serial.print(F("error: ")); Serial.println(s); }
bool readyConfig() {
  for (uint8_t i=0;i<3;i++) if (ax[i].stepsPerMm<=0 || ax[i].maxMm<=ax[i].minMm) return false;
  return true;
}
// Park every driver input at a known level and switch the drivers OFF.
// Leaving them as floating INPUTs re-enabled the active-low ENABLE (a floating
// EN reads LOW = motors on) and let noise on the open STEP pins keep stepping,
// which made an abort look like the machine ignoring it.
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
// Calibration record in EEPROM, written only by M92 and M211.
struct CalRecord { uint8_t magic, version, calibrated; float stepsX, stepsY, stepsZ, maxX, maxY; };
const uint8_t CAL_MAGIC=0xDA, CAL_VERSION=1;
void saveCal() {
  CalRecord r={CAL_MAGIC,CAL_VERSION,(uint8_t)(calibrated?1:0),ax[0].stepsPerMm,ax[1].stepsPerMm,ax[2].stepsPerMm,ax[0].maxMm,ax[1].maxMm};
  EEPROM.put(0,r);
}
void loadCal() {
  CalRecord r; EEPROM.get(0,r);
  if(r.magic!=CAL_MAGIC||r.version!=CAL_VERSION) return;
  if(r.stepsX>=0.1f&&r.stepsX<=2000) ax[0].stepsPerMm=r.stepsX;
  if(r.stepsY>=0.1f&&r.stepsY<=2000) ax[1].stepsPerMm=r.stepsY;
  if(r.stepsZ>=0.1f&&r.stepsZ<=2000) ax[2].stepsPerMm=r.stepsZ;
  if(r.maxX>0&&r.maxX<=600) ax[0].maxMm=r.maxX;
  if(r.maxY>0&&r.maxY<=600) ax[1].maxMm=r.maxY;
  calibrated = r.calibrated==1 && ax[0].maxMm>0 && ax[1].maxMm>0;
}
// Optional endstops. Bit i of each mask is for axis i (0=X, 1=Y, 2=Z).
// ESDIR bit set = endstop lies in the + direction. Default 4: Z bottom is +Z.
static const uint8_t ES_PIN[3]={9,10,11};
const int ES_EE_ADDR=32; // after CalRecord (23 bytes)
struct EsRecord { uint8_t magic, en, inv, dir; };
const uint8_t ES_MAGIC=0xDE;
uint8_t esEnable=0, esInv=0, esDir=4;
void saveEs() { EsRecord r={ES_MAGIC,esEnable,esInv,esDir}; EEPROM.put(ES_EE_ADDR,r); }
void loadEs() {
  EsRecord r; EEPROM.get(ES_EE_ADDR,r);
  if(r.magic!=ES_MAGIC||(r.en|r.inv|r.dir)>7) return;
  esEnable=r.en; esInv=r.inv; esDir=r.dir;
}
// True when the beam is blocked. Blocked reads HIGH with the default ESINV=0.
bool endstopHit(uint8_t i) { return (digitalRead(ES_PIN[i])==HIGH) != (((esInv>>i)&1)!=0); }
uint8_t esState() { uint8_t s=0; for(uint8_t i=0;i<3;i++) if(endstopHit(i)) s|=1<<i; return s; }
void printEs(uint8_t s) {
  Serial.print(F("ES"));
  for(uint8_t i=0;i<3;i++) { Serial.print(i==0?F(" X:"):i==1?F(" Y:"):F(" Z:")); Serial.print(((s>>i)&1)?F("blocked"):F("open")); }
  Serial.println();
}

// Each LED is written only when its state changes, so this is cheap in the step loop.
void writeLed(uint8_t idx, uint8_t pin, bool on) {
  static uint8_t out[4]={2,2,2,2};
  if(out[idx]!=(on?1:0)) { digitalWrite(pin,on?HIGH:LOW); out[idx]=on?1:0; }
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
  // All values are measured by the operator. Settings are RAM-only.
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
  else if(!strcmp(key,"$ESEN")) {if(v<0||v>7||v!=(float)(int)v)return false; esEnable=(uint8_t)v; saveEs();}
  else if(!strcmp(key,"$ESINV")) {if(v<0||v>7||v!=(float)(int)v)return false; esInv=(uint8_t)v; saveEs();}
  else if(!strcmp(key,"$ESDIR")) {if(v<0||v>7||v!=(float)(int)v)return false; esDir=(uint8_t)v; saveEs();}
  else if(!strcmp(key,"$PENUP")) {if(v<0||v>600)return false; penUpZ=v; penUpSet=true;}
  else if(!strcmp(key,"$PENDOWN")) {if(v<0||v>600)return false; penDownZ=v; penDownSet=true;}
  else return false;
  return true;
}

// Streaming is stop-and-wait. Any unexpected bytes during motion invalidate
// the manual origin. This also handles an immediate ! from the USB sender.
bool interrupted() {
  if (!Serial.available()) return false;
  while (Serial.available()) Serial.read();
  disarm();
  lineLen = 0;
  lineOverflow = false;
  replyError(F("interrupted; restore position before rearming"));
  return true;
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
  if(!major) { Serial.println(F("ok")); return true; }
  // Driver stays enabled from ARM until DISARM to avoid losing position.
  for(uint8_t i=0;i<3;i++) { digitalWrite(ax[i].stepPin,LOW); digitalWrite(ax[i].dirPin,delta[i]>=0?HIGH:LOW); }
  delayMicroseconds(5);
  float distance=sqrtf((target[0]-ax[0].posMm)*(target[0]-ax[0].posMm)+
                       (target[1]-ax[1].posMm)*(target[1]-ax[1].posMm)+
                       (target[2]-ax[2].posMm)*(target[2]-ax[2].posMm));
  // Cruise rate in major-axis steps/s from the feed, capped at MAX_STEP_RATE_SPS.
  float vC=(feed/60.0f)*(float)major/distance;
  if(vC>MAX_STEP_RATE_SPS) vC=MAX_STEP_RATE_SPS;
  if(vC<1.0f) vC=1.0f;
  // No lookahead: the host is stop-and-wait, so every move ends at START rate.
  float vS=(START_RATE_SPS<vC)?START_RATE_SPS:vC;
  float vS2=vS*vS;
  long accum[3]={0,0,0};
  busy=true;
  unsigned long tNext=micros();
  for(long s=0;s<major;s++) {
    // Check for ! on every step, not only while waiting: a short/fast move could
    // otherwise finish its whole loop without ever opening the wait window.
    if(interrupted()) { busy=false; return false; }
    if(s>0) {
      // Symmetric trapezoid/triangle: speed depends on steps from the nearest end.
      long m=(s<major-s)?s:major-s;
      float v=sqrtf(vS2+2.0f*ACCEL_STEPS_PER_S2*(float)m);
      if(v>vC) v=vC;
      tNext+=(unsigned long)(1000000.0f/v);
    }
    // Absolute schedule from tNext, so compute time does not drift the steps.
    while((long)(micros()-tNext)<0) { if(interrupted()) { busy=false; return false; } updateLeds(); }
    for(uint8_t i=0;i<3;i++) { accum[i]+=ad[i]; if(accum[i]>=major) { digitalWrite(ax[i].stepPin,HIGH); accum[i]-=major; } }
    delayMicroseconds(3); // pulse width >= 2 us
    for(uint8_t i=0;i<3;i++) digitalWrite(ax[i].stepPin,LOW);
  }
  busy=false;
  for(uint8_t i=0;i<3;i++) ax[i].posMm=target[i];
  Serial.println(F("ok")); return true;
}

// Homing speeds and limits. Lower HOME_SLOW if the endstop is hit too hard.
#define HOME_SEEK_MM_MIN 120.0f
#define HOME_SLOW_MM_MIN 30.0f
#define HOME_BACKOFF_MM 2.0f
#define HOME_MAX_MM 400.0f   // give up if no trigger within this travel

// Steps axis i, n steps at most, in direction pos. stopOn 1 stops when blocked,
// 0 when open, -1 ignores the endstop. Returns steps taken, or -1 if interrupted.
long stepAxis(uint8_t i, bool pos, float feedMm, long n, int8_t stopOn) {
  digitalWrite(ax[i].dirPin,pos?HIGH:LOW); delayMicroseconds(5);
  unsigned long periodUs=(unsigned long)(60000000.0f/(feedMm*ax[i].stepsPerMm));
  if(periodUs<1000UL) periodUs=1000UL; // same 1 kstep/s cap as moves
  unsigned long tNext=micros();
  long s=0;
  for(; s<n; s++) {
    if(stopOn>=0 && endstopHit(i)==(stopOn==1)) break;
    if(interrupted()) return -1;
    tNext+=periodUs;
    while((long)(micros()-tNext)<0) updateLeds();
    digitalWrite(ax[i].stepPin,HIGH); delayMicroseconds(3); digitalWrite(ax[i].stepPin,LOW);
    ax[i].posMm+=(pos?1.0f:-1.0f)/ax[i].stepsPerMm;
  }
  return s;
}
// Seek to the endstop, back off, re-approach slowly, then zero the axis there.
bool homeAxis(uint8_t i) {
  bool pos=(esDir>>i)&1;
  long seek=stepAxis(i,pos,HOME_SEEK_MM_MIN,lround(HOME_MAX_MM*ax[i].stepsPerMm),1);
  if(seek<0) return false;
  if(!endstopHit(i)) { replyError(F("home: no endstop trigger")); return false; }
  long back=lround(HOME_BACKOFF_MM*ax[i].stepsPerMm);
  if(stepAxis(i,!pos,HOME_SLOW_MM_MIN,back,-1)<0) return false;
  long app=stepAxis(i,pos,HOME_SLOW_MM_MIN,2*back,1);
  if(app<0) return false;
  if(!endstopHit(i)) { replyError(F("home: re-approach missed endstop")); return false; }
  ax[i].posMm=0; positionSet[i]=true;
  return true;
}

void processLine(char *line) {
  errorLatched=false; // the red LED shows the most recent line's error
  for(char *p=line;*p;p++) if(*p>='a'&&*p<='z') *p-=32;
  char *save; char *w=strtok_r(line," \t",&save); if(!w) return;
  if(!strcmp(w,"ARM")) {
    if(!readyConfig()||!penUpSet||!penDownSet||fabs(penUpZ-penDownZ)<0.01f||penUpZ<ax[2].minMm||penUpZ>ax[2].maxMm||penDownZ<ax[2].minMm||penDownZ>ax[2].maxMm) { replyError(F("configure measured steps/mm, travel and pen Z endpoints first")); return; }
    // Require a deliberate known origin on every boot before arming.
    if(!positionSet[0]||!positionSet[1]||!positionSet[2]||ax[0].posMm<ax[0].minMm||ax[0].posMm>ax[0].maxMm||ax[1].posMm<ax[1].minMm||ax[1].posMm>ax[1].maxMm||ax[2].posMm<ax[2].minMm||ax[2].posMm>ax[2].maxMm) { replyError(F("set measured position first")); return; }
    if(!armed) enableDrivers(); // idempotent: M17 may already have enabled the drivers
    Serial.println(F("ok")); return;
  }
  if(!strcmp(w,"DISARM")) { disarm(); Serial.println(F("ok")); return; }
  if(w[0]=='$') {
    if(armed) { replyError(F("disarm before configuration")); return; }
    if(!setParameter(w)) { replyError(F("bad configuration")); return; }
    Serial.println(F("ok")); return;
  }
  if(!strcmp(w,"ES")) { printEs(esState()); Serial.println(F("ok")); return; }
  if(!strcmp(w,"ESWATCH")) {
    uint8_t last=0xFF;
    while(!Serial.available()) {
      uint8_t s=esState();
      if(s!=last) { printEs(s); last=s; }
      updateLeds(); delay(5);
    }
    while(Serial.available()) Serial.read();
    Serial.println(F("ok")); return;
  }
  if(!strcmp(w,"G28")) {
    bool want[3]={false,false,false}; bool any=false;
    while((w=strtok_r(NULL," \t",&save))) {
      uint8_t i=(w[0]=='X')?0:(w[0]=='Y')?1:(w[0]=='Z')?2:3;
      if(i==3||w[1]) { replyError(F("G28 takes X, Y or Z")); return; }
      want[i]=true; any=true;
    }
    if(!any) want[0]=want[1]=want[2]=true;
    if(!armed) { replyError(F("not armed")); return; }
    for(uint8_t i=0;i<3;i++) if(want[i] && !((esEnable>>i)&1)) { replyError(F("endstop disabled; set $ESEN")); return; }
    for(uint8_t i=0;i<3;i++) if(want[i] && !homeAxis(i)) return;
    Serial.println(F("ok")); return;
  }
  if(!strcmp(w,"G21")) { Serial.println(F("ok")); return; }
  if(!strcmp(w,"G90")) { absoluteMode=true; Serial.println(F("ok")); return; }
  if(!strcmp(w,"G91")) { absoluteMode=false; Serial.println(F("ok")); return; }
  if(!strcmp(w,"LIMITS")) {
    Serial.print(F("ok X")); Serial.print(ax[0].maxMm,3);
    Serial.print(F(" Y")); Serial.print(ax[1].maxMm,3);
    Serial.print(F(" F")); Serial.println(MAX_FEED_MM_MIN,0); return;
  }
  if(!strcmp(w,"M5") || !strcmp(w,"M3")) {
    if(!armed) { replyError(F("not armed")); return; }
    if(!penUpSet||!penDownSet) { replyError(F("set measured pen Z endpoints")); return; }
    float t[3]={ax[0].posMm,ax[1].posMm,(!strcmp(w,"M3")?penDownZ:penUpZ)};
    if(moveTo(t,100.0f,true)) { penDown=!strcmp(w,"M3"); }
    return;
  }
  if(!strcmp(w,"M17")) { enableDrivers(); Serial.println(F("ok")); return; }
  if(!strcmp(w,"M18")) { disarm(); Serial.println(F("ok")); return; } // disarm() marks position unknown
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
    saveCal(); Serial.println(F("ok")); return;
  }
  if(!strcmp(w,"G92") || !strcmp(w,"M210")) {
    // M210 is G92 X0 Y0 Z0: the jogged-to corner becomes the origin.
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
    Serial.println(F("ok")); return;
  }
  if(!strcmp(w,"M211")) {
    // Current X/Y becomes the max travel corner. The origin must be set first.
    if(!positionSet[0]||!positionSet[1]) { replyError(F("set origin with M210 first")); return; }
    if(ax[0].posMm<=0||ax[1].posMm<=0||ax[0].posMm>600||ax[1].posMm>600) { replyError(F("max corner must be >0 and <=600 mm")); return; }
    ax[0].maxMm=ax[0].posMm; ax[1].maxMm=ax[1].posMm; calibrated=true;
    saveCal(); Serial.println(F("ok")); return;
  }
  if(!strcmp(w,"M114")) {
    Serial.print(F("ok X")); Serial.print(ax[0].posMm,3);
    Serial.print(F(" Y")); Serial.print(ax[1].posMm,3);
    Serial.print(F(" Z")); Serial.print(ax[2].posMm,3);
    Serial.println(posKnown()?F(" known"):F(" unknown")); return;
  }
  if(!strcmp(w,"M115")) {
    Serial.print(F("ok CAL=")); Serial.print(calibrated?1:0);
    Serial.print(F(" ORIGIN=")); Serial.print(posKnown()?1:0);
    Serial.print(F(" ARMED=")); Serial.print(armed?1:0);
    Serial.print(F(" MAX X")); Serial.print(ax[0].maxMm,3);
    Serial.print(F(" Y")); Serial.print(ax[1].maxMm,3);
    Serial.print(F(" Z")); Serial.print(ax[2].maxMm,3);
    Serial.print(F(" STEPS X")); Serial.print(ax[0].stepsPerMm,3);
    Serial.print(F(" Y")); Serial.print(ax[1].stepsPerMm,3);
    Serial.print(F(" Z")); Serial.println(ax[2].stepsPerMm,3); return;
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
    Serial.println(F("ok")); return;
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

void setup() {
  pinsFloat(); Serial.begin(115200);
  pinMode(LED_READY,OUTPUT); pinMode(LED_BUSY,OUTPUT); pinMode(LED_ALARM,OUTPUT); pinMode(LED_HEART,OUTPUT);
  for(uint8_t i=0;i<3;i++) pinMode(ES_PIN[i],INPUT_PULLUP);
  loadCal(); loadEs();
  Serial.println(F("DaVinci plotter ready; unarmed; G21 G90; send measured config, then ARM, M5"));
}
void loop() {
  updateLeds();
  while(Serial.available()) {
    char c=(char)Serial.read();
    if(c=='!') {
      disarm();
      lineLen=0; lineOverflow=false;
      replyError(F("aborted; position invalid"));
      continue;
    }
    if(c=='\r') continue;
    if(c=='\n') {
      lastLineMs=millis();
      if(lineOverflow) replyError(F("line too long"));
      else { lineBuf[lineLen]='\0'; processLine(lineBuf); }
      lineLen=0; lineOverflow=false;
    } else if(!lineOverflow) {
      if(lineLen<LINE_CAP-1) lineBuf[lineLen++]=c; else lineOverflow=true;
    }
  }
}
