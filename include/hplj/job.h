// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef HPLJ_JOB_H
#define HPLJ_JOB_H

#include "hplj/device.h"
#include "hplj/encoder.h"

#include <stdbool.h>
#include <stddef.h>

#define HPLJ_MAX_ENCODED_JOB_BYTES (64U * 1024U * 1024U)

enum hplj_job_state {
  HPLJ_JOB_ACCEPTED,
  HPLJ_JOB_HELD_FOR_FIRMWARE,
  HPLJ_JOB_HELD_FOR_DEVICE,
  HPLJ_JOB_PREPARING,
  HPLJ_JOB_TRANSMITTING,
  HPLJ_JOB_WAITING_FOR_MEDIA,
  HPLJ_JOB_COMPLETED,
  HPLJ_JOB_CANCELED,
  HPLJ_JOB_FAILED,
  HPLJ_JOB_FAILED_PARTIAL,
};

struct hplj_job_metadata {
  unsigned long job_id;
  enum hplj_job_state state;
  unsigned int pages_completed;
  size_t bytes_sent;
  struct hplj_error error;
};

typedef bool (*hplj_job_cancelled_callback)(void *context,
                                            unsigned long job_id);
typedef void (*hplj_job_state_callback)(void *context,
                                        const struct hplj_job_metadata *metadata);

struct hplj_job {
  struct hplj_job_metadata metadata;
  struct hplj_device *device;
  const struct hplj_foo2zjs_adapter *encoder;
  hplj_job_cancelled_callback is_cancelled;
  hplj_job_state_callback publish_state;
  void *callback_context;
  size_t maximum_encoded_bytes;
};

void hplj_job_init(struct hplj_job *job, unsigned long job_id,
                   struct hplj_device *device,
                   const struct hplj_foo2zjs_adapter *encoder,
                   hplj_job_cancelled_callback is_cancelled,
                   hplj_job_state_callback publish_state,
                   void *callback_context);
struct hplj_error hplj_job_prepare(struct hplj_job *job,
                                   const unsigned char *firmware,
                                   size_t firmware_size,
                                   const char *expected_firmware_version);
struct hplj_error hplj_job_submit_page(struct hplj_job *job,
                                       const struct hplj_raster *raster);
struct hplj_error hplj_job_complete(struct hplj_job *job);
struct hplj_error hplj_job_retry(struct hplj_job *job);
struct hplj_error hplj_job_wait_for_media(struct hplj_job *job,
                                          unsigned int conditions);
struct hplj_error hplj_job_resume_media(struct hplj_job *job);
void hplj_job_cancel(struct hplj_job *job);
void hplj_job_shutdown(struct hplj_job *job);

#endif
