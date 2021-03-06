from dsl import *

q_buffer = 'q_buffer'
q_entry = 'q_entry'


class circular_queue(State):
    len = Field(SizeT)
    offset = Field(SizeT)
    queue = Field(Pointer(Void))
    clean = Field(SizeT)
    id = Field(Int)
    entry_size = Field(Int)

    def init(self, len=0, queue=0, overlap=8, ready="NULL", done="NULL"):
        self.len = len
        self.offset = 0
        self.queue = queue
        self.clean = 0
        self.entry_size = overlap
        self.declare = False
        self.id = "create_dma_circular_queue((uint64_t) {0}, sizeof({1}), {2}, {3}, {4})"\
            .format(queue.name, queue.__class__.__name__, overlap, ready, done)


class circular_queue_lock(State):
    len = Field(SizeT)
    offset = Field(SizeT)
    queue = Field(Pointer(Void))
    clean = Field(SizeT)
    lock = Field('lock_t')
    id = Field(Int)
    entry_size = Field(Int)

    def init(self, len=0, queue=0, entry_size=0, ready="NULL", done="NULL"):
        self.len = len
        self.offset = 0
        self.queue = queue
        self.clean = 0
        self.entry_size = entry_size
        self.lock = lambda (x): 'qlock_init(&%s)' % x
        self.declare = False
        self.id = "create_dma_circular_queue((uint64_t) {0}, sizeof({1}), {2}, {3}, {4})" \
            .format(queue.name, queue.__class__.__name__, entry_size, ready, done)


def get_field_name(state, field):
    if isinstance(field, str):
        return field

    for s in state.__dict__:
        o = state.__dict__[s]
        if isinstance(o, Field):
            if o == field:
                return s


def create_queue_states(name, type, size, n_insts, entry_size, nameext="", deqext="",
                        declare=True, enq_lock=False, deq_lock=False):
    prefix = "%s_" % name

    class Storage(State): data = Field(Array(type, size))

    Storage.__name__ = prefix + Storage.__name__

    storages = [Storage() for i in range(n_insts)]

    if enq_lock:
        enq = circular_queue_lock
    else:
        enq = circular_queue

    if deq_lock:
        deq = circular_queue_lock
    else:
        deq = circular_queue

    enq_infos = [enq(init=[size, storages[i], entry_size, "enqueue_ready" + nameext, "enqueue_done" + nameext],
                     declare=declare, packed=False)
                 for i in range(n_insts)]
    deq_infos = [deq(init=[size, storages[i], entry_size, "dequeue_ready" + nameext + deqext, "dequeue_done" + nameext],
                     declare=declare, packed=False)
                 for i in range(n_insts)]

    class EnqueueCollection(State):
        insts = Field(Array(Pointer(enq), n_insts))
        def init(self, insts=[0]): self.insts = insts

    EnqueueCollection.__name__ = prefix + EnqueueCollection.__name__

    class DequeueCollection(State):
        insts = Field(Array(Pointer(deq), n_insts))
        def init(self, insts=[0]): self.insts = insts

    DequeueCollection.__name__ = prefix + DequeueCollection.__name__

    # TODO: init pthread_mutex_init(&lock, NULL)

    enq_all = EnqueueCollection(init=[enq_infos])
    deq_all = DequeueCollection(init=[deq_infos])

    return enq_all, deq_all, enq, deq, Storage


