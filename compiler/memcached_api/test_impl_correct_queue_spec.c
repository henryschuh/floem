#include "tmp_impl_correct_queue_spec.h"
#include "iokvs.h"

int main() {
  hasht_init();
  init();
  run_threads();
  usleep(500000);
  kill_threads();
  return 0;
}