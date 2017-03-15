from dsl import *
from elements_library import *

KeyVal = create_state("KeyVal", "uint16_t keylen; uint16_t vallen; uint8_t key[keylen]; uint8_t val[vallen];")
MSG = create_state("Msg", "KeyVal kv;")

Forward = create_identity("Forward", "Msg*")
f = Forward("get_key_val")

p = create_element_instance("print",
              [Port("in_keylen", ["uint16_t"]), Port("in_key", ["uint8_t*"])],
              [],
               r'''
uint16_t keylen = in_keylen();
uint8_t* key = in_key();
for(int i=0; i<keylen; i++) printf("%d\n", key[i]);
''')

x = f(None)
p(x.get('kv.keylen'), x.get('kv.key'))

c = Compiler()
c.testing = r'''
Msg* m = malloc(sizeof(Msg)+4);
m->kv.keylen = 2;
m->kv.vallen = 2;
uint16_t* key = (uint16_t*) m->kv._rest;
uint16_t* val = ((uint16_t*) m->kv._rest) + 1;
  *key = 11;
  *val = 7;

get_key_val(m);
'''
c.generate_code_and_run([11,0])