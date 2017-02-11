from graph import Element, Port, State


def Fork(name, n, type):
    outports = [Port("out%d" % (i+1), [type]) for i in range(n)]
    calls = ["out%d(x);" % (i+1) for i in range(n)]
    src = "(%s x) = in(); output { %s }" % (type, " ".join(calls))
    return Element(name, [Port("in", ["int"])], outports, src)


def Inject(name, type):
    src = "(%s x) = in(); output { out(x); }" % type
    return Element(name, [Port("in", [type])], [Port("out", [type])], src)


def ProbeState(name, type, size):
    return State(name, "%s data[%d]; int p;" % (type, size), "0,0")


def Probe(name, type, state, size):
    # TODO: need mutex lock (c) or atomic compare and swap (cpp)
    append = r'''
    if(this.p >= %d) { printf("Failed.\n"); exit(-1); }
    this.data[this.p] = x;
    this.p++;''' % size
    src = "(%s x) = in(); %s output { out(x); }" % (type, append)
    return Element(name, [Port("in", [type])], [Port("out", [type])],
                   src, None, [(state, "this")])

# Fork2 = Element("Fork2",
#                 [Port("in", ["int"])],
#                 [Port("out1", ["int"]), Port("out2", ["int"])],
#                 r'''(int x) = in(); output { out1(x); out2(x); }''')
# Fork3 = Element("Fork3",
#                 [Port("in", ["int"])],
#                 [Port("out1", ["int"]), Port("out2", ["int"]), Port("out3", ["int"])],
#                 r'''(int x) = in(); output { out1(x); out2(x); out3(x); }''')
Fork2 = Fork("Fork2", 2, "int")
Fork3 = Fork("Fork3", 3, "int")
Forward = Inject("Forward", "int")
Add = Element("Add",
              [Port("in1", ["int"]), Port("in2", ["int"])],
              [Port("out", ["int"])],
              r'''int x = in1() + in2(); output { out(x); }''')

Inc = Element("Inc",
              [Port("in", ["int"])],
              [Port("out", ["int"])],
              r'''int x = in() + 1; output { out(x); }''')

