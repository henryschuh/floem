from program import *
import re, sys
from contextlib import contextmanager

@contextmanager
def redirect_stdout(new_target):
    old_target, sys.stdout = sys.stdout, new_target # replace sys.stdout
    try:
        yield new_target # run some code with the replaced stdout
    finally:
        sys.stdout = old_target # restore to the previous value


def thread_func_create_cancel(func, device, size=None, interval=None):
    # TODO: potentially need to pass in core_id
    if size:
        body = r'''
    usleep(1000);
    for(int i=0; i<%d; i++) {
        //printf("inject = %s\n", i);
        %s();
        usleep(%d);
    }
    pthread_exit(NULL);
        ''' % (size, '%d', func, interval)
    else:
        body = r'''
    while(true) {
        %s();
        /* usleep(1000); */
    }
    ''' % func

    if device[0] == target.CPU:
        thread = "pthread_t _thread_%s;\n" % func
        func_src = "void *_run_%s(void *threadid) {\n" % func + body + "}\n"
        create = "  pthread_create(&_thread_%s, NULL, _run_%s, NULL);\n" % (func, func)
        cancel = "  pthread_cancel(_thread_%s);\n" % func
    elif device[0] == target.CAVIUM:
        thread = ""
        func_src = "void _run_%s() {\n" % func + body + "}\n"

        cond = " || ".join(["(corenum == %d)" % i for i in device[1]])
        create = r'''
    {
        int corenum = cvmx_get_core_num();
        if(%s)  _run_%s();
    }
        ''' % (cond, func)
        cancel = ""

    return (thread, func_src, create, cancel)


def inject_thread_code(injects, graph):
    global_src = ""
    run_src = ""
    kill_src = ""

    for (func, size, interval) in injects:
        instance = graph.instances[func]
        (thread, func_src, create, cancel) = thread_func_create_cancel(func, instance.device, size, interval)
        global_src += thread
        global_src += func_src
        run_src += create
        kill_src += cancel

    return global_src, run_src, kill_src


def internal_thread_code(forever, graph):
    global_src = ""
    run_src = ""
    kill_src = ""

    for func in forever:
        instance = graph.instances[func]
        if len(instance.element.inports) > 0:
            raise Exception(
                "The element '%s' cannot be a starting element because it receives an input from another element." % func)

        (thread, func_src, create, cancel) = thread_func_create_cancel(func, instance.device)
        global_src += thread
        global_src += func_src
        run_src += create
        kill_src += cancel

    return global_src, run_src, kill_src


# for state_instance in injects:
#     if process in graph.state_instances[state_instance].processes:
#         inject = injects[state_instance]

def generate_internal_triggers_with_process(graph, process, ext, mode):
    threads_internal = set([trigger.call_instance for trigger in graph.threads_internal])
    threads_api = set([trigger.call_instance for trigger in graph.threads_API])
    injects = graph.inject_populates

    spec_injects = []
    impl_injects = []
    all_injects = []
    for state_instance in injects:
        # if process in graph.state_instances[state_instance].processes:
        inject = injects[state_instance]
        spec_injects += [(x, inject.size, inject.interval)
                         for x in inject.spec_ele_instances if process == graph.instances[x].process]
        impl_injects += [(x, inject.size, inject.interval)
                         for x in inject.impl_ele_instances if process == graph.instances[x].process]
        all_injects += [x for x in inject.spec_ele_instances if process == graph.instances[x].process]
        all_injects += [x for x in inject.impl_ele_instances if process == graph.instances[x].process]

    # spec_impl = is_spec_impl(threads_internal.union(all_injects))

    forever = threads_internal.difference(all_injects)
    no_triggers = graph.threads_roots.difference(forever).difference(all_injects).difference(threads_api)

    forever = [t for t in forever if graph.instances[t].process == process]
    no_triggers = [t for t in no_triggers if graph.instances[t].process == process]
    if len(no_triggers) > 0:
        for inst in no_triggers:
            t = graph.instances[inst].thread
            if t:
                raise Exception(
                    "Element instance '%s' is assigned to thread '%s', but it is not reachable from the starting element of thread '%s'.\n"
                    % (inst, t, t)
                    + "To make it reachable, use %s.run_order to specify an order from an element reachable by the starting element of thread '%s' to '%s'."
                    % (t, t, inst)
                )

    header_src = ""
    if not mode == "compare":
        g1, r1, k1 = inject_thread_code(spec_injects + impl_injects, graph)
        g2, r2, k2 = internal_thread_code(forever, graph)
        global_src = g1 + g2
        run_src = "void run_threads() {\n" + r1 + r2 + "}\n"
        kill_src = "void kill_threads() {\n" + k1 + k2 + "}\n"
        header_src += "void run_threads();\n"
        header_src += "void kill_threads();\n"

    else:
        run_src = "void run_threads() { }\n"
        kill_src = "void kill_threads() { }\n"

        g1, r1, k1 = inject_thread_code(spec_injects, graph)
        g2, r2, k2 = internal_thread_code([x for x in forever if re.match('_spec', x)], graph)
        global_src = g1 + g2
        run_src += "void spec_run_threads() {\n" + r1 + r2 + "}\n"
        kill_src += "void spec_kill_threads() {\n" + k1 + k2 + "}\n"

        g1, r1, k1 = inject_thread_code(impl_injects,graph)
        g2, r2, k2 = internal_thread_code([x for x in forever if not re.match('_spec', x)], graph)
        global_src += g1 + g2
        run_src += "void impl_run_threads() {\n" + r1 + r2 + "}\n"
        kill_src += "void impl_kill_threads() {\n" + k1 + k2 + "}\n"

        header_src += "void run_threads();\n"
        header_src += "void kill_threads();\n"
        header_src += "void spec_run_threads();\n"
        header_src += "void spec_kill_threads();\n"
        header_src += "void impl_run_threads();\n"
        header_src += "void impl_kill_threads();\n"

    if ext == '.h':
        with open(process + '.h', 'a') as f, redirect_stdout(f):
            print header_src

    with open(process + '.c', 'a') as f, redirect_stdout(f):
        print global_src + run_src + kill_src


