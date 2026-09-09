// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/job.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

struct hplj_encoded_page {
  unsigned char *bytes;
  size_t size;
  size_t capacity;
  size_t maximum_size;
};

static struct hplj_error hplj_job_error(enum hplj_error_category category,
                                        enum hplj_retry_safety retry,
                                        enum hplj_human_action action,
                                        const char *detail) {
  return hplj_error_make(category, retry, action, detail);
}

static void hplj_job_publish(struct hplj_job *job) {
  if (job->publish_state != NULL) {
    job->publish_state(job->callback_context, &job->metadata);
  }
}

static void hplj_job_set_state(struct hplj_job *job,
                               enum hplj_job_state state,
                               struct hplj_error error) {
  job->metadata.state = state;
  job->metadata.error = error;
  hplj_job_publish(job);
}

static bool hplj_job_is_cancelled(const struct hplj_job *job) {
  return job->is_cancelled != NULL &&
         job->is_cancelled(job->callback_context, job->metadata.job_id);
}

static enum hplj_error_category hplj_collect_encoded_bytes(
    void *context, const unsigned char *bytes, size_t byte_count) {
  struct hplj_encoded_page *page = context;
  if (bytes == NULL || byte_count == 0) {
    return HPLJ_ERROR_ENCODING_FAILED;
  }
  if (byte_count > page->maximum_size - page->size) {
    return HPLJ_ERROR_ENCODING_FAILED;
  }
  size_t required = page->size + byte_count;
  if (required > page->capacity) {
    size_t capacity = page->capacity == 0 ? 4096 : page->capacity;
    while (capacity < required) {
      if (capacity > page->maximum_size / 2) {
        capacity = page->maximum_size;
        break;
      }
      capacity *= 2;
    }
    unsigned char *grown = realloc(page->bytes, capacity);
    if (grown == NULL) {
      return HPLJ_ERROR_ENCODING_FAILED;
    }
    page->bytes = grown;
    page->capacity = capacity;
  }
  memcpy(page->bytes + page->size, bytes, byte_count);
  page->size = required;
  return HPLJ_ERROR_NONE;
}

static void hplj_job_fail(struct hplj_job *job, struct hplj_error error,
                          size_t bytes_sent) {
  job->metadata.bytes_sent += bytes_sent;
  if (job->metadata.bytes_sent > 0) {
    error.retry = HPLJ_RETRY_EXPLICIT;
    error.action = HPLJ_ACTION_RETRY_JOB;
  }
  enum hplj_job_state state = error.category == HPLJ_ERROR_CANCELLED
                                  ? HPLJ_JOB_CANCELED
                                  : HPLJ_JOB_FAILED;
  hplj_job_set_state(job, state, error);
}

void hplj_job_init(struct hplj_job *job, unsigned long job_id,
                   struct hplj_device *device,
                   const struct hplj_foo2zjs_adapter *encoder,
                   hplj_job_cancelled_callback is_cancelled,
                   hplj_job_state_callback publish_state,
                   void *callback_context) {
  memset(job, 0, sizeof(*job));
  job->metadata.job_id = job_id;
  job->metadata.error = hplj_job_error(
      HPLJ_ERROR_NONE, HPLJ_RETRY_SAFE_AUTOMATIC, HPLJ_ACTION_NONE, "accepted");
  job->device = device;
  job->encoder = encoder;
  job->is_cancelled = is_cancelled;
  job->publish_state = publish_state;
  job->callback_context = callback_context;
  job->maximum_encoded_bytes = HPLJ_MAX_ENCODED_JOB_BYTES;
  hplj_job_set_state(job, HPLJ_JOB_ACCEPTED, job->metadata.error);
}

struct hplj_error hplj_job_prepare(struct hplj_job *job,
                                   const unsigned char *firmware,
                                   size_t firmware_size,
                                   const char *expected_firmware_version) {
  if (job == NULL || job->device == NULL || job->encoder == NULL ||
      (job->metadata.state != HPLJ_JOB_ACCEPTED &&
       job->metadata.state != HPLJ_JOB_HELD_FOR_FIRMWARE)) {
    return hplj_job_error(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER,
                          HPLJ_ACTION_NONE, "job cannot be prepared");
  }
  if (hplj_job_is_cancelled(job)) {
    struct hplj_error error = hplj_job_error(
        HPLJ_ERROR_CANCELLED, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
        "job was cancelled before preparation");
    hplj_job_fail(job, error, 0);
    return error;
  }

  struct hplj_device_result result = {0};
  if (job->device->state == HPLJ_DEVICE_DISCONNECTED) {
    result = hplj_device_connect(job->device);
    if (result.error.category != HPLJ_ERROR_NONE) {
      hplj_job_fail(job, result.error, result.bytes_transferred);
      return job->metadata.error;
    }
  }
  result = hplj_device_bootstrap_firmware(
      job->device, firmware, firmware_size, expected_firmware_version);
  if (result.error.category != HPLJ_ERROR_NONE) {
    if (result.error.category == HPLJ_ERROR_FIRMWARE_MISSING) {
      hplj_job_set_state(job, HPLJ_JOB_HELD_FOR_FIRMWARE, result.error);
    } else {
      hplj_job_fail(job, result.error, result.bytes_transferred);
    }
    return job->metadata.error;
  }
  hplj_job_set_state(
      job, HPLJ_JOB_PREPARING,
      hplj_job_error(HPLJ_ERROR_NONE, HPLJ_RETRY_SAFE_AUTOMATIC,
                     HPLJ_ACTION_NONE, "preparing"));
  return job->metadata.error;
}

