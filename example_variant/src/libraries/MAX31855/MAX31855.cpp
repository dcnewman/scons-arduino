#include "MAX31855.h"
#include "util/delay.h"

max31855::max31855(uint8_t so_, uint8_t sck_, uint8_t cs_) :
	sck(sck_), so(so_), cs(cs_)
{
	// Establish the directionality of the I/O pins
	pinMode(cs,  OUTPUT);

	// And right away, tell the chip that we're not talking to it
	// and force a conversion process.
	digitalWrite(cs, HIGH);

	// And everyone else
	pinMode(so,  INPUT);
	pinMode(sck, OUTPUT);
}

float max31855::readTemp(void)
{
	int32_t v = spiread32();

	if (v & 0x7)
		// Error!
		return NAN; 

	// Ignore cold junction temp data and any fault bits
	v >>= 18;

	// Pull off the bottom 13 toes'ies -- bits -- off
	int16_t temp = v & 0x3FFF;

	// Value from chip is in 2's-complement, 14bits
	// To convert to a negative value in 2's complement, 16bits
	// we need just set the two highest bits.
	if (v & 0x2000) 
		temp |= 0xC000;
  
	// Value is actually in units of 0.25C
	float tempC = v;
	return tempC / 4.0;
}


uint32_t max31855::spiread32(void)
{
	// Set CLK low
	digitalWrite(sck, LOW);

	// Stop any conversion
	delayMicroseconds(1);
	digitalWrite(cs, LOW);

	// Need to wait 100 ns == 0.1 us < 1 us
	delayMicroseconds(1);

	// Read the 14 temp bits, D31 - D18
	uint16_t t = 0;
	uint16_t mask = 0x2000;
	do
	{
		digitalWrite(sck, LOW);
		delayMicroseconds(1);
		if (digitalRead(so)) t |= mask;
		mask >>= 1;

		digitalWrite(sck, HIGH);
		delayMicroseconds(1);
	}
	while (mask != 0);

	// For bits D17 - D00, we really only care about
	// D16 -- Should be 0
	// D02 -- Indicates a short to VCC
	// D01 -- Indicates a short to GND
	// D00 -- Indicates an open circuit

	digitalWrite(cs, HIGH);
	return t;
}
