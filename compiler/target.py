# device = CPU
HOST = 'CPU'
CPU = 'CPU'
cpu_include_h = ["<stdint.h>", "<stdbool.h>", "<stdio.h>", "<stdlib.h>", '<queue.h>']
cpu_include_c = ["<stdint.h>", "<stdbool.h>", "<stdio.h>", "<stdlib.h>", "<string.h>", 
                 "<stddef.h>", "<unistd.h>", "<pthread.h>", '<queue.h>', '<shm.h>', '<util.h>', '<arpa/inet.h>']

# device = CAVIUM, process = CAVIUM
CAVIUM = 'CAVIUM'
cavium_include_h = ['"cvmcs-nic.h"', '"floem-queue.h"']
cavium_include_c = ['<cvmx-atomic.h>', '"cvmcs-nic.h"',
                    '"floem-util.h"', '"floem-dma.h"', '"floem-queue.h"', '"floem-queue-manage.h"']


# device = CPU, process = DPDK
def is_dpdk_proc(process):
    return process == 'dpdk'

dpdk = "dpdk"
dpdk_dir = "/opt/dpdk"
dpdk_include = dpdk_dir + "/include/dpdk"
dpdk_lib = dpdk_dir + "/lib/"
dpdk_pmds = "-lrte_pmd_ixgbe -lrte_pmd_i40e"
dpdk_libs = "-Wl,--whole-archive " + dpdk_pmds + " -lrte_eal" + \
    " -lrte_mempool -lrte_mempool_ring -lrte_hash -lrte_ring -lrte_kvargs" + \
    " -lrte_ethdev -lrte_mbuf -lrte_pmd_ring -Wl,--no-whole-archive -lm" + \
    " -lpthread -ldl"
dpdk_driver_header = ['<dpdkif.h>']


def runtime_hook(graph, process):
    src = ""
    if process == CAVIUM and graph.shared_states:
        src = r'''
#ifdef RUNTIME
    {
        int corenum = cvmx_get_core_num();
        if(corenum >= RUNTIME_START_CORE)  smart_dma_manage(corenum - RUNTIME_START_CORE);
    }
#endif
        '''
    return src
