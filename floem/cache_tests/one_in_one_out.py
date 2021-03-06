from floem import *


class Mult2(Element):
    def configure(self, *params):
        self.inp = Input(Int)
        self.out = Output(Int, Int)

    def impl(self):
        self.run_c(r'''
        (int x) = inp();
        output { out(x, 2*x); }
        ''')

class OnlyVal(Element):
    def configure(self):
        self.inp = Input(Int, Int)
        self.out = Output(Int)

    def impl(self):
        self.run_c(r'''
        (int key, int val) = inp();
        output { out(val); }
        ''')

CacheGetStart, CacheGetEnd, CacheSetStart, CacheSetEnd, \
CacheState, Key2State, KV2State, State2Key, State2KV = \
    cache_smart.smart_cache('MyCache', Int, [Int], write_policy=Cache.write_back, write_miss=Cache.write_alloc)


class MyState(CacheState):
    pass


class main(Flow):
    state = PerPacket(MyState)

    def impl(self):
        class compute(CallableSegment):
            def configure(self):
                self.inp = Input(Int)
                self.out = Output(Int)

            def impl(self):
                self.inp >> CacheGetStart() >> Mult2() >> CacheGetEnd() >> OnlyVal() >> self.out

        class set(CallableSegment):
            def configure(self):
                self.inp = Input(Int, Int)

            def impl(self):
                self.inp >> CacheSetStart() >> CacheSetEnd() >> library.Drop()

        compute('compute')
        set('set')


c = Compiler(main)
c.testing = r'''
set(1, 100);
out(compute(11)); out(compute(1)); out(compute(11)); out(compute(1)); 
set(11, 222); out(compute(11)); out(compute(1));
'''
c.generate_code_and_run([22,100,22,100, 222, 100])