def queue_default(name, entry_size, size, insts,
                  enq_blocking=False, deq_blocking=False, enq_atomic=False, deq_atomic=False,
                  clean=False, qid_output=False, checksum=False):
    """
    :param name: queue name
    :param entry_size:
    :param size: number of entries
    :param insts: number of physical queue instances
    :param enq_blocking:
    :param deq_blocking:
    :param enq_atomic:
    :param deq_atomic:
    :param clean: True if queue entry needs to be cleaned before being enqueued again.
    :param qid_output: True if dequeue get element should return queue instance id.
    :param checksum: True to enable checksum.
    :return: EnqueueAlloc, EnqueueSubmit, DequeueGet, DequeueRelease, clean_inst
    """

    prefix = name + "_"
    clean_name = "clean"
    checksum_arg = "true" if checksum else "false"

    class Clean(Element):
        def configure(self):
            self.inp = Input(q_buffer)
            self.out = Output(q_buffer)
            self.special = 'clean'

        def impl(self):
            self.run_c(r'''
            (q_buffer buf) = inp();
            output { out(buf); }
            ''')
    Clean.__name__ = prefix + Clean.__name__
    if clean:
        clean_inst = Clean(name=clean_name)
        clean_name = clean_inst.name
    else:
        clean_inst = None
        clean_name = "no_clean"

    enq_all, deq_all, EnqQueue, DeqQueue, Storage = \
        create_queue_states(name, Uint(8), entry_size * size, insts, entry_size=entry_size, nameext="_var",
                            deqext="_checksum" if checksum else "", declare=False, enq_lock=enq_atomic,
                            deq_lock=deq_atomic)  # TODO: scan => clean

    class EnqueueReserve(Element):
        this = Persistent(enq_all.__class__)
        def states(self): self.this = enq_all

        def configure(self, gap=0, channel=0):
            self.inp = Input(Int, Int)  # len, core
            self.out = Output(q_buffer)
            self.gap = gap
            self.channel = channel

        def impl(self):
            lock = "qlock_lock(&q->lock);" if enq_atomic else ''
            unlock = "qlock_unlock(&q->lock);" if enq_atomic else ''

            noblock = r'''
            %s
            q_buffer buff = enqueue_alloc((circular_queue*) q, len, %d, %s);
            %s
            ''' % (lock, self.gap, clean_name, unlock)

            block = r'''
#ifdef QUEUE_STAT
    static size_t full = 0;
    static struct timeval base, now;
    gettimeofday(&now, NULL);
    if(now.tv_sec >= base.tv_sec + 5) {
        printf("\n>>>>>>>>>>>>>>>>>>>>>>>> QUEUE FULL[''' + name + r''']: q = %p, full/5s = %ld\n", q, full);
        full = 0;
        base = now;
    }
#endif
''' + r'''
#ifndef CAVIUM
    q_buffer buff = { NULL, 0 };
#else
    q_buffer buff = { NULL, 0, 0 };
#endif
    while(buff.entry == NULL) {
        %s
        buff = enqueue_alloc((circular_queue*) q, len, %d, %s);
        %s
#ifdef QUEUE_STAT
        if(buff.entry == NULL) full++;
#endif
   }
   ''' % (lock, self.gap, clean_name, unlock)

            my_blocking = enq_blocking
            if isinstance(enq_blocking, list):
                my_blocking = enq_blocking[self.channel]

            if my_blocking:
                src = block
            else:
                src = noblock

            self.run_c(r'''
            (int len, int c) = inp();
            assert(c < %d);
            %s *q = this->insts[c];
            ''' % (insts, EnqQueue.__name__)
                       + src + r'''
                       //if(entry == NULL) { printf("queue %d is full.\n", c); }
                       //printf("ENQ' core=%ld, queue=%ld, entry=%ld\n", c, q->queue, entry);
                       output { out(buff); }
                       ''')

    class EnqueueSubmit(Element):
        def configure(self):
            self.inp = Input(q_buffer)

        def impl(self):
            self.run_c(r'''
            (q_buffer buf) = inp();
            enqueue_submit(buf, %s);
            ''' % checksum_arg)

    class DequeueGet(Element):
        this = Persistent(deq_all.__class__)
        def states(self): self.this = deq_all

        def configure(self):
            self.inp = Input(Int)
            self.out = Output(q_buffer, Int) if qid_output else Output(q_buffer)

        def impl(self):
            noblock_noatom = "q_buffer buff = dequeue_get((circular_queue*) q);\n"
            block_noatom = r'''
#ifndef CAVIUM
    q_buffer buff = { NULL, 0 };
#else
    q_buffer buff = { NULL, 0, 0 };
#endif
    while(buff.entry == NULL) {
        buff = dequeue_get((circular_queue*) q);
    }
            '''
            noblock_atom = "qlock_lock(&q->lock);\n" + noblock_noatom + "qlock_unlock(&q->lock);\n"
            block_atom = "qlock_lock(&q->lock);\n" + block_noatom + "qlock_unlock(&q->lock);\n"

            if deq_blocking:
                src = block_atom if deq_atomic else block_noatom
            else:
                src = noblock_atom if deq_atomic else noblock_noatom

            src = r'''
#ifdef QUEUE_STAT
    static size_t empty = 0;
    static struct timeval base, now;
    gettimeofday(&now, NULL);
    if(now.tv_sec >= base.tv_sec + 5) {
        printf("\n>>>>>>>>>>>>>>>>>>>>>>>> QUEUE EMPTY[''' + name + r''']: q = %p, empty/5s = %ld\n", q, empty);
        empty = 0;
        base = now;
    }
#endif
''' + src + r'''
#ifdef QUEUE_STAT
    if(buff.entry == NULL) empty++;
#endif
'''

            self.run_c(r'''
            (int c) = inp();
            assert(c < %d);
            %s *q = this->insts[c];
            ''' % (insts, DeqQueue.__name__)
                       + src
                       + r'''
                       output { out(%s); }
                       ''' % ('buff, c' if qid_output else 'buff'))

    class DequeueRelease(Element):
        def configure(self):
            self.inp = Input(q_buffer)

        def impl(self):
            if clean:
                self.run_c(r'''
                (q_buffer buf) = inp();
                dequeue_release(buf, FLAG_CLEAN);
                ''')
            else:
                self.run_c(r'''
                (q_buffer buf) = inp();
                dequeue_release(buf, 0);
                ''')

    EnqueueReserve.__name__ = prefix + EnqueueReserve.__name__
    EnqueueSubmit.__name__ = prefix + EnqueueSubmit.__name__
    DequeueGet.__name__ = prefix + DequeueGet.__name__
    DequeueRelease.__name__ = prefix + DequeueRelease.__name__

    return EnqueueReserve, EnqueueSubmit, DequeueGet, DequeueRelease, clean_inst


