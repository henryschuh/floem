from dsl import *


def create_fork(name, n, type):
    outports = [Port("out%d" % (i+1), [type]) for i in range(n)]
    calls = ["out%d(x);" % (i+1) for i in range(n)]
    src = "(%s x) = in(); output { %s }" % (type, " ".join(calls))
    return create_element(name, [Port("in", [type])], outports, src)


def create_fork_instance(inst_name, n, type):
    ele_name = "_element_" + inst_name
    ele = create_fork(ele_name, n, type)
    return ele(inst_name)


def create_identity(name, type):
    src = "(%s x) = in(); output { out(x); }" % type
    return create_element(name, [Port("in", [type])], [Port("out", [type])], src)


def create_add(name, type):
    src = "%s x = in1() + in2(); output { out(x); }" % type
    return create_element(name,
                          [Port("in1", [type]), Port("in2", [type])],
                          [Port("out", [type])],
                          r'''int x = in1() + in2(); output { out(x); }''')


def create_add1(name, type):
    src = "%s x = in() + 1; output { out(x); }" % type
    return create_element(name,
                          [Port("in", [type])],
                          [Port("out", [type])],
                          src)


def create_drop(name, type):
    return create_element(name,
                          [Port("in", [type])],
                          [],
                          r'''in();''')

def create_circular_queue(name, type, size):
    prefix = "_%s_" % name
    state_name = prefix + "queue"

    Enqueue = create_element(prefix+ "enqueue",
                             [Port("in", [type])], [],
                             r'''
           (%s x) = in();
           int next = this.tail + 1;
           if(next >= this.size) next = 0;
           if(next == this.head) {
             printf("Circular queue '%s' is full. A packet is dropped.\n");
           } else {
             this.data[this.tail] = x;
             this.tail = next;
           }
           ''' % (type, name), None, [(state_name, "this")])

    Dequeue = create_element(prefix + "dequeue",
                             [], [Port("out", [type])],
                             r'''
           %s x;
           bool avail = false;
           if(this.head == this.tail) {
             printf("Dequeue an empty circular queue '%s'. Default value is returned (for API call).\n");
             //exit(-1);
           } else {
               avail = true;
               x = this.data[this.head];
               int next = this.head + 1;
               if(next >= this.size) next = 0;
               this.head = next;
           }
           output switch { case avail: out(x); }
           ''' % (type, name), None, [(state_name, "this")])

    Queue = create_state(state_name, "int head; int tail; int size; %s data[%d];" % (type, size),
                         [0,0,size, [0]])

    def func(x, t1, t2):
        queue = Queue()
        enq = Enqueue(prefix + "enqueue", [queue])
        deq = Dequeue(prefix + "dequeue", [queue])
        enq(x)
        y = deq()

        t1(enq)
        t2(deq)
        return y

    return create_composite(name, func)


def create_circular_queue_instance(name, type, size):
    ele_name = "_element_" + name
    ele = create_circular_queue(ele_name, type, size)
    return ele(name)


def create_table_instances(put_name, get_name, index_type, val_type, size):
    state_name = ("_table_%s_%d" % (val_type, size)).replace('*', '$')
    state_instance_name = "_table_%s" % put_name
    Table = create_state(state_name, "{0} data[{1}];".format(val_type, size), [[0]])
    TablePut = create_element("_element_" + put_name,
                              [Port("in_index", [index_type]), Port("in_value", [val_type])], [],
                              r'''
              (%s index) = in_index();
              (%s val) = in_value();
              uint32_t key = index %s %d;
              if(this.data[key] == NULL) this.data[key] = val;
              else { printf("Hash collision!\n"); exit(-1); }
              ''' % (index_type, val_type, '%', size),
                              None, [(state_name, "this")])

    TableGet = create_element("_element_" + get_name,
                              [Port("in", [index_type])], [Port("out", [val_type])],
                              r'''
              (%s index) = in();
              uint32_t key = index %s %d;
              %s val = this.data[key];
              if(val == NULL) { printf("No such entry in this table.\n"); exit(-1); }
              this.data[key] = NULL;
              output { out(val); }
              ''' % (index_type, '%', size, val_type), None, [(state_name, "this")])

    table = Table(state_instance_name)
    table_put = TablePut(put_name, [table])
    table_get = TableGet(get_name, [table])
    return table_put, table_get