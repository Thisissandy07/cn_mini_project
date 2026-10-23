#ifndef COMMON_H
#define COMMON_H
#include <stdint.h>
#include <time.h>

#define HDR_SIZE 16          /* flow_id(4) + seq(4) + timestamp(8) */
#define MAX_PKT 1472         /* max UDP payload for a 1500 MTU */
#define MAX_FLOWS 16
#define WIRE_OVERHEAD 42     /* Ethernet(14) + IPv4(20) + UDP(8) */

struct __attribute__((packed)) pkt_hdr {
    uint32_t flow_id;        /* network byte order */
    uint32_t seq;            /* network byte order */
    uint64_t ts_ns;          /* send time, CLOCK_REALTIME, big endian */
};

static inline uint64_t now_ns(clockid_t c)
{
    struct timespec t;
    clock_gettime(c, &t);
    return (uint64_t)t.tv_sec * 1000000000ULL + (uint64_t)t.tv_nsec;
}
#endif
