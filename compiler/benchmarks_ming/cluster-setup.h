/*
 * Cluster network setup information.
 *
 * This is a static (read-only) loaded table.
 */
#ifndef _CLUSTER_SETUP_H
#define _CLUSTER_SETUP_H

#ifdef CAVIUM
#include "cvmx.h"
#endif

#define MAC_ADDRESS_LEN 6
#define IP_ADDRESS_LEN 4

typedef struct _entity {
    uint8_t mac[MAC_ADDRESS_LEN];
    uint8_t ip[IP_ADDRESS_LEN];
} __attribute__((packed)) entity;

typedef struct _flow {
    entity src;
    entity des;
} __attribute__((packed)) flow;

#ifdef CAVIUM
CVMX_SHARED 
#endif
flow mycluster[] = {
    { // n72 -> n73
        .src = {
            .mac = {0x00, 0x02, 0xc9, 0x4e, 0xde, 0xe4},
            .ip = {0x0a, 0x03, 0x00, 0x49},
        },
        .des = {
            .mac = {0x00, 0x02, 0xc9, 0x4e, 0xe9, 0x38},
            .ip = {0x0a, 0x03, 0x00, 0x48},
        }
    },
    { // n73 -> n72
        .src = {
            .mac = {0x00, 0x02, 0xc9, 0x4e, 0xe9, 0x38},
            .ip = {0x0a, 0x03, 0x00, 0x48},
        },
        .des = {
            .mac = {0x00, 0x02, 0xc9, 0x4e, 0xde, 0xe4},
            .ip = {0x0a, 0x03, 0x00, 0x49},
        }
    },
    { // n25 -> n29
        .src = {
            .mac = {0x3c, 0xfd, 0xfe, 0xaa, 0xde, 0xd0},
            .ip = {0x0a, 0x03, 0x00, 0x19},
        },
        .des = {
            .mac = {0x3c, 0xfd, 0xfe, 0xaa, 0xd1, 0xe0},
            .ip = {0x0a, 0x03, 0x00, 0x1d},
        }
    },
    { // n29 -> n25
        .src = {
            .mac = {0x3c, 0xfd, 0xfe, 0xaa, 0xd1, 0xe0},
            .ip = {0x0a, 0x03, 0x00, 0x1d},
        },
        .des = {
            .mac = {0x3c, 0xfd, 0xfe, 0xaa, 0xde, 0xd0},
            .ip = {0x0a, 0x03, 0x00, 0x19},
        },
    },
    { // n27 -> n28
        .src = {
            .mac = {0x3c, 0xfd, 0xfe, 0xaa, 0xd2, 0x28},
            .ip = {0x0a, 0x03, 0x00, 0x1b},
        },
        .des = {
            .mac = {0x3c, 0xfd, 0xfe, 0xa1, 0x11, 0x2c},
            .ip = {0x0a, 0x03, 0x00, 0x1c},
        },
    },
    { // n28 -> n27
        .src = {
            .mac = {0x3c, 0xfd, 0xfe, 0xa1, 0x11, 0x2c},
            .ip = {0x0a, 0x03, 0x00, 0x1c},
        },
        .des = {
            .mac = {0x3c, 0xfd, 0xfe, 0xaa, 0xd2, 0x28},
            .ip = {0x0a, 0x03, 0x00, 0x1b},
        },
    }
};

#endif /* _CLUSTER_SETUP_H */
