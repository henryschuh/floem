#ifndef HASH_H
#define    HASH_H

#include "stdint.h"
#include "stdlib.h"

#ifdef    __cplusplus
extern "C" {
#endif

uint32_t hash(const void *key, size_t length, const uint32_t initval);

#ifdef    __cplusplus
}
#endif

#endif    /* HASH_H */

