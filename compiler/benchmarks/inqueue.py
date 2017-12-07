from dsl import *
from compiler import Compiler
import target, queue, net_real, library
import queue_smart

n_cores = 9

class MyState(State):
    pkt = Field('void*')
    pkt_buff = Field('void*')
    key = Field('void*', copysize=22)
    core = Field(Size)
    pool = Field(Int)


class main(Flow):
    state = PerPacket(MyState)

    def impl(self):
        # Queue
        RxEnq, RxDeq, RxScan = queue_smart.smart_queue("rx_queue", entry_size=32, size=32 * 1024, insts=n_cores,
                                                       channels=1, enq_blocking=True, enq_atomic=False, enq_output=True)
        rx_enq = RxEnq()
        rx_deq = RxDeq()

        class MakeKey(Element):
            def configure(self):
                self.inp = Input(Size, "void *", "void *")
                self.out = Output()

            def impl(self):
                self.run_c(r'''
        (size_t size, void* pkt, void* buff) = inp();
        state.pkt = pkt;
        state.pkt_buff = buff;
        iokvs_message* m = (iokvs_message*) pkt;

        state.key = m->payload + m->mcr.request.extlen;;
        state.pool = 0;
        state.core = cvmx_get_core_num();

        output { out(); }
                ''')

        class GetPktBuff(Element):
            def configure(self):
                self.inp = Input()
                self.out = Output("void*", "void*")

            def impl(self):
                self.run_c(r'''
        void* pkt = state.pkt;
        void* pkt_buff = state.pkt_buff;
        output { out(pkt, pkt_buff); }
                ''')

        class nic_rx(Pipeline):
            def impl(self):
                from_net = net_real.FromNet()
                from_net_free = net_real.FromNetFree()

                from_net >> MakeKey() >> rx_enq.inp[0]
                rx_enq.done >> GetPktBuff() >> from_net_free
                from_net.nothing >> library.Drop()


        ############################ CPU #############################
        class Scheduler(Element):
            def configure(self):
                self.out = Output(Size)

            def impl(self):
                self.run_c(r'''
    static size_t core = 0;
    core = (core+1) %s %d;
                output { out(core); }
                ''' % ('%', n_cores))

        class Display(Element):
            def configure(self):
                self.inp = Input()

            def impl(self):
                self.run_c(r'''
    void *key = state.key;
    int pool = state.pool;

    static size_t count = 0;
    static uint64_t lasttime = 0;
    count++;
    if(count == 100000) {
        struct timeval now;
        gettimeofday(&now, NULL);

        uint64_t thistime = now.tv_sec*1000000 + now.tv_usec;
        printf("%zu pkts/s\n", (count * 1000000)/(thistime - lasttime));
        lasttime = thistime;
        count = 0;
    }
                ''')

        class run(Pipeline):
            def impl(self):
                Scheduler() >> rx_deq
                rx_deq.out[0] >> Display()

        nic_rx('nic_rx', device=target.CAVIUM, cores=range(n_cores))
        run('run', process='app', cores=range(1))


master_process('app')

c = Compiler(main)
c.include = r'''
#include "protocol_binary.h"
'''
c.generate_code_as_header()
c.depend = ['app']
c.compile_and_run("test_queue")