def generate_internal_triggers(graph, ext, mode):
    for process in graph.processes:
        generate_internal_triggers_with_process(graph, process, ext, mode)


def generate_inject_probe_code_with_process(graph, process, ext):
    injects = graph.inject_populates
    probes = graph.probe_compares
    src = ""
    if len(injects) or len(probes):
        inject_src = ""
        for state_instance in injects:
            inject = injects[state_instance]
            for key in inject.spec_instances:
                spec_instance = inject.spec_instances[key]
                if process in graph.state_instances[spec_instance].processes:
                    inject_src += generate_populate_state(inject, key)

        probe_src = ""
        for state_instance in probes:
            probe = probes[state_instance]
            for key in probe.spec_instances:
                spec_instance = probe.spec_instances[key]
                if process in graph.state_instances[spec_instance].processes:
                    probe_src += generate_compare_state(probe, key)

    else:
        inject_src = ""
        probe_src = ""

    src += "void init(char *argv[]) {\n" if graph.process2device[process] == target.CPU else "void init() {\n"
    src += "  init_memory_regions();\n"
    src += "  init_state_instances(argv);\n" if graph.process2device[process] == target.CPU else "  init_state_instances();\n"
    src += inject_src
    src += "}\n\n"

    src += "void finalize_and_check() {\n"
    src += probe_src
    src += "  finalize_memory_regions();\n"
    src += "  finalize_state_instances();\n"
    src += "}\n\n"

    if ext == '.h':
        with open(process + '.h', 'a') as f, redirect_stdout(f):
            print "void init(char *argv[]);" if graph.process2device[process] == target.CPU else "void init();\n"
            print "void finalize_and_check();"

    with open(process + '.c', 'a') as f, redirect_stdout(f):
        print src


def generate_inject_probe_code(graph, ext):
    for process in graph.processes:
        generate_inject_probe_code_with_process(graph, process, ext)


def generate_testing_code(graph, code, ext):
    if target.CPU in graph.devices:
        src = "int main(int argc, char *argv[]) {\n"
        src += "  init(argv);\n"
        src += "  run_threads();\n"
        if code:
            src += "  " + code
        src += "  kill_threads();\n"
        src += "  finalize_and_check();\n"
        src += "\n  return 0;\n"
        src += "}\n"

        for process in graph.processes:
            if graph.process2device[process] == target.CPU:
                name = process + ext
                with open(name, 'a') as f, redirect_stdout(f):
                    print src


def generate_populate_state(inject, key):
    # src = "  // %s: populate %s and %s\n" % \
    #       (inject.name, inject.spec_instances[key], inject.impl_instances[key])
    src = "  for(int i = 0; i < %d; i++) {\n" % inject.size
    src += "    %s temp = %s(i);\n" % (inject.type, inject.func)
    src += "    %s->data[i] = temp;\n" % inject.spec_instances[key]
    if key in inject.impl_instances:
        src += "    %s->data[i] = temp;\n" % inject.impl_instances[key]
    src += "  }\n"
    return src


def generate_compare_state(probe, key):
    if key not in probe.impl_instances:
        return ""
    spec = probe.spec_instances[key]
    impl = probe.impl_instances[key]
    # src = "  // %s: compare %s and %s\n" % \
    #       (probe.name, probe.spec_instances[key], probe.impl_instances[key])
    src = "  {0}({1}->p, {1}->data, {2}->p, {2}->data);\n".format(probe.func, spec, impl)
    return src
