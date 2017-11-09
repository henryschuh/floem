/*
 * In-NIC compute
 */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "pkt-utils.h"
#include "nic-compute.h"
#include "count-min-sketch.h"

#ifdef CAVIUM
#include "cvmx.h"
#include "cvmx-spinlock.h"
#include "cvmx-atomic.h"
#include "util.h"
#else
#include <dpdkif.h>
#endif

#define MIN(a,b) (((a)>(b))?(b):(a))
#define MAX(a,b) (((a)>(b))?(a):(b))

void lock_group_init(cvmx_spinlock_t* lock_group, int n) {
    int i = 0;

    for (i = 0; i < n; i++) {
        spinlock_init(&lock_group[i]);
    }
}


static PKT_TYPE
pkt_parser(uint8_t *pkt_ptr)
{
    PKT_TYPE cmd_type;

    if (!memcmp(pkt_ptr + UDP_PAYLOAD, "ECHO", 4)) {
        cmd_type = ECHO;
    } else if (!memcmp(pkt_ptr + UDP_PAYLOAD, "HASH", 4)) {
        cmd_type = HASH;
    } else if (!memcmp(pkt_ptr + UDP_PAYLOAD, "FLOW", 4)) {
        cmd_type = FLOW;
    } else { /* SEQU */
        cmd_type = SEQU;
    }

    return cmd_type;
}


#ifdef CAVIUM
/**
 * Initialize 3des for use
 *
 * @param key    3des keys
 */
static void crypto_3des_initialize(const uint64_t *key)
{
    CVMX_MT_3DES_KEY(key[0],0);
    CVMX_MT_3DES_KEY(key[1],1);
    CVMX_MT_3DES_KEY(key[2],2);
}

/**
 * 3des encrypt without any block chaining
 *
 * @param data     Data to encrypt
 * @param data_len Length of the data. Must be a multiple of 8
 */
static void crypto_3des_encrypt(uint64_t *data, int data_len)
{
    assert((data_len & 0x7) == 0);

    while (data_len)
    {
        CVMX_MT_3DES_ENC(*data);
        CVMX_MF_3DES_RESULT(*data);
        data++;
        data_len-=8;
    }
}

void
compute_3des(uint8_t *pkt_ptr,
             int pkt_len)
{
    const uint64_t key_3des[]           = {0x0123456789abcdefull,
                                           0x0123456789abcdefull,
                                           0x0123456789abcdefull};
    uint64_t *result_3des = (uint64_t *)(pkt_ptr + UDP_PAYLOAD + 5);
    crypto_3des_initialize(key_3des);
    crypto_3des_encrypt(result_3des, sizeof(uint64_t) * 4);
}

/**
 * Initialize AES for use
 *
 * @param key     AES keys
 * @param key_len Length of key in bits
 */
static void crypto_aes_initialize(const uint64_t *key, int key_len)
{
    CVMX_MT_AES_KEY(key[0],0);
    CVMX_MT_AES_KEY(key[1],1);
    CVMX_MT_AES_KEY(key[2],2);
    CVMX_MT_AES_KEY(key[3],3);
    CVMX_MT_AES_KEYLENGTH(key_len/64 - 1);
}

/**
 * AES encrypt without any block chaining
 *
 * @param data     Data to encrypt
 * @param data_len Length of the data. Must be a multiple of 16
 */
static void crypto_aes_encrypt(uint64_t *data, int data_len)
{
    assert((data_len & 0xf) == 0);

    while (data_len)
    {
        CVMX_MT_AES_ENC0(*data);
        CVMX_MT_AES_ENC1(*(data+1));
        CVMX_MF_AES_RESULT(*data++, 0);
        CVMX_MF_AES_RESULT(*data++, 1);
        data_len-=16;
    }
}

void
compute_aes(uint8_t *pkt_ptr,
            int pkt_len)
{
    const uint64_t key_aes[]     	    = {0x0123456789abcdefull,
                                           0x0123456789abcdefull,
                                           0x0123456789abcdefull,
                                           0x0123456789abcdefull};
    uint64_t *result_aes = (uint64_t *)(pkt_ptr + UDP_PAYLOAD + 5);

    crypto_aes_initialize(key_aes, 256);
    crypto_aes_encrypt(result_aes, sizeof(uint64_t) * 4);
}

#else
/**
 * Initialize 3des for use
 *
 * @param key    3des keys
 */
static void crypto_3des_initialize(const uint64_t *key)
{
    //CVMX_MT_3DES_KEY(key[0],0);
    //CVMX_MT_3DES_KEY(key[1],1);
    //CVMX_MT_3DES_KEY(key[2],2);
}

/**
 * 3des encrypt without any block chaining
 *
 * @param data     Data to encrypt
 * @param data_len Length of the data. Must be a multiple of 8
 */
static void crypto_3des_encrypt(uint64_t *data, int data_len)
{
    assert((data_len & 0x7) == 0);

    while (data_len)
    {
        //CVMX_MT_3DES_ENC(*data);
        //CVMX_MF_3DES_RESULT(*data);
        data++;
        data_len-=8;
    }
}

void
compute_3des(uint8_t *pkt_ptr,
             int pkt_len)
{
    const uint64_t key_3des[]           = {0x0123456789abcdefull,
                                           0x0123456789abcdefull,
                                           0x0123456789abcdefull};
    uint64_t *result_3des = (uint64_t *)(pkt_ptr + UDP_PAYLOAD + 5);
    crypto_3des_initialize(key_3des);
    crypto_3des_encrypt(result_3des, sizeof(uint64_t) * 4);
}

/**
 * Initialize AES for use
 *
 * @param key     AES keys
 * @param key_len Length of key in bits
 */
static void crypto_aes_initialize(const uint64_t *key, int key_len)
{
/*
    CVMX_MT_AES_KEY(key[0],0);
    CVMX_MT_AES_KEY(key[1],1);
    CVMX_MT_AES_KEY(key[2],2);
    CVMX_MT_AES_KEY(key[3],3);
    CVMX_MT_AES_KEYLENGTH(key_len/64 - 1);
    */
}

/**
 * AES encrypt without any block chaining
 *
 * @param data     Data to encrypt
 * @param data_len Length of the data. Must be a multiple of 16
 */
static void crypto_aes_encrypt(uint64_t *data, int data_len)
{
    assert((data_len & 0xf) == 0);

    while (data_len)
    {
    /*
        CVMX_MT_AES_ENC0(*data);
        CVMX_MT_AES_ENC1(*(data+1));
        CVMX_MF_AES_RESULT(*data++, 0);
        CVMX_MF_AES_RESULT(*data++, 1);
        */
        data_len-=16;
    }
}

void
compute_aes(uint8_t *pkt_ptr,
            int pkt_len)
{
    const uint64_t key_aes[]     	    = {0x0123456789abcdefull,
                                           0x0123456789abcdefull,
                                           0x0123456789abcdefull,
                                           0x0123456789abcdefull};
    uint64_t *result_aes = (uint64_t *)(pkt_ptr + UDP_PAYLOAD + 5);

    crypto_aes_initialize(key_aes, 256);
    crypto_aes_encrypt(result_aes, sizeof(uint64_t) * 4);
}

#endif