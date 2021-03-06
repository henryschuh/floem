from floem import *

class Request(Element):
    def configure(self):
        self.inp = Input(SizeT, "void*", "void*")
        self.out = Output(SizeT, "void*", "void*")

    def impl(self):
        self.run_c(r'''
(size_t size, void* pkt, void* buff) = inp();
param_message* m = (param_message*) pkt;

m->ether.src = src;
m->ether.dest = dest;

m->ipv4.src = src_ip;
m->ipv4.dest = dest_ip;

static __thread uint16_t sport = 0;
m->udp.src_port = (++sport == 0 ? ++sport : sport);
m->udp.dest_port = m->udp.src_port;

m->ether.type = htons(ETHERTYPE_IPv4);
m->ipv4._proto = 17;
        m->ipv4._len = htons(size - offsetof(param_message, ipv4));
        m->ipv4._ttl = 64;
        m->ipv4._chksum = 0;
        //m->ipv4._chksum = rte_ipv4_cksum(&m->ipv4);  // TODO

        m->udp.len = htons(size - offsetof(param_message, udp));
        m->udp.cksum = 0;

m->pool = rand() % 8;
m->param = (double)rand() / (double)RAND_MAX;

output { out(size, pkt, buff); }
        ''')

class Stat(State):
    count = Field(SizeT)
    lasttime = Field(SizeT)

    def init(self):
        self.count = 0
        self.lasttime = 0

class Recieve(Element):
    this = Persistent(Stat)

    def configure(self):
        self.inp = Input(SizeT, "void*", "void*")
        self.out = Output("void*", "void*")

    def states(self):
        self.this = Stat()

    def impl(self):
        self.run_c(r'''
(size_t size, void* pkt, void* buff) = inp();
param_message* m = (param_message*) pkt;


if(m->status == 1) {
    //printf("pkt\n");
uint64_t mycount = __sync_fetch_and_add64(&this->count, 1);
if(mycount == 100000) {
    struct timeval now;
    gettimeofday(&now, NULL);
    size_t thistime = now.tv_sec * 1000000 + now.tv_usec;
    printf("%zu pkts/s\n", (mycount * 1000000)/(thistime - this->lasttime));
    this->lasttime = thistime;
    this->count = 0;
}
}

output { out(pkt, buff); }
        ''')


class gen(Segment):
    def impl(self):
        net_alloc = net.NetAlloc()
        to_net = net.ToNet(configure=["net_alloc"])

        library.Constant(configure=[SizeT,'sizeof(param_message)']) >> net_alloc
        net_alloc.oom >> library.Drop()
        net_alloc.out >> Request() >> to_net

class recv(Segment):
    def impl(self):
        from_net = net.FromNet()
        free = net.FromNetFree()

        from_net.nothing >> library.Drop()

        from_net >> Recieve() >> free

n = 5
gen('gen', process='dpdk', cores=range(n))
recv('recv', process='dpdk', cores=range(n))
c = Compiler()
c.include = r'''
#include "protocol_binary.h"

struct eth_addr src = { .addr = "\x68\x05\xca\x33\x13\x40" }; // n30
//struct eth_addr dest = { .addr = "\x68\x05\xca\x33\x11\x3c" }; // n33
struct eth_addr dest = { .addr = "\x00\x0f\xb7\x30\x3f\x58" }; // n35

struct ip_addr src_ip = { .addr = "\x0a\x03\x00\x1e" };
//struct ip_addr dest_ip = { .addr = "\x0a\x03\x00\x21" }; // n33
struct ip_addr dest_ip = { .addr = "\x0a\x03\x00\x23" }; // n35
'''
c.testing = 'while (1) pause();'
c.generate_code_and_compile()
