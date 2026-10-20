// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/device.h"
#include "hplj/pjl_status.h"

#include <assert.h>
#include <string.h>

static void feed(struct hplj_pjl_status *status, const char *text) {
  hplj_pjl_status_feed(status, (const unsigned char *)text, strlen(text));
}

int main(void) {
  const char open[] = "@PJL USTATUS DEVICE\r\nCODE=40021\r\n"
                      "DISPLAY=\"\"\r\nONLINE=FALSE\r\n\f";
  const char ready[] = "@PJL USTATUS DEVICE\r\nCODE=10001\r\n"
                       "DISPLAY=\"\"\r\nONLINE=TRUE\r\n\f";
  struct hplj_pjl_status status = {0};
  for (size_t i = 0; i < sizeof(open) - 1; i++) {
    hplj_pjl_status_feed(&status, (const unsigned char *)open + i, 1);
    if (i + 1 < sizeof(open) - 1) {
      assert(status.conditions == HPLJ_DEVICE_CONDITION_NONE);
    }
  }
  assert(status.conditions == HPLJ_DEVICE_CONDITION_COVER_OPEN);
  feed(&status, "@PJL USTATUS JOB\r\nEND\r\nRESULT=OK\r\nPAGES=1\r\n\f");
  assert(status.conditions == HPLJ_DEVICE_CONDITION_COVER_OPEN);
  assert(status.completed_documents == 1);
  feed(&status, "@PJL USTATUS JOB\r\nSTART\r\n\f"
                "@PJL USTATUS PAGE\r\n1\r\n\f"
                "@PJL USTATUS JOB\r\nEND\r\nRESULT=ERROR\r\nPAGES=1\r\n\f"
                "@PJL USTATUS JOB\r\nEND\r\nRESULT=OK\r\nPAGES=0\r\n\f");
  assert(status.completed_documents == 1);
  feed(&status, "@PJL USTATUS DEVICE\r\nCODE=10001bad\r\nONLINE=TRUE\r\n\f");
  assert(status.conditions == HPLJ_DEVICE_CONDITION_COVER_OPEN);
  feed(&status, ready);
  assert(status.conditions == HPLJ_DEVICE_CONDITION_NONE);
  feed(&status, "@PJL USTATUS DEVICE\r\nCODE=41004\r\n"
                "DISPLAY=\"\"\r\nONLINE=FALSE\r\n\f");
  assert(status.conditions == HPLJ_DEVICE_CONDITION_MEDIA_EMPTY);
  assert(status.code == 41004 && !status.online);
  feed(&status, "@PJL USTATUS TIMED\r\nCODE=10023\r\nONLINE=TRUE\r\n\f");
  assert(status.conditions == HPLJ_DEVICE_CONDITION_MEDIA_EMPTY);
  feed(&status, "@PJL USTATUS TIMED\r\nCODE=10003\r\nONLINE=FALSE\r\n\f");
  assert(status.conditions == HPLJ_DEVICE_CONDITION_MEDIA_EMPTY);
  feed(&status, "@PJL USTATUS DEVICE\r\nCODE=41104\r\nONLINE=FALSE\r\n\f");
  assert(status.conditions == HPLJ_DEVICE_CONDITION_MANUAL_FEED);
  feed(&status, ready);
  assert(status.conditions == HPLJ_DEVICE_CONDITION_NONE);
  feed(&status, "@PJL INFO STATUS\r\nCODE=40022\r\nONLINE=FALSE\r\n\f");
  assert(status.conditions == HPLJ_DEVICE_CONDITION_FAULT);
  feed(&status, "@PJL USTATUS TIMED\r\nCODE=10003\r\nONLINE=FALSE\r\n\f");
  assert(status.conditions == HPLJ_DEVICE_CONDITION_NOT_SELECTED);
  char oversized[1100];
  memset(oversized, 'x', sizeof(oversized));
  hplj_pjl_status_feed(&status, (const unsigned char *)oversized, sizeof(oversized));
  feed(&status, ready);
  assert(status.conditions == HPLJ_DEVICE_CONDITION_NOT_SELECTED);
  feed(&status, ready);
  assert(status.conditions == HPLJ_DEVICE_CONDITION_NONE);
  feed(&status, "@PJL USTATUS DEVICE\r\nCODE=40021\r\nONLINE=FALSE\r\n\f"
                "@PJL USTATUS TIMED\r\nCODE=10001\r\nONLINE=TRUE\r\n\f");
  assert(status.conditions == HPLJ_DEVICE_CONDITION_NONE);
  return 0;
}
