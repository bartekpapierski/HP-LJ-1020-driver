// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/pjl_status.h"
#include "hplj/device.h"

#include <string.h>

static void hplj_pjl_parse_frame(struct hplj_pjl_status *status) {
  char *line = status->frame;
  char *end = strchr(line, '\n');
  if (end == NULL) {
    return;
  }
  *end = '\0';
  size_t length = strlen(line);
  if (length > 0 && line[length - 1] == '\r') {
    line[length - 1] = '\0';
  }
  if (strcmp(line, "@PJL USTATUS JOB") == 0) {
    // The encoder sends one page per PJL JOB/EOJ document. Only the observed
    // successful end report establishes completion of that document.
    if (strcmp(end + 1, "END\r\nRESULT=OK\r\nPAGES=1\r\n") == 0 ||
        strcmp(end + 1, "END\nRESULT=OK\nPAGES=1\n") == 0) {
      status->completed_documents++;
    }
    return;
  }
  if (strcmp(line, "@PJL USTATUS DEVICE") != 0 &&
      strcmp(line, "@PJL USTATUS TIMED") != 0 &&
      strcmp(line, "@PJL INFO STATUS") != 0) {
    return;
  }
  unsigned int code = 0;
  bool have_code = false;
  bool have_online = false;
  bool online = false;
  line = end + 1;
  while (*line != '\0') {
    end = strchr(line, '\n');
    if (end == NULL) {
      return;
    }
    *end = '\0';
    length = strlen(line);
    if (length > 0 && line[length - 1] == '\r') {
      line[--length] = '\0';
    }
    if (strncmp(line, "CODE=", 5) == 0) {
      if (have_code || length != 10) {
        return;
      }
      for (size_t index = 5; index < 10; index++) {
        if (line[index] < '0' || line[index] > '9') {
          return;
        }
        code = code * 10U + (unsigned int)(line[index] - '0');
      }
      have_code = true;
    } else if (strncmp(line, "ONLINE=", 7) == 0) {
      if (have_online ||
          (strcmp(line + 7, "TRUE") != 0 && strcmp(line + 7, "FALSE") != 0)) {
        return;
      }
      online = strcmp(line + 7, "TRUE") == 0;
      have_online = true;
    }
    line = end + 1;
  }
  if (!have_code || !have_online) {
    return;
  }
  status->code = code;
  status->online = online;
  if (code == 40021U) {
    status->conditions = HPLJ_DEVICE_CONDITION_COVER_OPEN;
  } else if (code >= 41000U && code < 42000U) {
    // PJL 41xyy requests foreground paper loading; x=1 is manual feed.
    status->conditions = (code / 100U) % 10U == 1U
                             ? HPLJ_DEVICE_CONDITION_MANUAL_FEED
                             : HPLJ_DEVICE_CONDITION_MEDIA_EMPTY;
  } else if (code >= 30000U) {
    status->conditions = HPLJ_DEVICE_CONDITION_FAULT;
  } else if ((status->conditions &
              (HPLJ_DEVICE_CONDITION_MEDIA_EMPTY |
               HPLJ_DEVICE_CONDITION_MANUAL_FEED)) != 0 &&
             !(code == 10001U && online)) {
    // The reference printer retries paper pickup, alternating a load request
    // with processing and warm-up. Those messages do not prove paper recovery.
    return;
  } else {
    status->conditions = online ? HPLJ_DEVICE_CONDITION_NONE
                                : HPLJ_DEVICE_CONDITION_NOT_SELECTED;
  }
}

void hplj_pjl_status_feed(struct hplj_pjl_status *status,
                          const unsigned char *bytes, size_t count) {
  for (size_t index = 0; index < count; index++) {
    if (bytes[index] == '\f') {
      if (!status->discarding) {
        status->frame[status->length] = '\0';
        hplj_pjl_parse_frame(status);
      }
      status->length = 0;
      status->discarding = false;
    } else if (!status->discarding) {
      if (bytes[index] == '\0' || status->length + 1 >= sizeof(status->frame)) {
        status->discarding = true;
      } else {
        status->frame[status->length++] = (char)bytes[index];
      }
    }
  }
}
