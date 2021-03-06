from dsl import *
import common, graph_ir, library

'''
state: per-packet state
'''
def cache_default(name, key_type, val_type,
                  state=False, key_name=None, val_names=None, keylen_name=None, vallen_name=None,
                  hash_value=False, var_size=False, update_func='f',
                  write_policy=graph_ir.Cache.write_through, write_miss=graph_ir.Cache.no_write_alloc,
                  set_query=True, n_hashes=2**15):
    if write_policy == graph_ir.Cache.write_back:
        assert write_miss == graph_ir.Cache.write_alloc, \
            "Cache: cannot use write-back policy with no write allocation on write misses."

    prefix = name + '_'

    if not var_size:
        for v in val_type:
            assert not common.is_pointer(v), "Cache with non-variable-size must not return any pointer value."

    class hash_table(State):
        buckets = Field(Array('cache_bucket', n_hashes))

        def init(self):
            self.buckets = lambda (x): 'cache_init(%s, %d)' % (x, n_hashes)

    hash_table.__name__ = prefix + hash_table.__name__
    my_hash_table = hash_table()

    if not var_size:
        kv_params_real = [key_type] + val_type
    else:
        kv_params_real = [key_type, Int, Int] + val_type

    if state:
        key_params = []
        kv_params = []
    else:
        if not var_size:
            key_params = [key_type]
            kv_params =  kv_params_real
        else:
            key_params = [key_type, Int]
            kv_params = kv_params_real

    # Key
    if common.is_pointer(key_type):
        key_arg = 'key'
        keylen_arg = 'keylen' if var_size else 'sizeof({0})'.format(key_type[:-1])
    else:
        key_arg = '&key'
        keylen_arg = 'sizeof({0})'.format(key_type)

    # Value base type
    val_base_type = []
    for i in range(len(val_type)):
        if common.is_pointer(val_type[i]):
            val_base_type.append(val_type[i][:-1])
        else:
            val_base_type.append(val_type[i])

    # Value
    return_vals = []
    val_assign_src = r'''
    uint8_t* p;
    p = ((uint8_t*) it->content) + %s;
    ''' % keylen_arg

    for i in range(len(val_type)):
        if common.is_pointer(val_type[i]):
            val_assign_src += "val{1} = ({0}*) p;\n".format(val_base_type[i], i)
        else:
            val_assign_src += "val{1} = *(({0}*) p);\n".format(val_base_type[i], i)
        val_assign_src += "p += sizeof({0});\n".format(val_base_type[i])
        return_vals.append("val{0}".format(i))


    val_decl = ""
    for i in range(len(val_type)):
        val_decl += "{0} val{1} = 0; ".format(val_type[i], i)
    val_src = r'''
    %s
    if(it != NULL) {
        %s
    }
                ''' % (val_decl, val_assign_src)


    # Update
    pointer_vals = []
    update_vals = []
    update_src = "uint8_t* p;"
    update_after = ""
    for i in range(len(val_type)):
        update_src += " {0}* p{1} = 0;".format(val_base_type[i], i)
        update_src += " {0} update{1} = 0;".format(val_type[i], i)

    update_src += r'''
    if(it != NULL) {
        p = ((uint8_t*) it->content) + %s;
        ''' % keylen_arg

    for i in range(len(val_type)):
        update_src += "p{1} = ({0}*) p;\n".format(val_base_type[i], i)
        update_src += "p += sizeof({0});\n".format(val_base_type[i])
        pointer_vals.append("p{0}".format(i))

        if common.is_pointer(val_type[i]):
            update_after += "update{0} = p{0};\n".format(i)
        else:
            update_after += "update{0} = *p{0};\n".format(i)
        update_vals.append("update{0}".format(i))

    if not var_size:
        update_src += "%s(%s, %s);\n" % (update_func, ','.join(pointer_vals), ','.join(return_vals))
    else:
        update_src += "%s(last_vallen, %s, %s);\n" % (update_func, ','.join(pointer_vals), ','.join(return_vals))
    update_src += update_after
    update_src += "}\n"

    # Compute hash
    if hash_value:
        compute_hash = "uint32_t hv = state->hash;"
    else:
        compute_hash = "uint32_t hv = jenkins_hash(%s, %s); state->hash = hv;" % (key_arg, keylen_arg)

    extra_return = 'keylen, last_vallen,' if var_size else ''

    class CacheGet(Element):
        this = Persistent(hash_table)

        def configure(self):
            self.inp = Input(*key_params)
            self.hit = Output(*kv_params)
            self.miss = Output(*key_params)
            self.fail = Output()
            self.this = my_hash_table

        def impl(self):
            if not var_size:
                if state:
                    input_src = "%s key = state->%s;" % (key_type, key_name)
                    output_src = ' '.join(["state->%s = %s;" % (s, v) for s, v in zip(val_names, return_vals)]) + \
                                 " output switch { case it: hit(); case success: miss(); else: fail(); }"
                else:
                    input_src = "(%s key) = inp();" % (key_type)
                    output_src = "output switch { case it: hit(key, %s); case true: miss(key); else: fail(); }" % ','.join(return_vals)

                self.run_c(r'''
                %s
                %s
                bool success;
                citem* it = cache_get(this->buckets, %d, %s, %s, hv, &success);
                %s
                state->cache_item = it;
                
                %s
                ''' % (input_src, compute_hash, n_hashes, key_arg, keylen_arg, val_src, output_src))
            else:
                if state:
                    input_src = "%s key = state->%s; int keylen = state->%s;" % (key_type, key_name, keylen_name)
                    output_src = "state->%s = (it)? it->last_vallen: 0;" % vallen_name + \
                                 ' '.join(["state->%s = %s;" % (s, v) for s, v in zip(val_names, return_vals)]) + \
                                 " output switch { case it: hit(); case success: miss(); else: fail(); }"
                else:
                    input_src = "(%s key, int keylen) = inp();" % (key_type)
                    output_src = "output switch { case it: hit(key, keylen, it->last_vallen, %s); case true: miss(key, keylen);" \
                                 % ','.join(return_vals) \
                                 + " else: fail(); }"

                self.run_c(r'''
                %s
                %s
                bool success;
                citem* it = cache_get(this->buckets, %d, %s, %s, hv, &success);
                %s
                state->cache_item = it;
                
                %s
                ''' % (input_src, compute_hash, n_hashes, key_arg, keylen_arg, val_src, output_src))

    # Item
    type_vals = []
    vals = []
    item_size = 'sizeof(citem)'
    for i in range(len(val_type)):
        type_vals.append("{0} val{1}".format(val_type[i], i))
        vals.append("val{0}".format(i))

    for i in range(len(val_type)-1):
        item_size += ' + sizeof(%s)' % val_base_type[i]

    if not var_size:
        last_vallen_arg = ' + sizeof(%s)' % val_base_type[-1]
    else:
        last_vallen_arg = 'last_vallen'

    item_size += ' + %s + %s' % (last_vallen_arg, keylen_arg)

    item_src = r'''
    int item_size = %s;
    citem* it = NULL;
    //printf("keylen = %s, vallen = %s\n", keylen, last_vallen);
    if(keylen > 0 && last_vallen > 0) {
        it = shared_mm_malloc(item_size);
        it->hv = hv;
        it->keylen = keylen;
        it->last_vallen = last_vallen;
        uint8_t* p = it->content;
    ''' % (item_size, '%d', '%d')

    if common.is_pointer(key_type):
        item_src += "memcpy(p, key, keylen);\n"
    else:
        item_src += "memcpy(p, &key, keylen);\n"
    item_src += "p += keylen;\n"

    for i in range(len(val_type) - 1):
        if common.is_pointer(val_type[i]):
            item_src += "memcpy(p, val{0}, sizeof({1}));\n".format(i, val_base_type[i])
        else:
            item_src += "memcpy(p, &val{0}, sizeof({1}));\n".format(i, val_base_type[i])
        item_src += "p += sizeof({0});\n".format(val_base_type[i])

    if common.is_pointer(val_type[-1]):
        item_src += "memcpy(p, val{0}, last_vallen);\n".format(len(val_type) - 1)
    else:
        item_src += "memcpy(p, &val{0}, last_vallen);\n".format(len(val_type) - 1)
    item_src += "}\n"

    item_src2 = item_src
    replace = 'true' if write_miss==graph_ir.Cache.write_alloc else 'false'
    item_src += r'''
    state->cache_item = NULL;
    bool success = false;
    if(it) {
        citem *rit = cache_put(this->buckets, %d, it, %s, &success);
    ''' % (n_hashes, replace)

    if write_policy == graph_ir.Cache.write_back:
        item_src += r'''
        state->cache_item = NULL;
        if(rit) {
            if(rit->evicted & 2) state->cache_item = rit;  // to be evict & release & free.
            else cache_release(rit);
        }
        '''
    else:
        item_src += r'''
        state->cache_item = NULL;
        if(rit) {
            if(rit->evicted & 2) { cache_release(rit); shared_mm_free(rit); }
            else cache_release(rit);
        }
        '''

    item_src += r'''
    }
    '''

    # Item source v2
    if state:
        val_state_src = ' '.join(["state->%s = %s;" % (s, v) for s, v in zip(val_names, return_vals)])
        if common.is_pointer(key_type):
            val_state_src += "state->%s = (%s) it->content; " % (key_name, key_type)
        else:
            val_state_src += "%s* key = (%s*) it->content; " % (key_type, key_type)
            val_state_src += "state->%s = *key; " % key_name

        if var_size:
            val_state_src += "state->%s = it->keylen;" % keylen_name
            val_state_src += "state->%s = it->last_vallen;" % vallen_name
    else:
        val_state_src = ''

    item_src2 += r'''
    state->cache_item = NULL;
    bool success = false;
    if(it) {
        citem* rit = cache_put_or_get(this->buckets, %d, it, true, &success);
        if(rit) {
            if(rit->evicted == 2) {
                cache_release(rit);
                shared_mm_free(rit);
            } else if(rit->evicted == 3) {
                state->cache_item = rit;
            } else {
                it = rit;
                state->cache_item = it;
                %s
                %s
            }
        }
    } 
    ''' % (n_hashes, val_assign_src, val_state_src)

    # key-value input/out src
    if not var_size:
        if state:
            kv_input_src = r'''
            %s key = state->%s;
            %s
            int keylen = %s;
            int last_vallen = %s;
            ''' % (key_type, key_name,
                   ' '.join(["%s %s = state->%s;" % (t, v, s) for s, v, t in zip(val_names, return_vals, val_type)]),
                   keylen_arg, last_vallen_arg)
        else:
            kv_input_src = r'''
            (%s key, %s) = inp();
            int keylen = %s;
            int last_vallen = %s;
            ''' % (key_type, ','.join(type_vals), keylen_arg, last_vallen_arg)
    else:
        if state:
            kv_input_src = r'''
            %s key = state->%s;
            %s
            int keylen = state->%s;
            int last_vallen = state->%s;
            ''' % (key_type, key_name,
                   ' '.join(["%s %s = state->%s;" % (t, v, s) for s, v, t in zip(val_names, return_vals, val_type)]),
                   keylen_name, vallen_name)
        else:
            kv_input_src = r'''
            (%s key, int keylen, int last_vallen, %s) = inp();
            ''' % (key_type, ','.join(type_vals))

    if state:
        kv_output_src = r'''
        output switch { case success: out(); else: fail(); }
        '''
    else:
        kv_output_src = r'''
        output switch { case success: out(key, %s %s); else: fail(); }
        ''' % (extra_return, ','.join(return_vals))

    class CacheSet(Element):
        this = Persistent(hash_table)

        def configure(self):
            self.inp = Input(*kv_params)
            self.out = Output(*kv_params)
            self.fail = Output()
            self.this = my_hash_table

        def impl(self):
            self.run_c(kv_input_src + compute_hash + item_src + kv_output_src)

    class CacheSetGet(Element):
        this = Persistent(hash_table)

        def configure(self):
            self.inp = Input(*kv_params)
            self.out = Output(*kv_params)
            self.this = my_hash_table

        def impl(self):
            if state:
                my_kv_output_src = r'''
                output { out(); }
                '''
            else:
                my_kv_output_src = r'''
                output { out(key, %s %s); }
                ''' % (extra_return, ','.join(return_vals))
            self.run_c(kv_input_src + compute_hash + item_src2 + my_kv_output_src)

    class CacheDelete(Element):
        this = Persistent(hash_table)

        def configure(self):
            self.inp = Input(*kv_params)
            self.out = Output(*kv_params)
            self.fail = Output()
            self.this = my_hash_table

        def impl(self):
            if common.is_pointer(key_type):
                del_src = r'''
                bool success;
                cache_delete(this->buckets, %d, key, keylen, hv, &success);
                ''' % n_hashes
            else:
                del_src = r'''
                bool success;
                cache_delete(this->buckets, %d, &key, keylen, hv, &success);
                ''' % n_hashes

            self.run_c(kv_input_src + compute_hash + del_src + kv_output_src)

    # class CacheUpdate(Element):
    #     this = Persistent(hash_table)
    #
    #     def configure(self):
    #         if not var_size:
    #             self.inp = Input(key_type, *val_type)
    #             self.hit = Output(key_type, *val_type)
    #             self.miss = Output(key_type, *val_type)
    #         else:
    #             self.inp = Input(key_type, Int, Int, *val_type)
    #             self.hit = Output(key_type, Int, Int, *val_type)
    #             self.miss = Output(key_type, Int, Int, *val_type)
    #         self.this = my_hash_table
    #
    #     def impl(self):
    #         if hash_value:
    #             compute_hash = "uint32_t hv = state->%s;" % hash_value
    #         else:
    #             compute_hash = "uint32_t hv = jenkins_hash(%s, %s);" % (key_arg, keylen_arg)
    #
    #         if not var_size:
    #             input_src = r'''
    #             (%s key, %s) = inp();
    #             int keylen = %s;
    #             int last_vallen = %s;
    #             ''' % (key_type, ','.join(type_vals), keylen_arg, last_vallen_arg)
    #         else:
    #             input_src = r'''
    #             (%s key, int keylen, int last_vallen, %s) = inp();
    #             '''% (key_type, ','.join(type_vals))
    #
    #         get_src = "citem *it = cache_get(this->buckets, %d, %s, %s, hv);\n" % (n_buckets, key_arg, keylen_arg)
    #
    #         # if not var_size:
    #         #     rel_src = "cache_release(it);\n"
    #         # else:
    #         rel_src = "state->cache_item = it;\n"
    #
    #
    #         if not var_size:
    #             output_src = r'''
    #             output switch {
    #                 case it: hit(key, %s);
    #                 else: miss(key, %s);
    #             }
    #             ''' % (','.join(update_vals), ','.join(return_vals))
    #         else:
    #             output_src = r'''
    #             output switch {
    #                 case it: hit(key, keylen, last_vallen, %s);
    #                 else: miss(key, keylen, last_vallen, %s);
    #             }
    #             ''' % (','.join(update_vals), ','.join(return_vals))
    #
    #         self.run_c(input_src + compute_hash + get_src + update_src + rel_src + output_src)


    class FreeOrRelease(Element):

        def configure(self):
            self.inp = Input()

        def impl(self):
            self.run_c(r'''
            citem* it = state->cache_item;
            if(it) {
                //printf("it->evicted = %d\n", it->evicted);
                if(it->evicted & 2) { 
                    cache_release(it); 
                    shared_mm_free(it); 
                    //printf("free %p\n", it); 
                }
                else { 
                    cache_release(it); 
                }
#ifdef DEBUG
                printf("release %p\n", it); 
#endif
                state->cache_item = NULL;
            }
            ''')

    class Free(Element):

        def configure(self):
            self.inp = Input()

        def impl(self):
            self.run_c(r'''
            citem* it = state->cache_item;
            if(it && it->evicted & 2) { 
                cache_release(it); 
                shared_mm_free(it);
#ifdef DEBUG
                printf("release %p\n", it); 
#endif
                state->cache_item = NULL;
            }
            ''')

    class Evict(Element):
        def configure(self):
            self.inp = Input()
            self.out = Output(*kv_params)

        def impl(self):
            extra_return = 'it->keylen, it->last_vallen,' if var_size else ''
            if state:
                output_src = "output switch { case evict: out(); }"
            else:
                output_src = "output switch { case evict: out((int*) it->content, %s %s); } " % \
                             (extra_return, ','.join(return_vals))

            hash_src = "state->hash = it->hv;" if hash_value else ''

            self.run_c(r'''
            citem *it = state->cache_item;
            bool evict = false;
            %s
            if(it && it->evicted == 3) {
                evict = true;
                int keylen = it->keylen;
                %s
                %s
                %s
            }
            %s
            ''' % (val_decl, val_assign_src, val_state_src, hash_src, output_src))

    class EvictSave(Element):
        def configure(self):
            self.inp = Input()
            self.out = Output()
            self.revert = Output(*kv_params_real)
            self.outports_order = ['out', 'revert']

        def impl(self):
            save_src = "%s _key = state->%s; " % (key_type, key_name)
            returns = ['_key']

            if var_size:
                save_src += "int _keylen = state->%s; " % keylen_name
                save_src += "int _vallen = state->%s; " % vallen_name
                returns.append('_keylen')
                returns.append('_vallen')

            for i in range(len(val_type)):
                save_src += "%s _val%d = state->%s; " % (val_type[i], i, val_names[i])
                returns.append("_val%d" % i)

            output_src = "output { out(); revert(%s); } " % ','.join(returns)

            self.run_c(r'''
            // save original key, val to temp
            %s
            
            // prepare state->key state->val for eviction
            citem *it = state->cache_item;
            int keylen = it->keylen;
            %s
            %s
            %s
            
            %s
            ''' % (save_src, val_decl, val_assign_src, val_state_src, output_src))

    class EvictRevert(Element):
        def configure(self):
            self.inp = Input(*kv_params_real)

        def impl(self):
            if not var_size:
                src = r'''
                (%s key, %s) = inp();
                state->%s = key;
                ''' % (key_type, ','.join(type_vals), key_name)
            else:
                src = r'''
                (%s key, int keylen, int last_vallen, %s) = inp();
                state->%s = key;
                state->%s = keylen;
                state->%s = last_vallen;
                ''' % (key_type, ','.join(type_vals), key_name, keylen_name, vallen_name)

            for i in range(len(val_type)):
                src += "state->%s = val%d; " % (val_names[i], i)

            self.run_c(src)

    class Miss(Element):
        def configure(self):
            self.inp = Input(*kv_params)
            self.out = Output(*kv_params)

        def impl(self):
            if state:
                self.run_c(r'''
                bool miss = (state->cache_item == NULL);
                output switch { case miss: out(); }
                ''')

            else:
                extra_args = 'int keylen, int last_vallen,' if var_size else ''
                extra_return = 'keylen, last_vallen,' if var_size else ''
                self.run_c(r'''
                (%s key, %s %s) = inp();
                bool miss = (state->cache_item == NULL);
                output switch { case miss: out(key, %s %s); }
                ''' % (key_type, extra_args, ','.join(type_vals), extra_return, ','.join(return_vals)))

    class ForkRel(Element):
        def configure(self):
            self.inp = Input(*kv_params)
            self.out = Output(*kv_params)
            self.release = Output()
            self.outports_order = ['out', 'release']

        def impl(self):
            if state:
                self.run_c(r'''
                output { out(); release(); }
                ''')

            else:
                extra_args = 'int keylen, int last_vallen,' if var_size else ''
                extra_return = 'keylen, last_vallen,' if var_size else ''
                self.run_c(r'''
                (%s key, %s %s) = inp();
                output { out(key, %s %s); release(); }
                ''' % (key_type, extra_args, ','.join(type_vals), extra_return, ','.join(return_vals)))

    class ForkRelKeyOnly(Element):
        def configure(self):
            self.inp = Input(*key_params)
            self.out = Output(*key_params)
            self.release = Output()
            self.outports_order = ['out', 'release']

        def impl(self):
            if state:
                self.run_c(r'''
                output { out(); release(); }
                ''')

            else:
                if var_size:
                    self.run_c(r'''
                    (%s key, int keylen) = inp();
                    output { out(key, keylen); release(); }
                    ''' % (key_type))
                else:
                    self.run_c(r'''
                    (%s key) = inp();
                    output { out(key); release(); }
                    ''' % (key_type))

    class Fork(Element):
        def configure(self):
            self.inp = Input(*kv_params)
            self.out1 = Output(*kv_params)
            self.out2 = Output(*kv_params)
            self.outports_order = ['out1', 'out2']

        def impl(self):
            if state:
                self.run_c(r'''
                output { out1(); out2(); }
                ''')
            else:
                if not var_size:
                    return_src = 'key, ' + ','.join(return_vals)
                    self.run_c(r'''
                    (%s key, %s) = inp();
                    output { out1(%s); out2(%s); }
                    ''' % (key_type, ','.join(type_vals), return_src, return_src))
                else:
                    return_src = 'key, keylen, last_vallen, ' + ','.join(return_vals)
                    self.run_c(r'''
                    (%s key, int keylen, int last_vallen, %s) = inp();
                    output { out1(%s); out2(%s); }
                    ''' % (key_type, ','.join(type_vals), return_src, return_src))

    class ForkEvictFree(Element):
        def configure(self):
            self.inp = Input()
            self.evict = Output()
            self.free = Output()
            self.outports_order = ['evict', 'free']

        def impl(self):
            self.run_c(r'''
            output { evict(); free(); }
            ''')

    class EvictComposite(Composite):
        def configure(self):
            self.inp = Input()
            self.out = Output(*kv_params)

        def impl(self):
            evict = Evict()
            if state:
                save = EvictSave()
                revert = EvictRevert()

                self.inp >> evict >> save >> self.out
                save.revert >> revert
            else:
                self.inp >> evict >> self.out

    library.Drop(create=False, force=True)
    class GetComposite(Composite):
        def configure(self):
            self.inp = Input(*key_params)
            self.out = Output(*kv_params)
            self.query_begin = Output(*key_params)
            self.query_end = Input(*kv_params)
            self.enq_out = Output()
            if write_policy == graph_ir.Cache.write_back and set_query:
                self.evict_begin = Output(*kv_params)

        def impl(self):
            cache_get = CacheGet()
            cache_set_get = CacheSetGet()
            fork_rel = ForkRelKeyOnly()

            self.inp >> fork_rel >> cache_get
            fork_rel.release >> self.enq_out

            # Lock fail
            cache_get.fail >> library.Drop()

            # Miss
            fork2 = ForkRel()
            cache_get.miss >> self.query_begin
            self.query_end >> cache_set_get >> fork2
            fork2.release >> FreeOrRelease()

            if write_policy == graph_ir.Cache.write_back and set_query:
                fork3 = Fork()
                fork2 >> fork3
                fork3.out2 >> self.out
                fork3.out1 >> EvictComposite() >> self.evict_begin
            else:
                fork2 >> self.out

            # Get (come after miss because resource mapping on miss path is the default)
            fork = ForkRel()
            cache_get.hit >> fork >> self.out
            fork.release >> FreeOrRelease()

    class SetWriteBack(Composite):
        def configure(self):
            self.inp = Input(*kv_params)
            self.out = Output(*kv_params)
            self.query_begin = Output(*kv_params)
            self.enq_out = Output()

        def impl(self):
            cache_set = CacheSet()
            fork = Fork()
            fork_rel = ForkRel()

            # Lock fail
            cache_set.fail >> library.Drop()

            self.inp >> fork_rel >> cache_set >> fork
            fork_rel.release >> self.enq_out
            fork.out2 >> self.out

            if write_miss == graph_ir.Cache.write_alloc:
                evict_then_free = ForkEvictFree()
                fork.out1 >> evict_then_free
                evict_then_free.evict >> EvictComposite() >> self.query_begin
                evict_then_free.free >> Free()
            else:
                fork.out2 >> Miss() >> self.query_begin


    class SetWriteThrough(Composite):
        def configure(self):
            self.inp = Input(*kv_params)
            self.out = Output(*kv_params)
            self.query_begin = Output(*kv_params)
            self.query_end = Input(*kv_params)
            self.enq_out = Output()

        def impl(self):
            fork = Fork()
            fork_rel = ForkRel()
            cache_del = CacheDelete()
            cache_set = CacheSet()

            self.inp >> fork_rel >> cache_del >> self.query_begin
            fork_rel.release >> self.enq_out
            self.query_end >> fork
            fork.out1 >> self.out
            fork.out2 >> cache_set >> library.Drop()

            # Lock fail
            cache_del.fail >> library.Drop()
            cache_set.fail >> library.Drop()

    return GetComposite, SetWriteBack if write_policy==graph_ir.Cache.write_back else SetWriteThrough
