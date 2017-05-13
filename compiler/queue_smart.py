from dsl import *

class Queue:
    def __init__(self, name, size, n_cores, n_cases):
        self.name = name
        self.size = size
        self.n_cores = n_cores
        self.n_cases = n_cases
        self.enq = None
        self.deq = None


class QueueVariableSizeOne2Many(Queue):
    def __init__(self, name, size, n_cores):
        Queue.__init__(self, name, size, n_cores)


def smart_circular_queue_variablesize_one2many(name, size, n_cores, n_cases):
    prefix = "_%s_" % name
    queue = Queue(name, size, n_cores, n_cases)
    Smart_enq = create_element(prefix + "smart_enq_ele",
                               [Port("in" + str(i), []) for i in range(n_cases)],
                               [Port("out", [])], "state.core; output { out(); }")

    Smart_deq = create_element(prefix + "smart_deq_ele",
                               [Port("in_core", ["size_t"]), Port("in", [])],
                               [Port("out" + str(i), []) for i in range(n_cases)],"output { }")

    Smart_enq.special = queue
    Smart_deq.special = queue

    return Smart_enq, Smart_deq


def smart_circular_queue_variablesize_one2many_instances(name, size, n_cores, n_cases):
    Enq, Deq = smart_circular_queue_variablesize_one2many(name, size, n_cores, n_cases)
    enq = Enq()
    deq = Deq()

    x = enq()
    deq(None, x)

    Enq.special.enq = enq
    Deq.special.deq = deq

    return enq, deq