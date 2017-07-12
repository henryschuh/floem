from dsl2 import *
import queue_smart2, net_real
from compiler import Compiler

class MyState(State):
    core = Field(Int)
    keylen = Field(Int)
    key = Field(Pointer(Uint(8)), copysize='state.keylen')
    p = Field(Pointer(Int), shared='data_region')

class Count(State):
    count = Field(Int)
    def init(self):
        self.count = 0

class main(Pipeline):
    state = PerPacket(MyState)

    class Save(Element):
        this = Persistent(Count)

        def configure(self):
            self.inp = Input('void*', 'void*')
            self.out = Output()
            self.this = Count()

        def impl(self):
            self.run_c(r'''
    inp();
    this->count++;
    printf("inject = %d\n", this->count);
    state.core = 0;
    state.key = (uint8_t *) malloc(this->count);
    state.keylen = this->count;
    int i;
    for(i=0; i<this->count ; i++)
        state.key[i] = this->count;

    int* p = data_region;
    p[this->count] = 100 + this->count;
    state.p = &p[this->count];
    output { out(); }
            ''')

        def impl_cavium(self):
            self.run_c(r'''
    inp();
    this->count++;
    printf("inject = %d\n", this->count);
    state.core = 0;
    state.key = (uint8_t *) malloc(this->count);
    state.keylen = this->count;
    int i;
    for(i=0; i<this->count ; i++)
        state.key[i] = this->count;

    int* p = data_region;
    void* addr = &p[Count0->count];
    int* x;
    dma_buf_alloc((void**) &x);
    *x = my_ntohl(100 + Count0->count);
    dma_write((uintptr_t) addr, sizeof(int), x);
    dma_free(x);
    _state->p = addr;

    output { out(); }
            ''')

    class Display(Element):
        def configure(self):
            self.inp = Input()

        def impl(self):
            self.run_c(r'''
            printf("%d %d %d %d\n", state.keylen, state.key[0], state.key[state.keylen-1], *state.p);
            fflush(stdout);
            ''')

    Enq, Deq, Scan = queue_smart2.smart_queue("queue", 256, 2, 1, blocking=True)

    class push(InternalLoop):
        def impl(self):
            from_net = net_real.FromNet()
            from_net_free = net_real.FromNetFree()

            from_net >> main.Save() >> main.Enq()
            from_net >> from_net_free

    class pop(InternalLoop):
        # def configure(self):
        #     self.inp = Input(Size)

        def impl(self):
            self.core_id >> main.Deq() >> main.Display()

    def impl(self):
        MemoryRegion("data_region", 4 * 100)
        main.push('push', device=target.CAVIUM)
        main.pop('pop', process="varsize_enq")

master_process("varsize_enq")

c = Compiler(main)
c.generate_code_as_header()