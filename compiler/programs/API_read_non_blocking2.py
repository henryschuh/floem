from compiler import *
from thread_allocation import *

p = Program(
    State("Buffer", "int x; int avail;", "0,0"),
    Element("Save",
            [Port("in", ["int"])],
            [],
            r'''if(this.avail==1) { printf("Failed.\n"); exit(-1); } this.x = in(); this.avail = 1;''',
            None,
            [("Buffer", "this")]),
    Element("Load",
            [],
            [Port("out", ["int", "int"])],
            r'''
            int x = 0; int avail = 0;
            if(this.avail==1) { x = this.x; avail = 1; this.avail = 0; }
            out(x, avail);''',
            None,
            [("Buffer", "this")]),
    StateInstance("Buffer", "b"),
    ElementInstance("Save", "save", ["b"]),
    ElementInstance("Load", "load", ["b"]),
    APIFunction("read", "load", None, "load", "out", "ReadReturn")
)

g = generate_graph(p)
generate_code(g)