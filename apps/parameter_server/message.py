from floem import *

class param_message(State):
    group_id = Field(Int)
    member_id = Field(Int)  # worker
    start_id = Field(Uint(64))
    starttime = Field('struct timeval')  # 16 bytes
    n = Field(Int)
    parameters = Field(Array(Int))
    layout = [group_id, member_id, start_id, starttime, n, parameters]

n_params = 3500000
n_groups = 128
n_workers = 8
buffer_size = 350

define = r'''
#define N_PARAMS %d
#define N_GROUPS %d
#define BUFFER_SIZE %d
#define BITMAP_FULL 0xff
''' % (n_params, n_groups, buffer_size)
