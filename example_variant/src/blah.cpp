#include "Arduino.h"
#include "SoftwareSerial.h"
#include "foo.h"

SoftwareSerial serial(12, 13);

void setup()
{
    serial.begin(9600);
}

void loop()
{
    serial.println(hello());
    delay(1000*5);  // 5 seconds
}
