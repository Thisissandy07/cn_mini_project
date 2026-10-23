#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <pthread.h>
#include <endian.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include "common.h"

typedef struct {
    int id, port, size, duration;
    const char *ip;
    double rate_mbps;
    uint64_t tx_pkts, tx_bytes;
    uint64_t last_pkts, last_bytes;     /* main thread only */
    volatile int done;
} flow_t;

static flow_t flows[MAX_FLOWS];
static volatile sig_atomic_t stop_flag = 0;
static void on_sig(int s) { (void)s; stop_flag = 1; }

static void *sender(void *arg)
{
    flow_t *f = arg;
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) { perror("socket"); f->done = 1; return NULL; }
    struct sockaddr_in dst = {0};
    dst.sin_family = AF_INET;
    dst.sin_port = htons(f->port);
    if (inet_pton(AF_INET, f->ip, &dst.sin_addr) != 1) { fprintf(stderr, "bad IP\n"); f->done = 1; return NULL; }

    char buf[MAX_PKT];
    memset(buf, 'x', sizeof buf);
    struct pkt_hdr *h = (struct pkt_hdr *)buf;
    h->flow_id = htonl(f->id);

    double interval_ns = (f->size * 8.0) / (f->rate_mbps * 1e6) * 1e9;
    uint64_t start = now_ns(CLOCK_MONOTONIC);
    uint64_t end = start + (uint64_t)f->duration * 1000000000ULL;
    uint64_t next = start;
    uint32_t seq = 0;

    while (!stop_flag) {
        uint64_t t = now_ns(CLOCK_MONOTONIC);
        if (t >= end) break;
        if (t < next) {                          /* pace the sending rate */
            uint64_t gap = next - t;
            if (gap > 100000) {
                struct timespec ts = { 0, (long)(gap - 50000) };
                nanosleep(&ts, NULL);
            }
            continue;
        }
        h->seq = htonl(seq);
        h->ts_ns = htobe64(now_ns(CLOCK_REALTIME));
        ssize_t n = sendto(fd, buf, f->size, 0, (struct sockaddr *)&dst, sizeof dst);
        if (n > 0) {
            __atomic_fetch_add(&f->tx_pkts, 1, __ATOMIC_RELAXED);
            __atomic_fetch_add(&f->tx_bytes, (uint64_t)n, __ATOMIC_RELAXED);
            seq++;
        }
        next += (uint64_t)interval_ns;
        if (t > next + 200000000ULL) next = t;    /* don't burst after a stall */
    }
    close(fd);
    f->done = 1;
    return NULL;
}

int main(int argc, char **argv)
{
    const char *ip = "10.0.0.3", *out = "client.csv";
    int base_port = 5000, size = 1200, duration = 10, nflows = 1, opt;
    double rate = 5.0;
    while ((opt = getopt(argc, argv, "s:p:l:r:t:n:o:")) != -1) {
        switch (opt) {
        case 's': ip = optarg; break;
        case 'p': base_port = atoi(optarg); break;
        case 'l': size = atoi(optarg); break;
        case 'r': rate = atof(optarg); break;
        case 't': duration = atoi(optarg); break;
        case 'n': nflows = atoi(optarg); break;
        case 'o': out = optarg; break;
        default:
            fprintf(stderr, "usage: %s -s server_ip [-p base_port] [-l payload_bytes] [-r rate_mbps_per_flow] [-t seconds] [-n flows] [-o csv]\n", argv[0]);
            return 1;
        }
    }
    if (size < HDR_SIZE || size > MAX_PKT) { fprintf(stderr, "size must be %d..%d\n", HDR_SIZE, MAX_PKT); return 1; }
    if (nflows < 1 || nflows > MAX_FLOWS || rate <= 0 || duration <= 0) { fprintf(stderr, "bad arguments\n"); return 1; }

    signal(SIGINT, on_sig);
    signal(SIGTERM, on_sig);

    FILE *csv = fopen(out, "w");
    if (!csv) { perror("fopen"); return 1; }
    fprintf(csv, "epoch_s,flow_id,tx_pkts,tx_bytes,tx_mbps\n");

    pthread_t th[MAX_FLOWS];
    for (int i = 0; i < nflows; i++) {
        flows[i] = (flow_t){ .id = i, .port = base_port + i, .size = size, .duration = duration,
                             .ip = ip, .rate_mbps = rate };
        pthread_create(&th[i], NULL, sender, &flows[i]);
    }

    uint64_t last = now_ns(CLOCK_MONOTONIC);
    for (;;) {
        struct timespec ts = { 1, 0 };
        nanosleep(&ts, NULL);
        uint64_t now = now_ns(CLOCK_MONOTONIC);
        double dt = (now - last) / 1e9;
        last = now;
        double epoch = now_ns(CLOCK_REALTIME) / 1e9;
        int all_done = 1;
        for (int i = 0; i < nflows; i++) {
            flow_t *f = &flows[i];
            uint64_t pk = __atomic_load_n(&f->tx_pkts, __ATOMIC_RELAXED);
            uint64_t by = __atomic_load_n(&f->tx_bytes, __ATOMIC_RELAXED);
            fprintf(csv, "%.3f,%d,%llu,%llu,%.4f\n", epoch, f->id,
                    (unsigned long long)(pk - f->last_pkts), (unsigned long long)(by - f->last_bytes),
                    (by - f->last_bytes) * 8.0 / dt / 1e6);
            f->last_pkts = pk; f->last_bytes = by;
            if (!f->done) all_done = 0;
        }
        fflush(csv);
        if (all_done) break;
    }

    for (int i = 0; i < nflows; i++) pthread_join(th[i], NULL);
    fprintf(stderr, "--- client summary ---\n");
    for (int i = 0; i < nflows; i++)
        fprintf(stderr, "flow %d: sent %llu pkts, %llu bytes\n", i,
                (unsigned long long)flows[i].tx_pkts, (unsigned long long)flows[i].tx_bytes);
    fclose(csv);
    return 0;
}
