from floem import *

class MyState(State):
    qid = Field(Int)
    index = Field(Int)
    p = Field(Pointer(Int), shared='data_region')  # TODO

class main(Flow):
    state = PerPacket(MyState)

    class Save(Element):
        def configure(self):
            self.inp = Input(Int)
            self.out = Output()

        def impl(self):
            self.run_c(r'''
    state.index = inp(); state.p = data_region; state.qid = 0; output { out(); }
            ''')

    class Display(Element):
        def configure(self):
            self.inp = Input()

        def impl(self):
            self.run_c(r'''
            printf("%d\n", state.p[state.index]); fflush(stdout);
            ''')

    Enq, Deq, Scan = queue_smart.smart_queue("queue", 32, 128, 2, 1)


    class push(CallableSegment):
        def configure(self):
            self.inp = Input(Int)

        def impl(self):
            self.inp >> main.Save() >> main.Enq()

    class pop(CallableSegment):
        def configure(self):
            self.inp = Input(Int)

        def impl(self):
            self.inp >> main.Deq() >> main.Display()

    def impl(self):
        MemoryRegion("data_region", 4 * 100)
        main.push('push', process="queue_shared_p1")
        main.pop('pop', process="queue_shared_p2")
        master_process("queue_shared_p1")


c = Compiler(main)
c.generate_code_as_header()
c.depend = {"queue_shared_p1_main": ['queue_shared_p1'],
            "queue_shared_p2_main": ['queue_shared_p2']}
c.compile_and_run(["queue_shared_p1_main", "queue_shared_p2_main"])