import codegen
import desugaring
import program
import workspace
import pipeline_state
import join_handling
import empty_port


class Compiler:
    def __init__(self, *pipelines):
        self.desugar_mode = "impl"
        self.resource = True
        self.remove_unused = True

        # Extra code
        self.include = None
        self.testing = None
        self.depend = None

        # Compiler option
        self.I = None
        self.pipelines = pipelines

    def has_spec_impl(self, scopes):
        for scope in scopes:
            for x in scope:
                if isinstance(x, program.Spec) or isinstance(x, program.Impl):
                    return True
        return False

    def generate_graph_from_scope(self, myscope, filename, pktstate=None, spec_impl=False, original=None):
        p = program.Program(*myscope)
        dp = desugaring.desugar(p, self.desugar_mode, force=spec_impl)

        g = program.program_to_graph_pass(dp, default_process=filename, original=original)
        empty_port.nonempty_to_empty_port_pass(g)
        pipeline_state.pipeline_state_pass(g, pktstate)
        return g

    def generate_graph(self, filename="tmp"):
        # Retrieve all scopes first
        scope = workspace.get_last_scope()
        decl = workspace.get_last_decl()
        org_scope = decl + scope

        pipelines = []
        for pipeline in self.pipelines:
            p = pipeline()
            pipelines.append(p)

        # Check if there is spec
        has_spec_impl = self.has_spec_impl([p.scope for p in pipelines] + [org_scope])

        # Generate graph
        original = self.generate_graph_from_scope(decl + scope, filename, spec_impl=has_spec_impl)
        all = []
        for i in range(len(self.pipelines)):
            p = pipelines[i]
            g = self.generate_graph_from_scope(decl + p.decl + p.scope, filename,
                                               pktstate=p.state, spec_impl=has_spec_impl, original=original)
            all.append(g)
            decl += p.decl

        for g in all:
            original.merge(g)

        join_handling.join_and_resource_annotation_pass(original, self.resource, self.remove_unused)

        return original

    def generate_code(self):
        codegen.generate_code_only(self.generate_graph(), self.testing, self.desugar_mode, self.include)

    def generate_code_and_run(self, expect=None):
        codegen.generate_code_and_run(self.generate_graph(), self.testing, self.desugar_mode, expect, self.include, self.depend)

    def generate_code_and_compile(self):
        codegen.generate_code_and_compile(self.generate_graph(), self.testing, self.desugar_mode, self.include, self.depend)

    def generate_code_as_header(self, header='tmp'):
        codegen.generate_code_as_header(self.generate_graph(header), self.testing, self.desugar_mode, self.include)

    def compile_and_run(self, name):
        codegen.compile_and_run(name, self.depend)