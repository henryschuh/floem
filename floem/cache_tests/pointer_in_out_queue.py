from floem import *

class Storage(State):
    mem = Field(Array(Int, 100))

    def init(self):
        self.mem = lambda x: 'init_mem(%s, 100)' % x

class Mult2(Element):
    this = Persistent(Storage)

    def configure(self):
        self.inp = Input(Pointer(Int), Int)
        self.out = Output(Pointer(Int), Int, Int, Pointer(Int))

    def states(self, storage):
        self.this = storage

    def impl(self):
        self.run_c(r'''
        (int* key, int keylen) = inp();
        
        int x = *key;
        int y = this->mem[x];
        int vallen = sizeof(int);
        
        if (x == 0) {
            y = 0;
            vallen = 0;
        } else if(y == -1) {
            y = 2*x;
            this->mem[x] = y;
        }
        
        output { out(key, keylen, vallen, &y); }
        ''')

class LookUp(Element):
    this = Persistent(Storage)

    def configure(self):
        self.inp = Input(Pointer(Int), Int, Int, Pointer(Int))
        self.out = Output(Pointer(Int), Int, Int, Pointer(Int))

    def states(self, storage):
        self.this = storage

    def impl(self):
        self.run_c(r'''
        (int* key, int keylen, int vallen, int* val) = inp();
        
        int x = *key;
        int y = *val;
        this->mem[x] = y;
        
#ifdef DEBUG
        printf("update storage %d %d\n", x, y);
#endif

        output { out(key, keylen, vallen, val); }
        ''')

class OnlyVal(Element):
    def configure(self):
        self.inp = Input(Pointer(Int), Int, Int, Pointer(Int))
        self.out = Output(Int)

    def impl(self):
        self.run_c(r'''
        (int* key, int keylen, int vallen, int* val) = inp();
        int y = *val;
        if(vallen == 0) y = -1;
        output { out(&y); }
        ''')

class Key2Pointer(Element):
    def configure(self):
        self.inp = Input(Int)
        self.out = Output(Pointer(Int), Int)

    def impl(self):
        self.run_c(r'''
        (int x) = inp();
        state->hash = 0;
        output { out(&x, sizeof(int)); }
        ''')

class KV2Pointer(Element):
    def configure(self):
        self.inp = Input(Int, Int)
        self.out = Output(Pointer(Int), Int, Int, Pointer(Int))

    def impl(self):
        self.run_c(r'''
        (int x, int y) = inp();
        state->hash = 0;
        output { out(&x, sizeof(int), sizeof(int), &y); }
        ''')


class DisplayGet(Element):
    def configure(self):
        self.inp = Input(Pointer(Int), Int, Int, Pointer(Int))

    def impl(self):
        self.run_c(r'''
        (int* key, int keylen, int vallen, int* val) = inp();
        int x = *key;
        //int y = *val;
        
        int y = -1;
        if(vallen > 0) y = *val;
        
        printf("    GET%d VAL%d\n", x, y);
        ''')


class DisplaySet(Element):
    def configure(self):
        self.inp = Input(Pointer(Int), Int, Int, Pointer(Int))

    def impl(self):
        self.run_c(r'''
        (int* key, int keylen, int vallen, int* val) = inp();
        int x = *key;
        printf("    SET%d\n", x);
        ''')

n_queues = 1
class QID(ElementOneInOut):
    def impl(self):
        self.run_c(r'''
        state->qid = state->hash %s %s;
        //printf("qid: key = %s\n", *state.key);
        output { out(); }
        ''' % ('%', n_queues, '%d'))

class DebugSet(ElementOneInOut):
    def impl(self):
        self.run_c(r'''
        printf("debug: key = %d\n", *state.key);
        output { out(); }
        ''')

write_policy = Cache.write_back
write_miss = Cache.write_alloc

CacheGetStart, CacheGetEnd, CacheSetStart, CacheSetEnd, \
CacheState, Key2State, KV2State, State2Key, State2KV = \
    cache_smart.smart_cache('MyCache', Pointer(Int), [Pointer(Int)],
                            var_size=True, hash_value='hash',
                            write_policy=write_policy, write_miss=write_miss)

InEnq, InDeq, InClean = queue_smart.smart_queue("inqueue", 32, 16, n_queues, 2)
OutEnq, OutDeq, OutClean = queue_smart.smart_queue("outqueue", 32, 16, n_queues, 2)

class main(Flow):
    state = PerPacket(CacheState)

    def impl(self):
        storage = Storage()


        class compute(CallableSegment):
            def configure(self):
                self.inp = Input(Int)

            def impl(self):
                enq = InEnq()
                self.inp >> Key2Pointer() >> CacheGetStart() >> Key2State() >> QID() >> enq.inp[0]

        class set(CallableSegment):
            def configure(self):
                self.inp = Input(Int, Int)

            def impl(self):
                enq = InEnq()
                self.inp >> KV2Pointer() >> CacheSetStart() >> KV2State() >> QID() >> enq.inp[1]

        class nic_tx(Segment):
            def impl(self):
                deq = OutDeq()

                self.core_id >> deq
                deq.out[0] >> State2KV() >> CacheGetEnd() >> DisplayGet()
                deq.out[1] >> State2KV() >> CacheSetEnd() >> DisplaySet()

        class server(Segment):
            def impl(self):
                deq = InDeq()
                enq = OutEnq()

                self.core_id >> deq
                deq.out[0] >> State2Key() >> Mult2(states=[storage]) >> KV2State() >> enq.inp[0]
                deq.out[1] >> State2KV() >> LookUp(states=[storage]) >> KV2State() >> enq.inp[1]

        compute('compute')
        set('set')
        nic_tx('nic_tx', cores=[0])
        server('server', cores=[0])


c = Compiler(main)
c.include = r'''
void init_mem(int* mem, int n) {
    int i;
    for(i=0; i<n; i++)
        mem[i] = -1;
}
'''
c.testing = r'''
set(1, 100);
compute(11); compute(1); 
set(11, 222); compute(11); compute(1);
compute(0);
sleep(1);
'''
if write_policy == Cache.write_through:
    c.generate_code_and_run(["SET1", "GET11", "VAL22", "GET1", "VAL100", "SET11", "GET11", "VAL222", "GET1", "VAL100", "GET0", "VAL-1"])
else:
    c.generate_code_and_run()