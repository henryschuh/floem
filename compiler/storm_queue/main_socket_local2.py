import queue2
import net2
import library_dsl2
from dsl2 import *
from compiler import Compiler

test = "spout"
inject_func = "random_" + test
workerid = {"spout": 0, "count": 1, "rank": 2}

n_cores = 7
n_workers = 4


class TaskMaster(State):
    task2executorid = Field(Pointer(Int))
    task2worker = Field(Pointer(Int))

    def init(self):
        self.task2executorid = "get_task2executorid()"
        self.task2worker = "get_task2worker()"

task_master = TaskMaster('task_master')


class GetCore(Element):
    this = Persistent(TaskMaster)
    def states(self, task_master): self.this = task_master

    def configure(self):
        self.inp = Input("struct tuple*")
        self.out = Output("struct tuple*", Size)

    def impl(self):
        self.run_c(r'''
    struct tuple* t = inp();
    int id = this->task2executorid[t->task];
    printf("receive: task %d, id %d\n", t->task, id);
    output { out(t, id); }
        ''')


class Choose(Element):
    this = Persistent(TaskMaster)
    def states(self, task_master): self.this = task_master

    def configure(self):
        self.inp = Input("struct tuple*")
        self.out_send = Output("struct tuple*")
        self.out_local = Output("struct tuple*")
        #self.out_nop = Output()

    def impl(self):
        self.run_c(r'''
    struct tuple* t = inp();
    bool local;
    if(t != NULL) {
        local = (this->task2worker[t->task] == this->task2worker[t->fromtask]);
        if(local) printf("send to myself!\n");
    }
    output switch { case (t && local): out_local(t); case (t && !local): out_send(t); } // else: out_nop(); }
        ''')


class PrintTuple(Element):
    def configure(self):
        self.inp = Input("struct tuple*")
        self.out = Output("struct tuple*")

    def impl(self):
        self.run_c(r'''
    (struct tuple* t) = inp();

    //printf("TUPLE = null\n");
    if(t != NULL) {
        printf("TUPLE[0] -- task = %d, fromtask = %d, str = %s, integer = %d\n", t->task, t->fromtask, t->v[0].str, t->v[0].integer);
        //printf("TUPLE[1] -- task = %d, fromtask = %d, str = %s, integer = %d\n", t->task, t->fromtask, t->v[1].str, t->v[1].integer);
        fflush(stdout);
    }
    output { out(t); }
        ''')



class SteerWorker(Element):
    this = Persistent(TaskMaster)
    def states(self, task_master): self.this = task_master

    def configure(self):
        self.inp = Input("struct tuple*")
        self.out = [Output("struct tuple*") for i in range(n_workers)]
        #self.out_nop = Output()

    def impl(self):
        src = ""
        for i in range(n_workers):
            src += "case (id == {0}): out{0}(t); ".format(i)
        self.run_c(r'''
    (struct tuple* t) = inp();
    int id = -1;
    if(t != NULL) {
        id = this->task2worker[t->task];
        printf("send to worker %d\n", id);
    }
    output switch { ''' + src + "}") # else: out_nop(); }")


# class Drop(Element):
#     def configure(self): self.inp = Input()
#     def impl(self): pass
#
# nop = Drop()

class BatchInfo(State):
    core = Field(Int)
    batch_size = Field(Int)
    start = Field(Uint(64))

    def init(self):
        self.core = 0
        self.batch_size = 0
        self.start = 0

batch_info = BatchInfo()

class BatchScheduler(Element):
    this = Persistent(BatchInfo)
    def states(self, batch_info): self.this = batch_info

    def configure(self):
        self.out = Output(Size)

    def impl(self):
        self.run_c(r'''
    if(this->batch_size >= BATCH_SIZE || rdtsc() - this->start >= BATCH_DELAY) {
        this->core = (this->core + 1) %s %d;
        this->batch_size = 0;
        this->start = rdtsc();
    }
    output { out(this->core); }
        ''' % ('%', n_cores))

class BatchInc(Element):
    this = Persistent(BatchInfo)

    def states(self, batch_info): self.this = batch_info

    def configure(self):
        self.inp = Input("struct tuple*")
        #self.out = Output("struct tuple*")

    def impl(self):
        self.run_c(r'''
        (struct tuple* t) = inp();
        if(t) this->batch_size++;
        // output switch { case t: out(t); };
        ''')

################## Queue addr ####################
class AddrState(State):
    buffer = Field(queue2.q_buffer)

class DropAddr(Element):
    def configure(self):
        self.inp = Input("struct tuple*", "uintptr_t")
        self.out = Output("struct tuple*")

    def impl(self):
        self.run_c(r'''
    (struct tuple* t, uintptr_t addr) = inp();
    output { out(t); }
        ''')

class AddNullAddr(Element):
    def configure(self):
        self.inp = Input("struct tuple*")
        self.out = Output("struct tuple*", "uintptr_t")

    def impl(self):
        self.run_c(r'''
    (struct tuple* t) = inp();
    output { out(t, 0); }
        ''')

