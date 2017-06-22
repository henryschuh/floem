from dsl2 import *
import queue_smart2
from compiler import Compiler

class MyState(State):
    core = Field(Int)
    keylen = Field(Int)
    key = Field(Pointer(Uint(8)), copysize='state.keylen')  # TODO

class main(Pipeline):
    state = PerPacket(MyState)

    class Save(Element):
        def configure(self):
            self.inp = Input(Int, Uint(8))
            self.out = Output()

        def impl(self):
            self.run_c(r'''
    (int len, uint8_t data) = inp();
    state.core = 0;
    state.key = (uint8_t *) malloc(len);
    state.keylen = len;
    for(int i=0; i<len ; i++)
        state.key[i] = data;
    output { out(); }
            ''')

    class Display(Element):
        def configure(self):
            self.inp = Input()

        def impl(self):
            self.run_c(r'''
            printf("%d %d %d\n", state.keylen, state.key[0], state.key[state.keylen-1]);
            fflush(stdout);
            ''')

    Enq, Deq, Scan = queue_smart2.smart_queue("queue", 256, 2, 1)

    class push(API):
        def configure(self):
            self.inp = Input(Int, Uint(8))

        def impl(self):
            self.inp >> main.Save() >> main.Enq()

    class pop(API):
        def configure(self):
            self.inp = Input(Size)

        def impl(self):
            self.inp >> main.Deq() >> main.Display()

    def impl(self):
        main.push('push', process="queue_shared_data1")
        main.pop('pop', process="queue_shared_data2")
        master_process("queue_shared_data1")

c = Compiler(main)
c.include = r'''
#include <rte_memcpy.h>
#include "../queue.h"
#include "../shm.h"
'''

c.generate_code_as_header()
c.depend = {"queue_shared_data1_main": ['queue_shared_data1'],
            "queue_shared_data2_main": ['queue_shared_data2']}
c.compile_and_run(["queue_shared_data1_main", "queue_shared_data2_main"])