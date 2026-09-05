// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/device.h"
#include "hplj/encoder.h"
#include "hplj/pappl.h"
#include "hplj/version.h"

#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>

struct fake_device {
  const char *identity;
  size_t write_limit;
  size_t written;
  bool firmware_uploaded;
};

static enum hplj_error_category fake_open(void *context) {
  (void)context;
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category fake_discover_exact(void *context) {
  (void)context;
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category fake_claim_interface(void *context) {
  (void)context;
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category fake_identity(void *context, char *identity,
                                              size_t identity_size, size_t *identity_length) {
  struct fake_device *device = context;
  const char *source = device->firmware_uploaded ? "MFG:HP;MDL:HP LaserJet 1020;FWVER:1;"
                                                  : device->identity;
  if (strlen(source) + 1 > identity_size) {
    return HPLJ_ERROR_DEVICE_PROTOCOL;
  }
  memcpy(identity, source, strlen(source) + 1);
  *identity_length = strlen(source);
  return HPLJ_ERROR_NONE;
}

static void fake_release(void *context) {
  (void)context;
}

static enum hplj_error_category fake_upload(void *context, const unsigned char *firmware,
                                            size_t firmware_size) {
  struct fake_device *device = context;
  if (firmware == NULL || firmware_size == 0) {
    return HPLJ_ERROR_FIRMWARE_MISSING;
  }
  device->firmware_uploaded = true;
  return HPLJ_ERROR_NONE;
}

static struct hplj_transfer_result fake_write(void *context, const unsigned char *bytes,
                                              size_t byte_count) {
  struct fake_device *device = context;
  (void)bytes;
  size_t transferred = byte_count < device->write_limit ? byte_count : device->write_limit;
  device->written += transferred;
  return (struct hplj_transfer_result){
      .category = transferred == byte_count ? HPLJ_ERROR_NONE : HPLJ_ERROR_DEVICE_DISCONNECTED,
      .bytes_transferred = transferred,
  };
}

static void test_device_rejects_invalid_transition(void) {
  struct fake_device fake = {.identity = "MFG:HP;MDL:HP LaserJet 1020;", .write_limit = 64};
  struct hplj_device device;
  hplj_device_init(&device, &(struct hplj_device_ops){
      .discover_exact = fake_discover_exact, .open = fake_open,
      .claim_interface = fake_claim_interface, .read_identity = fake_identity,
      .upload_firmware = fake_upload, .write = fake_write, .release = fake_release, .context = &fake,
  });

  const unsigned char page[] = {1, 2, 3};
  struct hplj_device_result operation = hplj_device_send(&device, page, sizeof(page), false);
  assert(operation.error.category == HPLJ_ERROR_INVALID_STATE);
  assert(operation.error.retry == HPLJ_RETRY_NEVER);
  assert(device.state == HPLJ_DEVICE_DISCONNECTED);
}

static void test_partial_send_requires_explicit_retry(void) {
  struct fake_device fake = {.identity = "MFG:HP;MDL:HP LaserJet 1020;", .write_limit = 2};
  struct hplj_device device;
  hplj_device_init(&device, &(struct hplj_device_ops){
      .discover_exact = fake_discover_exact, .open = fake_open,
      .claim_interface = fake_claim_interface, .read_identity = fake_identity,
      .upload_firmware = fake_upload, .write = fake_write, .release = fake_release, .context = &fake,
  });
  assert(hplj_device_connect(&device).error.category == HPLJ_ERROR_NONE);
  const unsigned char firmware[] = {0x01};
  assert(hplj_device_bootstrap_firmware(&device, firmware, sizeof(firmware)).error.category ==
         HPLJ_ERROR_NONE);

  const unsigned char page[] = {1, 2, 3};
  struct hplj_device_result operation = hplj_device_send(&device, page, sizeof(page), false);
  assert(operation.error.category == HPLJ_ERROR_DEVICE_DISCONNECTED);
  assert(operation.error.retry == HPLJ_RETRY_EXPLICIT);
  assert(operation.bytes_transferred == 2);
  assert(device.state == HPLJ_DEVICE_DISCONNECTED);
}

struct fake_sink {
  size_t bytes_written;
};

static enum hplj_error_category fake_emit(void *context, const unsigned char *bytes,
                                          size_t byte_count) {
  struct fake_sink *sink = context;
  (void)bytes;
  sink->bytes_written += byte_count;
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category fake_encode(void *context, const struct hplj_raster *raster,
                                            const struct hplj_encoder_sink *sink,
                                            bool cancelled, size_t *bytes_emitted) {
  (void)context;
  if (cancelled) {
    return HPLJ_ERROR_CANCELLED;
  }
  *bytes_emitted = raster->row_stride_bytes * raster->height_rows;
  return sink->emit(sink->context, raster->bits, *bytes_emitted);
}

static void test_encoder_rejects_invalid_raster_before_output(void) {
  struct fake_sink sink = {0};
  const unsigned char row[] = {0};
  struct hplj_raster raster = {
      .width_pixels = 8, .height_rows = 1, .resolution_dpi = 600,
      .row_stride_bytes = 0, .bits = row, .bit_polarity = HPLJ_BLACK_IS_ONE,
      .page_count = 1, .media = HPLJ_MEDIA_A4, .source = HPLJ_SOURCE_AUTO,
      .quality = HPLJ_QUALITY_NORMAL, .density = 3,
  };
  struct hplj_encode_result result = hplj_encode_raster(
      &(struct hplj_foo2zjs_adapter){.encode_zjstream = fake_encode, .context = NULL}, &raster,
      &(struct hplj_encoder_sink){.emit = fake_emit, .context = &sink}, false);
  assert(result.error.category == HPLJ_ERROR_RASTER_INVALID);
  assert(sink.bytes_written == 0);
}

static void test_pappl_mapping_hides_external_types(void) {
  struct hplj_status status = hplj_status_from_device(HPLJ_DEVICE_AWAITING_FIRMWARE);
  assert(status.queue == HPLJ_QUEUE_HELD);
  assert(status.action == HPLJ_ACTION_IMPORT_FIRMWARE);
  assert(strcmp(hplj_product_version(), "0.1.0") == 0);
  assert(strcmp(hplj_dependency_version("pappl"), "1.4.12") == 0);
  assert(strcmp(hplj_dependency_version("libusb"), "1.0.30") == 0);
}

struct fake_pappl {
  unsigned int publishes;
  struct hplj_status status;
};

static void fake_publish(void *context, struct hplj_status status) {
  struct fake_pappl *pappl = context;
  pappl->publishes++;
  pappl->status = status;
}

static void test_pappl_adapter_accepts_a_host_test_double(void) {
  struct fake_pappl pappl = {0};
  const struct hplj_service_config config = {
      .queue_name = "HP_LaserJet_1020", .loopback_host = "127.0.0.1",
      .ipp_port = 8631, .firmware_path = "/private/firmware",
  };
  hplj_pappl_publish_status(&config, NULL, fake_publish, &pappl,
                            HPLJ_DEVICE_AWAITING_FIRMWARE);
  assert(pappl.publishes == 1);
  assert(pappl.status.queue == HPLJ_QUEUE_HELD);
}

int main(void) {
  test_device_rejects_invalid_transition();
  test_partial_send_requires_explicit_retry();
  test_encoder_rejects_invalid_raster_before_output();
  test_pappl_mapping_hides_external_types();
  test_pappl_adapter_accepts_a_host_test_double();
  return 0;
}
