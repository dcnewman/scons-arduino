#include "Arduino.h"

class max31855
{
public:
	max31855(uint8_t miso, uint8_t sck, uint8_t cs);
	float readTemp(void);

private:
	uint8_t sck, so, cs;
	uint32_t spiread32(void);
};