struct hplj_error hplj_job_submit_page(struct hplj_job *job,
                                       const struct hplj_raster *raster) {
  if (job == NULL || job->metadata.state != HPLJ_JOB_PREPARING) {
    return hplj_job_error(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER,
                          HPLJ_ACTION_NONE, "job is not ready for a page");
  }
  if (hplj_job_is_cancelled(job)) {
    struct hplj_error error = hplj_job_error(
        HPLJ_ERROR_CANCELLED, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
        "job was cancelled before encoding");
    hplj_job_fail(job, error, 0);
    return job->metadata.error;
  }

  struct hplj_encoded_page page = {
      .maximum_size = job->maximum_encoded_bytes};
  struct hplj_encoder_sink sink = {
      .emit = hplj_collect_encoded_bytes, .context = &page};
  struct hplj_encode_result encoded = hplj_encode_raster(
      job->encoder, raster, &sink, hplj_job_is_cancelled(job));
  if (encoded.error.category != HPLJ_ERROR_NONE) {
    free(page.bytes);
    if (encoded.error.retry == HPLJ_RETRY_EXPLICIT &&
        encoded.error.category != HPLJ_ERROR_CANCELLED) {
      encoded.error.retry = HPLJ_RETRY_SAFE_AUTOMATIC;
    }
    hplj_job_fail(job, encoded.error, 0);
    return job->metadata.error;
  }
  if (page.size == 0 || encoded.bytes_emitted != page.size) {
    free(page.bytes);
    struct hplj_error error = hplj_job_error(
        HPLJ_ERROR_ENCODING_FAILED, HPLJ_RETRY_SAFE_AUTOMATIC,
        HPLJ_ACTION_RETRY_JOB, "encoder byte count is inconsistent");
    hplj_job_fail(job, error, 0);
    return job->metadata.error;
  }

  hplj_job_set_state(
      job, HPLJ_JOB_TRANSMITTING,
      hplj_job_error(HPLJ_ERROR_NONE, HPLJ_RETRY_SAFE_AUTOMATIC,
                     HPLJ_ACTION_NONE, "transmitting"));
  struct hplj_device_result sent = hplj_device_send(
      job->device, page.bytes, page.size, hplj_job_is_cancelled(job));
  free(page.bytes);
  if (sent.error.category != HPLJ_ERROR_NONE) {
    hplj_job_fail(job, sent.error, sent.bytes_transferred);
    return job->metadata.error;
  }
  job->metadata.bytes_sent += sent.bytes_transferred;
  job->metadata.pages_completed++;
  hplj_job_set_state(
      job, HPLJ_JOB_PREPARING,
      hplj_job_error(HPLJ_ERROR_NONE, HPLJ_RETRY_SAFE_AUTOMATIC,
                     HPLJ_ACTION_NONE, "page transmitted"));
  return job->metadata.error;
}

struct hplj_error hplj_job_complete(struct hplj_job *job) {
  if (job == NULL || job->metadata.state != HPLJ_JOB_PREPARING ||
      job->metadata.pages_completed == 0) {
    return hplj_job_error(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER,
                          HPLJ_ACTION_NONE,
                          "job cannot complete before page transmission");
  }
  hplj_job_set_state(
      job, HPLJ_JOB_COMPLETED,
      hplj_job_error(HPLJ_ERROR_NONE, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
                     "completed"));
  return job->metadata.error;
}

struct hplj_error hplj_job_retry(struct hplj_job *job) {
  if (job == NULL || job->metadata.state != HPLJ_JOB_FAILED ||
      job->metadata.error.retry != HPLJ_RETRY_EXPLICIT) {
    return hplj_job_error(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER,
                          HPLJ_ACTION_NONE, "job is not eligible for explicit retry");
  }
  job->metadata.bytes_sent = 0;
  job->metadata.pages_completed = 0;
  hplj_job_set_state(
      job, HPLJ_JOB_ACCEPTED,
      hplj_job_error(HPLJ_ERROR_NONE, HPLJ_RETRY_SAFE_AUTOMATIC,
                     HPLJ_ACTION_NONE, "explicit retry accepted"));
  return job->metadata.error;
}

void hplj_job_cancel(struct hplj_job *job) {
  if (job == NULL || job->metadata.state == HPLJ_JOB_COMPLETED ||
      job->metadata.state == HPLJ_JOB_CANCELED) {
    return;
  }
  struct hplj_error error = hplj_job_error(
      HPLJ_ERROR_CANCELLED,
      job->metadata.bytes_sent > 0 ? HPLJ_RETRY_EXPLICIT : HPLJ_RETRY_NEVER,
      job->metadata.bytes_sent > 0 ? HPLJ_ACTION_RETRY_JOB : HPLJ_ACTION_NONE,
      "job canceled");
  hplj_job_set_state(job, HPLJ_JOB_CANCELED, error);
}

void hplj_job_shutdown(struct hplj_job *job) {
  if (job == NULL) {
    return;
  }
  if (job->metadata.state != HPLJ_JOB_COMPLETED &&
      job->metadata.state != HPLJ_JOB_CANCELED &&
      job->metadata.state != HPLJ_JOB_FAILED) {
    hplj_job_cancel(job);
  }
  if (job->device != NULL) {
    hplj_device_disconnect(job->device);
  }
}
