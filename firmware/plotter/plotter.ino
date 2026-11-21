/*
 * Da Vinci plotter controller for an Uno + CNC Shield V3 style STEP/DIR
 * interface. Pin mapping follows the repo's documented common mapping:
 * X 2/5, Y 3/6, Z 4/7, shared active-low ENABLE 8. The documentation says
 * this mapping is not electrically verified on every machine. Verify the
 * actual shield/driver wiring before connecting motor power.
 *
 * No settings are guessed: travel, steps/mm and pen endpoints must be
 * measured and entered while disarmed. All settings are RAM-only and reset
 * to zero at boot. No homing switches or servo are assumed. Z is the bed axis.
 */
#include <Arduino.h>
#include <stdlib.h>
#include <math.h>

static const uint8_t X_STEP=2, X_DIR=5, Y_STEP=3, Y_DIR=6, Z_STEP=4, Z_DIR=7;
static const uint8_t ENABLE_PIN=8; // CNC Shield V3 common shared active-low enable
static const float MAX_FEED_MM_MIN=600.0f;
static const float MAX_Z_FEED_MM_MIN=120.0f;
static const uint8_t LINE_CAP=96;

struct Axis { uint8_t stepPin, dirPin; float stepsPerMm, minMm, maxMm, posMm; };
Axis ax[3]={{X_STEP,X_DIR,0,0,0,0},{Y_STEP,Y_DIR,0,0,0,0},{Z_STEP,Z_DIR,0,0,0,0}};
bool armed=false, absoluteMode=true, penDown=false;
bool positionSet[3]={false,false,false};
bool penUpSet=false, penDownSet=false;
float penUpZ=0, penDownZ=0;
char lineBuf[LINE_CAP]; uint8_t lineLen=0; bool lineOverflow=false;

void replyError(const __FlashStringHelper *s) { Serial.print(F("error: ")); Serial.println(s); }
void replyError(const char *s) { Serial.print(F("error: ")); Serial.println(s); }
bool readyConfig() {
  for (uint8_t i=0;i<3;i++) if (ax[i].stepsPerMm<=0 || ax[i].maxMm<=ax[i].minMm) return false;
  return true;
}
void pinsFloat() {
  for (uint8_t i=0;i<3;i++) {
    pinMode(ax[i].stepPin,INPUT); digitalWrite(ax[i].stepPin,LOW);
    pinMode(ax[i].dirPin,INPUT); digitalWrite(ax[i].dirPin,LOW);
  }
  pinMode(ENABLE_PIN,INPUT); digitalWrite(ENABLE_PIN,LOW); // no internal pull-up
}
void disarm() {
  if(armed) { digitalWrite(ENABLE_PIN,HIGH); pinMode(ENABLE_PIN,OUTPUT); }
  armed=false; penDown=false; pinsFloat();
  for(uint8_t i=0;i<3;i++) positionSet[i]=false;
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

bool moveTo(float target[3], float feed) {
  if(!armed) { replyError(F("not armed")); return false; }
  if(feed<=0 || feed>MAX_FEED_MM_MIN) { replyError(F("feed out of range")); return false; }
  if(fabs(target[2]-ax[2].posMm)>0.0001f && feed>MAX_Z_FEED_MM_MIN) { replyError(F("Z feed out of range")); return false; }
  long dest[3], start[3], delta[3], ad[3]; long major=0;
  for(uint8_t i=0;i<3;i++) {
    if(target[i]<ax[i].minMm-0.0001f || target[i]>ax[i].maxMm+0.0001f) { replyError(F("travel limit")); return false; }
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
  unsigned long interval=(unsigned long)(60000000.0f*distance/(feed*major));
  // Hard cap at 1 kstep/s even if a host supplies a faster feed or calibration.
  if(interval<1000) interval=1000;
  long accum[3]={0,0,0};
  for(long s=0;s<major;s++) {
    for(uint8_t i=0;i<3;i++) accum[i]+=ad[i];
    for(uint8_t i=0;i<3;i++) if(accum[i]>=major) { digitalWrite(ax[i].stepPin,HIGH); accum[i]-=major; }
    delayMicroseconds(3);
    for(uint8_t i=0;i<3;i++) digitalWrite(ax[i].stepPin,LOW);
    if(interval>3) {
      unsigned long waitUs=interval-3UL;
      while(waitUs) {
        if (interrupted()) return false;
        unsigned int slice=(unsigned int)(waitUs>15000UL?15000UL:waitUs);
        delayMicroseconds(slice); waitUs-=slice;
      }
    }
  }
  for(uint8_t i=0;i<3;i++) ax[i].posMm=target[i];
  Serial.println(F("ok")); return true;
}

void processLine(char *line) {
  for(char *p=line;*p;p++) if(*p>='a'&&*p<='z') *p-=32;
  char *save; char *w=strtok_r(line," \t",&save); if(!w) return;
  if(!strcmp(w,"ARM")) {
    if(armed) { replyError(F("already armed")); return; }
    if(!readyConfig()||!penUpSet||!penDownSet||fabs(penUpZ-penDownZ)<0.01f||penUpZ<ax[2].minMm||penUpZ>ax[2].maxMm||penDownZ<ax[2].minMm||penDownZ>ax[2].maxMm) { replyError(F("configure measured steps/mm, travel and pen Z endpoints first")); return; }
    // Require a deliberate known origin on every boot before arming.
    if(!positionSet[0]||!positionSet[1]||!positionSet[2]||ax[0].posMm<ax[0].minMm||ax[0].posMm>ax[0].maxMm||ax[1].posMm<ax[1].minMm||ax[1].posMm>ax[1].maxMm||ax[2].posMm<ax[2].minMm||ax[2].posMm>ax[2].maxMm) { replyError(F("set measured position first")); return; }
    digitalWrite(ENABLE_PIN,HIGH); pinMode(ENABLE_PIN,OUTPUT);
    for(uint8_t i=0;i<3;i++){digitalWrite(ax[i].stepPin,LOW);pinMode(ax[i].stepPin,OUTPUT);digitalWrite(ax[i].dirPin,LOW);pinMode(ax[i].dirPin,OUTPUT);}
    digitalWrite(ENABLE_PIN,LOW);
    armed=true; Serial.println(F("ok")); return;
  }
  if(!strcmp(w,"DISARM")) { disarm(); Serial.println(F("ok")); return; }
  if(w[0]=='$') {
    if(armed) { replyError(F("disarm before configuration")); return; }
    if(!setParameter(w)) { replyError(F("bad configuration")); return; }
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
    if(moveTo(t,100.0f)) { penDown=!strcmp(w,"M3"); }
    return;
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
    moveTo(t,feed); return;
  }
  replyError(F("unsupported command"));
}

void setup() {
  pinsFloat(); Serial.begin(115200);
  Serial.println(F("DaVinci plotter ready; unarmed; G21 G90; send measured config, then ARM, M5"));
}
void loop() {
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
      if(lineOverflow) replyError(F("line too long"));
      else { lineBuf[lineLen]='\0'; processLine(lineBuf); }
      lineLen=0; lineOverflow=false;
    } else if(!lineOverflow) {
      if(lineLen<LINE_CAP-1) lineBuf[lineLen++]=c; else lineOverflow=true;
    }
  }
}
