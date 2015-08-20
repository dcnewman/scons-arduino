#include "Arduino.h"
#include "SoftwareSerial.h"

SoftwareSerial serial(12, 13);

void setup()
{
    serial.begin(9600);
}

void loop()
{
    serial.println("Hello, world!");
    delay(1000*5);  // 5 seconds
}
