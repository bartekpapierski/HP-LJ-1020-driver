// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef HPLJ_CONFIG_H
#define HPLJ_CONFIG_H

#include "hplj/error.h"

#include <stdbool.h>
#include <stddef.h>

/*
 * All string members are borrowed for the service lifetime. The caller owns
 * their storage and may release it after the service has stopped.
 */
struct hplj_service_config {
  const char *queue_name;
  const char *loopback_host;
  unsigned short ipp_port;
  const char *firmware_path;
};

struct hplj_observer {
  void (*report)(void *context, const char *component, struct hplj_error error);
  void *context;
};

struct hplj_clock {
  unsigned long long (*monotonic_milliseconds)(void *context);
  void *context;
};

struct hplj_filesystem {
  enum hplj_error_category (*read_firmware)(void *context, const char *path,
                                             unsigned char **contents, size_t *size);
  void (*release_buffer)(void *context, unsigned char *contents);
  void *context;
};

struct hplj_process_supervisor {
  enum hplj_error_category (*service_state)(void *context, bool *running);
  void *context;
};

#endif
