/*
 * sntp - minimal SNTP client for the Anyka AK3918AV100 camera (kernel 4.4, ARMv5).
 *
 * Why not busybox ntpd/date: our static busybox (Ubuntu 24.04 armel glibc) uses 64-bit time
 * and returns garbage on kernel 4.4. This tool reads/sets the clock with the raw 32-bit
 * gettimeofday/settimeofday syscalls and never touches glibc's time functions.
 *
 * usage: sntp SERVER_IP [-s]      query server, print offset; -s also sets the clock
 * exit:  0 ok, 1 usage, 2 network/timeout, 3 bad reply, 4 settimeofday failed
 */
#include <arpa/inet.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <unistd.h>

#define NTP_UNIX_DELTA 2208988800UL /* seconds 1900-01-01 -> 1970-01-01 */

struct tv32 { int32_t sec; int32_t usec; };

static int get_tv(struct tv32 *t) { return syscall(__NR_gettimeofday, t, NULL); }
static int set_tv(const struct tv32 *t) { return syscall(__NR_settimeofday, t, NULL); }

static double tv_d(const struct tv32 *t) { return (double)(uint32_t)t->sec + t->usec / 1e6; }

static double ntp_ts(const unsigned char *p)
{
    uint32_t s = (uint32_t)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3];
    uint32_t f = (uint32_t)p[4] << 24 | p[5] << 16 | p[6] << 8 | p[7];
    return (double)(s - NTP_UNIX_DELTA) + f / 4294967296.0;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s SERVER_IP [-s]\n", argv[0]);
        return 1;
    }
    int do_set = argc > 2 && strcmp(argv[2], "-s") == 0;

    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) { perror("socket"); return 2; }
    struct timeval to = { 3, 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &to, sizeof to);

    struct sockaddr_in sa;
    memset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET;
    sa.sin_port = htons(123);
    if (inet_pton(AF_INET, argv[1], &sa.sin_addr) != 1) {
        fprintf(stderr, "bad IP %s\n", argv[1]);
        return 1;
    }

    for (int attempt = 0; attempt < 3; attempt++) {
        unsigned char pkt[48];
        memset(pkt, 0, sizeof pkt);
        pkt[0] = 0x23; /* LI 0, VN 4, mode 3 (client) */

        struct tv32 t1, t4;
        get_tv(&t1);
        if (sendto(fd, pkt, sizeof pkt, 0, (struct sockaddr *)&sa, sizeof sa) != sizeof pkt) {
            perror("sendto");
            continue;
        }
        unsigned char r[48];
        ssize_t n = recv(fd, r, sizeof r, 0);
        get_tv(&t4);
        if (n < 48) {
            fprintf(stderr, "attempt %d: no reply (%s)\n", attempt + 1, n < 0 ? strerror(errno) : "short");
            continue;
        }
        int mode = r[0] & 7, stratum = r[1];
        if (mode != 4 || stratum == 0 || stratum > 15) {
            fprintf(stderr, "bad reply mode %d stratum %d\n", mode, stratum);
            return 3;
        }
        /* offset = ((T2 - T1) + (T3 - T4)) / 2, using server receive (T2) / transmit (T3) */
        double T2 = ntp_ts(r + 32), T3 = ntp_ts(r + 40);
        double offset = ((T2 - tv_d(&t1)) + (T3 - tv_d(&t4))) / 2.0;
        double delay = (tv_d(&t4) - tv_d(&t1)) - (T3 - T2);
        printf("server %s stratum %d offset %+.3f s delay %.3f s\n", argv[1], stratum, offset, delay);

        if (do_set) {
            double now = tv_d(&t4) + offset;
            struct tv32 nt = { (int32_t)(uint32_t)now, (int32_t)((now - (uint32_t)now) * 1e6) };
            if (set_tv(&nt) != 0) { perror("settimeofday"); return 4; }
            printf("clock set to unix %u\n", (unsigned)(uint32_t)nt.sec);
        }
        close(fd);
        return 0;
    }
    close(fd);
    return 2;
}
