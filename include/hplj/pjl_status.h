// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef HPLJ_PJL_STATUS_H
#define HPLJ_PJL_STATUS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

struct hplj_pjl_status {
  char frame[1024];
  size_t length;
  unsigned int conditions;
  unsigned int code;
  bool online;
  uint64_t completed_documents;
  bool discarding;
};

void hplj_pjl_status_feed(struct hplj_pjl_status *status,
                          const unsigned char *bytes, size_t count);

#endif
