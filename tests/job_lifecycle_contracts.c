// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/job.h"

#include <assert.h>
#include <stdlib.h>
#include <string.h>

struct fake_pipeline {
  const char *identity;
  bool firmware_uploaded;
  bool cancelled;
  enum hplj_error_category encode_error;
  enum hplj_error_category encode_after_prefix_error;
  struct hplj_transfer_result transfers[3];
  unsigned int transfer_count;
  unsigned int transfer_index;
  unsigned int releases;
  unsigned int state_count;
  enum hplj_job_state states[16];
  unsigned char output[1024];
  size_t output_size;
};

static enum hplj_error_category fake_discover(
    void *context, struct hplj_usb_descriptor *descriptor) {
  (void)context;
  descriptor->vendor_id = HPLJ_REFERENCE_VENDOR_ID;
  descriptor->product_id = HPLJ_REFERENCE_PRODUCT_ID;
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category fake_open(void *context) {
  (void)context;
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category fake_claim(void *context) {
  (void)context;
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category fake_identity(void *context, char *identity,
                                               size_t identity_size,
                                               size_t *identity_length) {
  struct fake_pipeline *fake = context;
  const char *value = fake->firmware_uploaded
                          ? "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;"
                          : fake->identity;
  *identity_length = strlen(value);
  assert(*identity_length + 1 <= identity_size);
  memcpy(identity, value, *identity_length + 1);
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category fake_upload(void *context,
                                             const unsigned char *firmware,
                                             size_t firmware_size) {
  struct fake_pipeline *fake = context;
  assert(firmware != NULL);
  assert(firmware_size > 0);
  fake->firmware_uploaded = true;
  return HPLJ_ERROR_NONE;
}

static struct hplj_transfer_result fake_write(void *context,
                                               const unsigned char *bytes,
                                               size_t byte_count) {
  struct fake_pipeline *fake = context;
  struct hplj_transfer_result result = {
      .category = HPLJ_ERROR_NONE, .bytes_transferred = byte_count};
  if (fake->transfer_index < fake->transfer_count) {
    result = fake->transfers[fake->transfer_index++];
  }
  size_t retained = result.bytes_transferred;
  if (retained > byte_count) {
    retained = byte_count;
  }
  assert(fake->output_size + retained <= sizeof(fake->output));
  memcpy(fake->output + fake->output_size, bytes, retained);
  fake->output_size += retained;
  return result;
}

static void fake_release(void *context) {
  struct fake_pipeline *fake = context;
  fake->releases++;
}

static enum hplj_error_category fake_encode(
    void *context, const struct hplj_raster *raster,
    const struct hplj_encoder_sink *sink, bool cancelled,
    size_t *bytes_emitted) {
  struct fake_pipeline *fake = context;
  if (cancelled) {
    return HPLJ_ERROR_CANCELLED;
  }
  if (fake->encode_error != HPLJ_ERROR_NONE) {
    return fake->encode_error;
  }
  const unsigned char prefix[] = {'J', 'Z', 'J', 'Z'};
  enum hplj_error_category category =
      sink->emit(sink->context, prefix, sizeof(prefix));
  if (category == HPLJ_ERROR_NONE &&
      fake->encode_after_prefix_error != HPLJ_ERROR_NONE) {
    *bytes_emitted = sizeof(prefix);
    return fake->encode_after_prefix_error;
  }
  if (category == HPLJ_ERROR_NONE) {
    category = sink->emit(sink->context, raster->bits, raster->bits_size);
  }
  *bytes_emitted = category == HPLJ_ERROR_NONE
                       ? sizeof(prefix) + raster->bits_size
                       : 0;
  return category;
}

static bool fake_cancelled(void *context, unsigned long job_id) {
  (void)job_id;
  return ((struct fake_pipeline *)context)->cancelled;
}

static void record_state(void *context,
                         const struct hplj_job_metadata *metadata) {
  struct fake_pipeline *fake = context;
  assert(fake->state_count < 16);
  fake->states[fake->state_count++] = metadata->state;
}

static struct hplj_raster valid_raster(void) {
  static const unsigned char bits[] = {0x80, 0x00};
  return (struct hplj_raster){
      .width_pixels = 8,
      .height_rows = 2,
      .resolution_dpi = 600,
      .painted_resolution_dpi = 600,
      .page_width_pixels = 8,
      .page_height_rows = 2,
      .printable_width_pixels = 8,
      .printable_height_rows = 2,
      .row_stride_bytes = 1,
      .bits = bits,
      .bits_size = sizeof(bits),
      .bit_polarity = HPLJ_BLACK_IS_ONE,
      .bit_order = HPLJ_MOST_SIGNIFICANT_BIT_FIRST,
      .page_count = 1,
      .media = HPLJ_MEDIA_A4,
      .source = HPLJ_SOURCE_AUTO,
      .quality = HPLJ_QUALITY_NORMAL,
      .density = 3,
  };
}

static struct hplj_job make_job(struct fake_pipeline *fake,
                                struct hplj_device *device) {
  struct hplj_device_ops device_ops = {
      .discover = fake_discover,
      .open = fake_open,
      .claim_interface = fake_claim,
      .read_identity = fake_identity,
      .upload_firmware = fake_upload,
      .write = fake_write,
      .release = fake_release,
      .context = fake,
  };
  hplj_device_init(device, &device_ops);
  static struct hplj_foo2zjs_adapter encoder;
  encoder = (struct hplj_foo2zjs_adapter){
      .encode_zjstream = fake_encode, .context = fake};
  struct hplj_job job;
  hplj_job_init(&job, 42, device, &encoder, fake_cancelled, record_state, fake);
  return job;
}

static void test_job_waits_for_firmware_then_completes_after_transmission(void) {
  struct fake_pipeline fake = {
      .identity = "MFG:HP;MDL:HP LaserJet 1020;"};
  struct hplj_device device;
  struct hplj_job job = make_job(&fake, &device);

  struct hplj_error error = hplj_job_prepare(&job, NULL, 0, "20050309");
  assert(error.category == HPLJ_ERROR_FIRMWARE_MISSING);
  assert(job.metadata.state == HPLJ_JOB_HELD_FOR_FIRMWARE);
  assert(job.metadata.bytes_sent == 0);

  const unsigned char firmware[] = {1, 2, 3};
  error = hplj_job_prepare(&job, firmware, sizeof(firmware), "20050309");
  assert(error.category == HPLJ_ERROR_NONE);
  assert(job.metadata.state == HPLJ_JOB_PREPARING);
  assert(fake.firmware_uploaded);

  struct hplj_raster raster = valid_raster();
  error = hplj_job_submit_page(&job, &raster);
  assert(error.category == HPLJ_ERROR_NONE);
  assert(job.metadata.state == HPLJ_JOB_PREPARING);
  assert(job.metadata.pages_completed == 1);
  assert(job.metadata.bytes_sent == 6);
  assert(fake.output_size == 6);
  assert(hplj_job_complete(&job).category == HPLJ_ERROR_NONE);
  assert(job.metadata.state == HPLJ_JOB_COMPLETED);

  const enum hplj_job_state expected[] = {
      HPLJ_JOB_ACCEPTED, HPLJ_JOB_HELD_FOR_FIRMWARE, HPLJ_JOB_PREPARING,
      HPLJ_JOB_TRANSMITTING, HPLJ_JOB_PREPARING, HPLJ_JOB_COMPLETED};
  assert(fake.state_count == sizeof(expected) / sizeof(expected[0]));
  assert(memcmp(fake.states, expected, sizeof(expected)) == 0);
}

static void test_partial_transmission_requires_explicit_retry(void) {
  struct fake_pipeline fake = {
      .identity = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;",
      .transfers = {{HPLJ_ERROR_DEVICE_TIMEOUT, 2}},
      .transfer_count = 1,
  };
  struct hplj_device device;
  struct hplj_job job = make_job(&fake, &device);
  assert(hplj_job_prepare(&job, NULL, 0, "20050309").category ==
         HPLJ_ERROR_NONE);

  struct hplj_raster raster = valid_raster();
  struct hplj_error error = hplj_job_submit_page(&job, &raster);
  assert(error.category == HPLJ_ERROR_DEVICE_TIMEOUT);
  assert(error.retry == HPLJ_RETRY_EXPLICIT);
  assert(job.metadata.state == HPLJ_JOB_FAILED);
  assert(job.metadata.bytes_sent == 2);
  assert(job.metadata.pages_completed == 0);
  assert(hplj_job_complete(&job).category == HPLJ_ERROR_INVALID_STATE);

  assert(hplj_job_retry(&job).category == HPLJ_ERROR_NONE);
  assert(job.metadata.state == HPLJ_JOB_ACCEPTED);
  assert(job.metadata.bytes_sent == 0);
  assert(job.metadata.pages_completed == 0);
  assert(hplj_job_prepare(&job, NULL, 0, "20050309").category ==
         HPLJ_ERROR_NONE);
  assert(hplj_job_complete(&job).category == HPLJ_ERROR_INVALID_STATE);
}

static void test_zero_byte_failure_retries_but_partial_cancel_never_does(void) {
  struct fake_pipeline fake = {
      .identity = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;",
      .transfers = {{HPLJ_ERROR_DEVICE_TIMEOUT, 0},
                    {HPLJ_ERROR_NONE, 6}},
      .transfer_count = 2,
  };
  struct hplj_device device;
  struct hplj_job job = make_job(&fake, &device);
  assert(hplj_job_prepare(&job, NULL, 0, "20050309").category ==
         HPLJ_ERROR_NONE);
  struct hplj_raster raster = valid_raster();
  assert(hplj_job_submit_page(&job, &raster).category == HPLJ_ERROR_NONE);
  assert(fake.transfer_index == 2);
  assert(job.metadata.bytes_sent == 6);

  fake = (struct fake_pipeline){
      .identity = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;",
      .transfers = {{HPLJ_ERROR_CANCELLED, 1}},
      .transfer_count = 1,
  };
  job = make_job(&fake, &device);
  assert(hplj_job_prepare(&job, NULL, 0, "20050309").category ==
         HPLJ_ERROR_NONE);
  struct hplj_error error = hplj_job_submit_page(&job, &raster);
  assert(error.category == HPLJ_ERROR_CANCELLED);
  assert(error.retry == HPLJ_RETRY_EXPLICIT);
  assert(job.metadata.state == HPLJ_JOB_CANCELED);
  assert(job.metadata.bytes_sent == 1);
  assert(fake.transfer_index == 1);
}

static void test_malformed_raster_is_rejected_before_encoding_or_output(void) {
  struct fake_pipeline fake = {
      .identity = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;"};
  struct hplj_device device;
  struct hplj_job job = make_job(&fake, &device);
  assert(hplj_job_prepare(&job, NULL, 0, "20050309").category ==
         HPLJ_ERROR_NONE);
  struct hplj_raster raster = valid_raster();
  raster.painted_resolution_dpi = 300;
  struct hplj_error error = hplj_job_submit_page(&job, &raster);
  assert(error.category == HPLJ_ERROR_RASTER_INVALID);
  assert(error.retry == HPLJ_RETRY_NEVER);
  assert(job.metadata.state == HPLJ_JOB_FAILED);
  assert(fake.output_size == 0);
}

static void test_failures_cancellation_limits_and_shutdown_release_resources(void) {
  struct fake_pipeline fake = {
      .identity = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;"};
  struct hplj_device device;
  struct hplj_job job = make_job(&fake, &device);
  assert(hplj_job_prepare(&job, NULL, 0, "20050309").category ==
         HPLJ_ERROR_NONE);
  struct hplj_raster raster = valid_raster();

  fake.cancelled = true;
  assert(hplj_job_submit_page(&job, &raster).category == HPLJ_ERROR_CANCELLED);
  assert(job.metadata.state == HPLJ_JOB_CANCELED);
  assert(fake.output_size == 0);

  fake.cancelled = false;
  job = make_job(&fake, &device);
  assert(hplj_job_prepare(&job, NULL, 0, "20050309").category ==
         HPLJ_ERROR_NONE);
  fake.encode_error = HPLJ_ERROR_ENCODING_FAILED;
  assert(hplj_job_submit_page(&job, &raster).category ==
         HPLJ_ERROR_ENCODING_FAILED);
  assert(job.metadata.state == HPLJ_JOB_FAILED);
  assert(job.metadata.bytes_sent == 0);

  fake.encode_error = HPLJ_ERROR_NONE;
  fake.encode_after_prefix_error = HPLJ_ERROR_ENCODING_FAILED;
  job = make_job(&fake, &device);
  assert(hplj_job_prepare(&job, NULL, 0, "20050309").category ==
         HPLJ_ERROR_NONE);
  struct hplj_error buffered_failure = hplj_job_submit_page(&job, &raster);
  assert(buffered_failure.category == HPLJ_ERROR_ENCODING_FAILED);
  assert(buffered_failure.retry == HPLJ_RETRY_SAFE_AUTOMATIC);
  assert(job.metadata.bytes_sent == 0);
  assert(fake.output_size == 0);

  fake.encode_after_prefix_error = HPLJ_ERROR_NONE;
  job = make_job(&fake, &device);
  job.maximum_encoded_bytes = 4;
  assert(hplj_job_prepare(&job, NULL, 0, "20050309").category ==
         HPLJ_ERROR_NONE);
  assert(hplj_job_submit_page(&job, &raster).category ==
         HPLJ_ERROR_ENCODING_FAILED);
  assert(job.metadata.state == HPLJ_JOB_FAILED);
  assert(fake.output_size == 0);

  job = make_job(&fake, &device);
  assert(hplj_job_prepare(&job, NULL, 0, "20050309").category ==
         HPLJ_ERROR_NONE);
  hplj_job_shutdown(&job);
  assert(job.metadata.state == HPLJ_JOB_CANCELED);
  assert(fake.releases > 0);
}

int main(void) {
  test_job_waits_for_firmware_then_completes_after_transmission();
  test_partial_transmission_requires_explicit_retry();
  test_zero_byte_failure_retries_but_partial_cancel_never_does();
  test_malformed_raster_is_rejected_before_encoding_or_output();
  test_failures_cancellation_limits_and_shutdown_release_resources();
  return 0;
}
