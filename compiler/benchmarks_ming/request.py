from dsl2 import *
from compiler import Compiler
import target, queue2, net_real, library_dsl2


class Request(Element):
    def configure(self):
        self.inp = Input(Size, "void*", "void*")
        self.out = Output(Size, "void*", "void*")

    def impl(self):
        self.run_c(r'''
(size_t size, void* pkt, void* buff) = inp();
udp_message* m = (udp_message*) pkt;

m->ether.src = src;
m->ether.dest = dest;

m->ipv4.src = src_ip;
m->ipv4.dest = dest_ip;

static __thread uint16_t sport = 0;
m->udp.src_port = (++sport == 0 ? ++sport : sport);
m->udp.dest_port = m->udp.src_port;

m->ether.type = htons(ETHERTYPE_IPv4);
m->ipv4._proto = 17; // udp
        m->ipv4._len = htons(size - offsetof(udp_message, ipv4));
        m->ipv4._ttl = 64;
        m->ipv4._chksum = 0;
        m->ipv4._chksum = rte_ipv4_cksum(&m->ipv4);  // TODO

        m->udp.len = htons(size - offsetof(udp_message, udp));
        m->udp.cksum = 0;
        //printf("size: %ld %ld %ld\n", size, m->ipv4._len, m->udp.len);

output { out(size, pkt, buff); }
        ''')

class PayloadGen(Element):
    def configure(self):
        self.inp = Input(Size, "void*", "void*")
        self.out = Output(Size, "void*", "void*")

    def impl(self):
        self.run_c(r'''
(size_t size, void* pkt, void* buff) = inp();

udp_message* m = (udp_message*) pkt;
int i;

switch(CMD) {

case HASH:
strcpy(m->cmd, "HASH");
for(i=0; i< (size - sizeof(udp_message) - 5)/8; i++) {                            
    sprintf(m->payload + 8*i, "%d", TEXT_BASE + rand() % TEXT_BASE);          
}                                                                          
break;  

case FLOW:
strcpy(m->cmd, "FLOW");
for(i=0; i<4; i++) {
    sprintf(m->payload + 8*i, "%d", TEXT_BASE + rand() % TEXT_BASE);
}
break;

case SEQU:
strcpy(m->cmd, "SEQU");
sprintf(m->payload, "%d", 1000 + rand() % 1000);
break;

}

output { out(size, pkt, buff); }
        ''')

class Stat(State):
    count = Field(Size)
    lasttime = Field(Size)

    def init(self):
        self.count = 0
        self.lasttime = 0

class Reply(Element):
    this = Persistent(Stat)

    def configure(self):
        self.inp = Input(Size, "void*", "void*")
        self.out = Output("void*", "void*")

    def states(self):
        self.this = Stat()

    def impl(self):
        self.run_c(r'''
(size_t size, void* pkt, void* buff) = inp();
udp_message* m = (udp_message*) pkt;


if(m->ipv4._proto == 17) {
        //printf("pkt %ld\n", size);
uint64_t mycount = __sync_fetch_and_add64(&this->count, 1);
        if(mycount == 100000) {
    struct timeval now;
    gettimeofday(&now, NULL);
    size_t thistime = now.tv_sec * 1000000 + now.tv_usec;
    printf("%zu pkts/s  %f Gbits/s\n", (mycount * 1000000)/(thistime - this->lasttime),
                                        (mycount * size * 8.0)/((thistime - this->lasttime) * 1000));
    this->lasttime = thistime;
    this->count = 0;
}
}

output { out(pkt, buff); }
        ''')


class gen(InternalLoop):
    def impl(self):
        net_alloc = net_real.NetAlloc()
        to_net = net_real.ToNet(configure=["net_alloc"])

        library_dsl2.Constant(configure=[80]) >> net_alloc
        net_alloc.oom >> library_dsl2.Drop()
        net_alloc.out >> Request() >> PayloadGen() >> to_net

class recv(InternalLoop):
    def impl(self):
        from_net = net_real.FromNet()
        free = net_real.FromNetFree()

        from_net.nothing >> library_dsl2.Drop()

        from_net >> Reply() >> free

n = 5
gen('gen', process='dpdk', cores=range(n))
recv('recv', process='dpdk', cores=range(n))
c = Compiler()
c.include = r'''
#include <string.h>
#include "protocol_binary.h"
#include <rte_ip.h>

struct eth_addr src = { .addr = "\x68\x05\xca\x33\x13\x40" };
//struct eth_addr dest = { .addr = "\x68\x05\xca\x33\x11\x3c" }; // n33
struct eth_addr dest = { .addr = "\x00\x0f\xb7\x30\x3f\x58" }; // n35

struct ip_addr src_ip = { .addr = "\x0a\x03\x00\x1e" };   // n30
//struct ip_addr dest_ip = { .addr = "\x0a\x03\x00\x21" }; // n33
struct ip_addr dest_ip = { .addr = "\x0a\x03\x00\x23" }; // n35
//struct ip_addr dest_ip = { .addr = "\x0a\x03\x00\x24" }; // n36

#define TEXT_BASE 10000000 /* 10M (8 bits) */
typedef enum _TYPE {
    ECHO, /* echo */
    HASH, /* hash computing */
    FLOW, /* flow classification */
    SEQU, /* sequencer */
} PKT_TYPE;

#define CMD HASH
'''
c.testing = 'while (1) pause();'
c.generate_code_and_compile()
