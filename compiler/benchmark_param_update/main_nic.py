from dsl2 import *
from compiler import Compiler
import target, queue2, net_real, library_dsl2, queue_smart2

n_cores = 1
nic_cores = 1

class MyState(State):
    core = Field(Size)
    payload = Field(Pointer(Uint(8)), copysize='sizeof(param_entry)')

class main(Pipeline):
    state = PerPacket(MyState)

    def impl(self):
        # Queue
        RxEnq, RxDeq, RxScan = queue_smart2.smart_queue("rx_queue", 32 * 1024, n_cores, 1,
                                                        overlap=32,
                                                        enq_output=False, enq_blocking=True, enq_atomic=True)
        rx_enq = RxEnq()
        rx_deq = RxDeq()

        class Reply(Element):
            def configure(self):
                self.inp = Input(Size, "void*", "void*")
                self.out = Output(Size, "void*", "void*")

            def impl(self):
                self.run_c(r'''
        (size_t size, void* pkt, void* buff) = inp();
        param_message* m = (param_message*) pkt;

        struct eth_addr src = m->ether.src;
        struct eth_addr dest = m->ether.dest;
        m->ether.src = dest;
        m->ether.dest = src;

        struct ip_addr src_ip = m->ipv4.src;
        struct ip_addr dest_ip = m->ipv4.dest;
        m->ipv4.src = dest_ip;
        m->ipv4.dest = src_ip;

        uint16_t src_port = m->udp.src_port;
        uint16_t dest_port = m->udp.dest_port;
        m->udp.dest_port = src_port;
        m->udp.src_port = dest_port;

        m->status = 1;

        /*
        uint8_t* p = pkt;
        int i;
        for(i=0; i<64; i++) {
          printf("%x ",p[i]);
        }
        printf("\n");
        */

        output { out(size, pkt, buff); }
                ''')

        class Save(Element):
            def configure(self):
                self.inp = Input(Size, "void *", "void *")
                self.out = Output()

            def impl(self):
                self.run_c(r'''
        (size_t size, void* pkt, void* buff) = inp();
        //state.pkt = pkt;
        //state.pkt_buff = buff;
        param_message* m = (param_message*) pkt;

        state.core = nic_htonl(m->pool) %s %d;
        state.payload = (uint8_t*) &m->pool;

        output { out(); }
                ''' % ('%', n_cores))

        class nic_rx(InternalLoop):
            def impl(self):
                from_net = net_real.FromNet()
                to_net = net_real.ToNet()

                from_net.nothing >> library_dsl2.Drop()

                from_net >> Save() >> rx_enq
                from_net >> Reply() >> to_net

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

        class Update(Element):
            def configure(self):
                self.inp = Input()

            def impl(self):
                self.run_c(r'''
        uint8_t* payload = state.payload;
        uint32_t* pool = payload;
        double* param = payload + sizeof(uint32_t);
        update_param(*pool, *param);
                    ''')

        class run(InternalLoop):
            def impl(self):
                #Scheduler() >> rx_deq
                self.core_id >> rx_deq
                rx_deq.out[0] >> Update()

        nic_rx('nic_rx', device=target.CAVIUM, cores=range(nic_cores))
        run('run', process='app', cores=range(n_cores))

master_process('app')

c = Compiler(main)
c.include = r'''
#include "protocol_binary.h"
'''
c.generate_code_as_header()
c.depend = ['app', 'param_update']
c.compile_and_run("test_queue")
