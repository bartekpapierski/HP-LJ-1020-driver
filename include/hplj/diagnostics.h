// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef HPLJ_DIAGNOSTICS_H
#define HPLJ_DIAGNOSTICS_H

#include "hplj/job.h"
#include <pthread.h>
#include <stdio.h>
#include <time.h>

/* Only numeric enums/counters and compiled-in strings cross this boundary. */
struct hplj_diagnostics {
  pthread_mutex_t mutex;
  FILE *log;
  time_t created;
  size_t bytes;
};
bool hplj_diagnostics_open(struct hplj_diagnostics *diagnostics, const char *path);
void hplj_diagnostics_close(struct hplj_diagnostics *diagnostics);
bool hplj_diagnostics_event(struct hplj_diagnostics *diagnostics, time_t now,
                             const struct hplj_job_metadata *job);
bool hplj_diagnostics_snapshot(const char *state_path, time_t now,
                                enum hplj_device_state device,
                                enum hplj_error_category error,
                                bool firmware_available);
#endif
