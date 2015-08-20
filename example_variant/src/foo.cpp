#include "foo.h"

const char *hello(void)
{
	static const char h[] = "Hello World!";

	return h;
}