def queue_custom(name, entry_type, size, insts, status_field, checksum=False, local=False,
                 enq_blocking=False, enq_atomic=False, enq_output=False,
                 deq_blocking=False, deq_atomic=False):
    """
    :param name: queue name
    :param entry_type:
    :param size: number of entries
    :param insts: number of physical queue instances
    :param status_field: name of status field in the entry. Status field must be fewer than 1 byte.
    :param checksum: name of checksum field. False if no checksum is required.
    :param enq_blocking:
    :param deq_blocking:
    :param enq_atomic:
    :param deq_atomic:
    :param enq_output: enq element has output port.
    :return: Enq, Deq, DeqRelease
    """

    define_state(entry_type)
    status_field = get_field_name(entry_type, status_field)

    entry_type = string_type(entry_type)
    type_star = entry_type + "*"
    if checksum:
        checksum_offset = "(uint64_t) &((%s) 0)->%s" % (type_star, checksum)
    else:
        checksum_offset = None
    type_offset = "(uint64_t) &((%s) 0)->%s" % (type_star, status_field)
    sanitized_name = '_' + entry_type.replace(' ', '_')

    enq_all, deq_all, EnqQueue, DeqQueue, Storage = \
        create_queue_states(name, entry_type, size, insts, entry_size="sizeof(%s)" % entry_type, nameext=sanitized_name,
                            deqext="_checksum" if checksum else "", declare=True, enq_lock=False, deq_lock=False)

    # Extra functions
    enqueue_ready = r'''
int enqueue_ready%s(void* buff) {
  %s dummy = (%s) buff;
  return (dummy->%s == 0)? sizeof(%s): 0;
}
    ''' % (sanitized_name, type_star, type_star, status_field, entry_type)

    enqueue_done = r'''
int enqueue_done%s(void* buff) {
    %s dummy = (%s) buff;
    return (dummy->%s)? sizeof(%s): 0;
}
        ''' % (sanitized_name, type_star, type_star, status_field, entry_type)

    dequeue_ready = r'''
int dequeue_ready%s(void* buff) {
    %s dummy = (%s) buff;
    return (dummy->%s & FLAG_OWN)? sizeof(%s): 0;
}
''' % (sanitized_name, type_star, type_star, status_field, entry_type)

    if checksum:
        dequeue_ready += r'''
int dequeue_ready%s_checksum(void* buff) {
  %s dummy = (%s) buff;
  if(dummy->%s) {
    uint8_t checksum = dummy->%s;
    uint64_t checksum_size = %s;
    uint8_t* p = (uint8_t*) buff;
    uint32_t i;
    for(i=0; i<checksum_size; i++)
      checksum ^= *(p+i);
    return (checksum == 0)? sizeof(%s): 0;
  }
  return 0;
}
    ''' % (sanitized_name, type_star, type_star, status_field, checksum, checksum_offset, entry_type)

    dequeue_done = r'''
int dequeue_done%s(void* buff) {
    %s dummy = (%s) buff;
    return (dummy->%s == 0)? sizeof(%s): 0;
}
        ''' % (sanitized_name, type_star, type_star, status_field, entry_type)

    if entry_type not in Storage.extra_code or checksum:
        Storage.extra_code[entry_type] = enqueue_ready + enqueue_done + dequeue_ready + dequeue_done

    if checksum:
        checksum_code = r'''
    uint8_t checksum = 0;
    uint8_t *data = (uint8_t*) content;
    int checksum_size = %s;
    int i;
    for(i=0; i<checksum_size; i++)
      checksum ^= *(data+i);
    content->%s = checksum; 
    ''' % (checksum_offset, checksum)
        flush_code = "clflush_cache_range(content, type_offset);"
    else:
        checksum_code = ""
        flush_code = ""

    copy = r'''
    int type_offset = %s;
    assert(type_offset > 0);
    assert(p->entry_size - type_offset > 0 && p->entry_size - type_offset <= 64);
    %s content = &q->data[old];
    memcpy(content, x, type_offset);
    __SYNC;
    %s
    content->%s = FLAG_OWN;
    %s
    __SYNC;
    ''' % (type_offset, type_star, flush_code, status_field, checksum_code)

    atomic_src = r'''
    __SYNC;
    size_t old = p->offset;
    size_t new = (old + 1) %s %d;
    while(!__sync_bool_compare_and_swap64(&p->offset, old, new)) {
        old = p->offset;
        new = (old + 1) %s %d;
    }
    ''' % ('%', size, '%', size)

    wait_then_copy = r'''
    // still occupied. wait until empty

    while(q->data[old].%s != 0 || !__sync_bool_compare_and_swap32(&q->data[old].%s, 0, FLAG_INUSE)) {
        __SYNC;
    }
    %s
    '''% (status_field, status_field, copy)

    init_read_cvm = r'''
        uintptr_t addr = (uintptr_t) &q->data[old];
        %s* entry;
        int size = sizeof(%s);
#ifdef DMA_CACHE
        entry = smart_dma_read(p->id, addr, size);
#else
        dma_read(addr, size, (void**) &entry);
#endif
        ''' % (entry_type, entry_type)

    wait_then_copy_cvm = r'''
#ifdef DMA_CACHE
    while(entry == NULL) entry = smart_dma_read(p->id, addr, size);
    assert(entry->%s == 0);
    memcpy(entry, x, size);
    smart_dma_write(p->id, addr, size, entry);
#else
    // TODO: potential race condition here -- slow and fast thread grab the same entry!
    // However, using typemask requires more DMA operations.

    while(entry->%s) dma_read_with_buf(addr, size, entry, 1);
    memcpy(entry, x, size);
    dma_write(addr, size, entry, 1);
#endif
        ''' % (status_field, status_field)

    wait_then_get = r'''
    %s x = &q->data[old];
    while(x->%s != FLAG_OWN || !__sync_bool_compare_and_swap32(&x->%s, FLAG_OWN, FLAG_OWN | FLAG_INUSE)) {
#ifdef QUEUE_STAT
        __sync_fetch_and_add64(&empty[c], 1);
#endif
        __SYNC;
    }
    ''' % (type_star, status_field, status_field)

    wait_then_get_cvm = r'''
#ifdef DMA_CACHE
        while(entry == NULL) entry = smart_dma_read(p->id, addr, size);
        assert(entry->%s != 0);
#else
        // TODO: potential race condition here -- slow and fast thread grab the same entry!
        while(!dequeue_ready%s(entry)) dma_read_with_buf(addr, size, entry, 1);
#endif
        %s* x = entry;
        ''' % (status_field, sanitized_name, entry_type)

    inc_offset = "p->offset = (p->offset + 1) %s %d;\n" % ('%', size)

    class Enqueue(Element):
        this = Persistent(enq_all.__class__)

        def states(self): self.this = enq_all

        def configure(self):
            self.inp = Input(type_star, Int)
            if enq_output:
                self.done = Output(type_star)

            if local:
                self.special = 'queue-local'

        def impl(self):

            stat = r'''
#ifdef QUEUE_STAT
    static size_t drop[10] = {0};
    static struct timeval base, now;
    gettimeofday(&now, NULL);
    if(now.tv_sec >= base.tv_sec + 5) {
        base = now;
        printf("\n>>>>>>>>>>>>>>>>>>>>>>>> QUEUE DROP[''' + name + r''']\n");
        for(int i=0;i<8;i++) { 
          if(drop[i]) printf("queue[%ld]: drop/5s = %ld\n", i, drop[i]);
          drop[i] = 0;
        }
    }
#endif
            '''

            noblock_noatom = stat + r'''
            __SYNC;
            size_t old = p->offset;
            if(q->data[old].%s == 0) {
                %s
                p->offset = (p->offset + 1) %s %d;
            }
#ifdef QUEUE_STAT
            else __sync_fetch_and_add64(&drop[c], 1);
#endif
                ''' % (status_field, copy, '%', size)

            noblock_atom = stat + r'''
    __SYNC;
    bool success = false;
    size_t old = p->offset;

    if(__sync_bool_compare_and_swap32(&q->data[old].%s, 0, FLAG_INUSE)) {
      if(__sync_bool_compare_and_swap64(&p->offset, old, (old + 1) %s %d)) {
        %s
        success = true; 
      } else {
        q->data[old].%s = 0;
      }
    }

#ifdef QUEUE_STAT
    if(!success) __sync_fetch_and_add64(&drop[c], 1);
#endif
    ''' % (status_field, '%', size, copy, status_field)

            block_noatom = "size_t old = p->offset;\n" + wait_then_copy + inc_offset

            block_atom = atomic_src + wait_then_copy

            if enq_blocking:
                src = block_atom if enq_atomic else block_noatom
            else:
                src = noblock_atom if enq_atomic else noblock_noatom

            out_src = "output { done(x); }\n" if enq_output else ''

            self.run_c(r'''
            (%s x, int c) = inp();
            assert(c < %d);
            circular_queue* p = this->insts[c];
            %s* q = p->queue;
            assert(sizeof(q->data[0].%s) == 1);
            ''' % (type_star, insts, Storage.__name__, status_field)
                       + src + out_src)

        def impl_cavium(self):
            noblock_noatom = "size_t old = p->offset;\n" + init_read_cvm + r'''
    if(entry->%s == 0) {
        memcpy(entry, x, size);
#ifdef DMA_CACHE
        smart_dma_write(p->id, addr, size, entry);
#else
        dma_write(addr, size, entry, 1);
#endif
        p->offset = (p->offset + 1) %s %d;
    }
    ''' % (status_field, '%', size)

            noblock_atom = "size_t old = p->offset;\n" + init_read_cvm + r'''
#ifdef DMA_CACHE
    if(entry) {
#else
    // TODO: potential race condition for non DMA_CACHE

    if(entry->%s == 0) {
#endif
        size_t new = (old + 1) %s %d;
        if(cvmx_atomic_compare_and_store64(&p->offset, old, new)) {
            assert(entry->%s == 0);
            memcpy(entry, x, size);
#ifdef DMA_CACHE
            smart_dma_write(p->id, addr, size, entry);
#else
            dma_write(addr, size, entry, 1);
#endif
        }
    }
    ''' % (status_field, '%', size, status_field)

            block_noatom = "size_t old = p->offset;\n" + init_read_cvm + wait_then_copy_cvm + inc_offset

            block_atom = atomic_src + init_read_cvm + wait_then_copy_cvm

            if enq_blocking:
                src = block_atom if enq_atomic else block_noatom
            else:
                src = noblock_atom if enq_atomic else noblock_noatom

            dma_free = r'''
#ifndef DMA_CACHE
    dma_free(entry);
#endif
    '''
            out_src = "output { done(x); }\n" if enq_output else ""


            self.run_c(r'''
            (%s x, int c) = inp();
            assert(c < %d);
            circular_queue* p = this->insts[c];
            %s* q = p->queue;
            ''' % (type_star, insts, Storage.__name__)
                       + src + dma_free + out_src)

    class Dequeue(Element):
        this = Persistent(deq_all.__class__)

        def states(self): self.this = deq_all

        def configure(self):
            self.inp = Input(Int)
            self.out = Output(q_buffer)
            if local:
                self.special = 'queue-local'

        def impl(self):
            noblock_noatom = r'''
            %s x = NULL;
            __SYNC;
            if(q->data[p->offset].%s == FLAG_OWN) {
                x = &q->data[p->offset];
                p->offset = (p->offset + 1) %s %d;
            }
            ''' % (type_star, status_field, '%', size)

            noblock_atom = r'''
    %s x = NULL;
    __SYNC;
    size_t old = p->offset; 
    if(__sync_bool_compare_and_swap32(&q->data[old].%s, FLAG_OWN, FLAG_OWN | FLAG_INUSE)) {
      if(__sync_bool_compare_and_swap64(&p->offset, old, (old + 1) %s %d)) {
        x = &q->data[old];
      } else {
        q->data[old].%s = FLAG_OWN;
      }
    }
    ''' % (type_star, status_field, '%', size, status_field)

            block_noatom = "size_t old = p->offset;\n" + wait_then_get + inc_offset

            block_atom = atomic_src + wait_then_get

            if deq_blocking:
                src = block_atom if deq_atomic else block_noatom
            else:
                src = noblock_atom if deq_atomic else noblock_noatom

            src = r'''
#ifdef QUEUE_STAT
    static size_t empty[10] = {0};
    static struct timeval base, now;
    gettimeofday(&now, NULL);
    if(now.tv_sec >= base.tv_sec + 5) {
        printf("\n>>>>>>>>>>>>>>>>>>>>>>>> QUEUE EMPTY[''' + name + r''']\n");
        base = now;
        for(int i=0;i<10;i++) {
          if(empty[i]) printf("queue[%ld]: empty/5s = %ld\n", i, empty[i]);
          empty[i] = 0;
        }
    }
#endif
''' + src + r'''  
#ifdef QUEUE_STAT
    if(x == NULL)  __sync_fetch_and_add64(&empty[c], 1);
#endif
'''

            self.run_c(r'''
    (int c) = inp();
    assert(c < %d);
    circular_queue* p = this->insts[c];
    %s* q = p->queue;
    ''' % (insts, Storage.__name__)
                       + src
                       + r'''
#ifndef CAVIUM
    q_buffer tmp = {(void*) x, 0};
#else
    q_buffer tmp = {(void*) x, 0, p->id};
#endif
    output { out(tmp); }''')

        def impl_cavium(self):
            noblock_noatom = "size_t old = p->offset;\n" + init_read_cvm + r'''
    %s x = NULL;
#ifdef DMA_CACHE
    if(entry) {
        assert(entry->%s != 0);
#else
    if(dequeue_ready%s(entry)) {
#endif
        x = entry;
        p->offset = (p->offset + 1) %s %d;
    } else {
#ifndef DMA_CACHE
        dma_free(entry);
#endif
    }
    ''' % (type_star, status_field, sanitized_name, '%', size)

            noblock_atom = "size_t old = p->offset;\n" + init_read_cvm + r'''
    %s x = NULL;
    bool success = false;
#ifdef DMA_CACHE
    if(entry) {
#else
    // TODO: potential race condition for non DMA_CACHE

    if(dequeue_ready%s(entry)) {
#endif
        size_t new = (old + 1) %s %d;
        if(__sync_bool_compare_and_swap64(&p->offset, old, new)) {
            x = entry;
            success = true;
            assert(entry->%s != 0);
        }
    }
    if(!success) {
#ifndef DMA_CACHE
        dma_free(entry);
#endif
    }
    ''' % (type_star, sanitized_name, '%', size, status_field)

            block_noatom = "size_t old = p->offset;\n" + init_read_cvm + wait_then_get_cvm + inc_offset

            block_atom = atomic_src + init_read_cvm + wait_then_get_cvm

            if deq_blocking:
                src = block_atom if deq_atomic else block_noatom
            else:
                src = noblock_atom if deq_atomic else noblock_noatom

            debug = r'''printf("deq %ld\n", c);'''

            self.run_c(r'''
            (int c) = inp();
            assert(c < %d);
            circular_queue* p = this->insts[c];
            %s* q = p->queue;
            ''' % (insts, Storage.__name__)
                       #+ debug
                       + src
                       + r'''
                       q_buffer tmp = {(void*) x, addr, p->id};
                       output { out(tmp); }''')

    class Release(Element):
        def configure(self):
            self.inp = Input(q_buffer)
            if local:
                self.special = 'queue-local'

        def impl(self):
            set_owner = "x->%s = 0; __SYNC;" % status_field
            set_checksum = "x->%s = 0; __SYNC;" % checksum if checksum else ""

            self.run_c(r'''
    (q_buffer buff) = inp();
    %s x = (%s) buff.entry;
    if(x) {
        %s
        %s
    }
    ''' % (type_star, type_star, set_checksum, set_owner))

        def impl_cavium(self):
            set_owner = "x->%s = 0;" % status_field
            set_checksum = "x->%s = 0;" % checksum if checksum else ""
            self.run_c(r'''
    (q_buffer buff) = inp();
    %s x = (%s) buff.entry;
    if(x) {
        %s
        %s
#ifdef DMA_CACHE
        smart_dma_write(buff.qid, buff.addr, sizeof(%s), x);
#else
        dma_write(buff.addr, sizeof(%s), x, 1);
        dma_free(x);
#endif
    }
            ''' % (type_star, type_star, set_checksum, set_owner, entry_type, entry_type))


    return Enqueue, Dequeue, Release