class SaveBuff(Element):
    def configure(self):
        self.inp = Input(queue2.q_buffer)
        self.out = Output("struct tuple*")

    def impl(self):
        self.run_c(r'''
    (q_buffer buff) = inp();
    state.buffer = buff;
    output { out(buff.entry); }
        ''')

class GetBuff(Element):
    def configure(self):
        self.inp = Input("struct tuple*")
        self.out = Output(queue2.q_buffer)

    def impl(self):
        self.run_c(r'''
    (struct tuple* t) = inp();
    q_buffer buff = state.buffer;
    output { out(buff); }
        ''')
MAX_ELEMS = (4 * 1024)

rx_enq_creator, rx_deq_creator, rx_release_creator = \
    queue2.queue_custom_owner_bit("rx_queue", "struct tuple", MAX_ELEMS, n_cores, "task", deq_blocking=True,
                                  enq_output=True)

tx_enq_creator, tx_deq_creator, tx_release_creator = \
    queue2.queue_custom_owner_bit("tx_queue", "struct tuple", MAX_ELEMS, n_cores, "task")

class nic_rx(InternalLoop):
    def configure(self): self.process = 'flexstorm'
    def impl(self):
        from_net = net2.from_net_fixed_size_instance("tuple", "struct tuple", n_workers, 8192,
                                                     "workers[atoi(argv[1])].port")
        get_core = GetCore(states=[task_master])

        from_net >> get_core >> rx_enq_creator() >> library_dsl2.Drop(configure=["struct tuple*"])

class inqueue_get(API):
    def configure(self):
        self.process = 'flexstorm'
        self.inp = Input(Size)
        self.out = Output(queue2.q_buffer)

    def impl(self): self.inp >> rx_deq_creator() >> self.out

class inqueue_advance(API):
    def configure(self):
        self.process = 'flexstorm'
        self.inp = Input(queue2.q_buffer)

    def impl(self): self.inp >> rx_release_creator()

class outqueue_put(API):
    def configure(self):
        self.process = 'flexstorm'
        self.inp = Input("struct tuple*", Size)

    def impl(self): self.inp >> tx_enq_creator()

class nic_tx(InternalLoop):  # TODO: ugly, sol: option to make to_net and enq return X
    def configure(self):
        self.process = 'flexstorm'

    # Ugly version
    # def impl(self):
    #     queue_schedule >> tx_deq_creator() >> print_tuple >> choose
    #
    #     # send
    #     choose.out_send >> steer_worker
    #     for i in range(n_workers):
    #         steer_worker.out[i] >> to_nets[i]
    #     steer_worker.out_nop >> nop
    #
    #     # local
    #     rx_enq = rx_enq_creator()
    #     choose.out_local >> get_core2 >> rx_enq
    #
    #     # nop
    #     choose.out_nop >> nop
    #
    #     tx_release = tx_release_creator()
    #     run_order(to_nets + [rx_enq, nop], batch_inc)
    #     print_tuple >> batch_inc >> tx_release

    # Cleaner version
    def impl(self):
        to_nets = []
        for i in range(n_workers):
            to_net = net2.to_net_fixed_size_instance("tuple" + str(i), "struct tuple",
                                                     "workers[%d].hostname" % i, "workers[%d].port" % i, output=True)
            to_nets.append(to_net)

        tx_deq = tx_deq_creator()
        tx_release = tx_release_creator()
        rx_enq = rx_enq_creator()

        queue_schedule = BatchScheduler(states=[batch_info])
        batch_inc = BatchInc(states=[batch_info])
        save_buff = SaveBuff()
        print_tuple = PrintTuple()
        choose = Choose(states=[task_master])
        steer_worker = SteerWorker(states=[task_master])
        get_core = GetCore(states=[task_master])

        # main connection
        queue_schedule >> tx_deq >> save_buff >> print_tuple >> choose
        save_buff >> batch_inc

        # send
        choose.out_send >> steer_worker
        for i in range(n_workers):
            steer_worker.out[i] >> to_nets[i] >> GetBuff() >> tx_release

        # local
        choose.out_local >> get_core >> rx_enq >> GetBuff() >> tx_release

class TxPipeline(Pipeline):
    state = PerPacket(AddrState)

    def impl(self):
        nic_tx('nic_tx')


nic_rx('nic_rx')
inqueue_get('inqueue_get')
inqueue_advance('inqueue_advance')  # TODO: signature change
outqueue_put('outqueue_put')


c = Compiler(TxPipeline)
c.include = r'''
#include <rte_memcpy.h>
#include "worker.h"
#include "storm.h"
#include "socket.h"
'''
c.depend = {"test_storm": ['list', 'hash', 'hash_table', 'spout', 'count', 'rank', 'worker', 'flexstorm']}
c.generate_code_as_header("flexstorm")
c.compile_and_run([("test_storm", workerid[test])])
