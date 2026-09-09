// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/device.h"
#include "hplj/pappl.h"
#include "hplj/usb_libusb.h"

#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

struct fake_usb {
  struct hplj_usb_descriptor descriptor;
  const char *identities[8];
  enum hplj_error_category identity_errors[8];
  size_t identity_count;
  size_t identity_index;
  enum hplj_error_category discover_errors[8];
  size_t discover_count;
  size_t discover_index;
  struct hplj_transfer_result writes[8];
  size_t write_count;
  size_t write_index;
  enum hplj_error_category upload_errors[8];
  size_t upload_error_count;
  unsigned int opens;
  unsigned int claims;
  unsigned int releases;
  unsigned int uploads;
  unsigned int conditions;
  enum hplj_error_category status_error;
};

static enum hplj_error_category fake_discover(void *context,
                                               struct hplj_usb_descriptor *descriptor) {
  struct fake_usb *usb = context;
  enum hplj_error_category error = HPLJ_ERROR_NONE;
  if (usb->discover_index < usb->discover_count) {
    error = usb->discover_errors[usb->discover_index++];
  }
  if (error == HPLJ_ERROR_NONE) {
    *descriptor = usb->descriptor;
  }
  return error;
}

static enum hplj_error_category fake_open(void *context) {
  struct fake_usb *usb = context;
  usb->opens++;
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category fake_claim(void *context) {
  struct fake_usb *usb = context;
  usb->claims++;
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category fake_identity(void *context, char *identity,
                                              size_t identity_size,
                                              size_t *identity_length) {
  struct fake_usb *usb = context;
  size_t index = usb->identity_index++;
  if (index < sizeof(usb->identity_errors) / sizeof(usb->identity_errors[0]) &&
      usb->identity_errors[index] != HPLJ_ERROR_NONE) {
    return usb->identity_errors[index];
  }
  assert(index < usb->identity_count);
  const char *source = usb->identities[index];
  size_t length = strlen(source);
  if (length + 1 > identity_size) {
    return HPLJ_ERROR_DEVICE_PROTOCOL;
  }
  memcpy(identity, source, length + 1);
  *identity_length = length;
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category fake_upload(void *context,
                                            const unsigned char *firmware,
                                            size_t firmware_size) {
  struct fake_usb *usb = context;
  assert(firmware != NULL);
  assert(firmware_size > 0);
  usb->uploads++;
  if (usb->uploads <= usb->upload_error_count) {
    return usb->upload_errors[usb->uploads - 1];
  }
  return HPLJ_ERROR_NONE;
}

static struct hplj_transfer_result fake_write(void *context,
                                               const unsigned char *bytes,
                                               size_t byte_count) {
  struct fake_usb *usb = context;
  assert(bytes != NULL);
  assert(byte_count > 0);
  if (usb->write_index < usb->write_count) {
    return usb->writes[usb->write_index++];
  }
  return (struct hplj_transfer_result){HPLJ_ERROR_NONE, byte_count};
}

static void fake_release(void *context) {
  struct fake_usb *usb = context;
  usb->releases++;
}

static enum hplj_error_category fake_status(void *context,
                                             unsigned int *conditions) {
  struct fake_usb *usb = context;
  *conditions = usb->conditions;
  return usb->status_error;
}

static struct hplj_device make_device(struct fake_usb *usb) {
  struct hplj_device device;
  const struct hplj_device_ops ops = {
      .discover = fake_discover,
      .open = fake_open,
      .claim_interface = fake_claim,
      .read_identity = fake_identity,
      .upload_firmware = fake_upload,
      .write = fake_write,
      .read_status = fake_status,
      .release = fake_release,
      .context = usb,
  };
  hplj_device_init(&device, &ops);
  return device;
}

static struct fake_usb reference_usb(void) {
  return (struct fake_usb){
      .descriptor = {HPLJ_REFERENCE_VENDOR_ID, HPLJ_REFERENCE_PRODUCT_ID},
      .identities = {"MFG:HP;MDL:HP LaserJet 1020;"},
      .identity_count = 1,
  };
}

static void test_discovery_requires_exact_descriptor_and_identity(void) {
  struct fake_usb usb = reference_usb();
  usb.descriptor.product_id = 0x2c17;
  struct hplj_device device = make_device(&usb);
  struct hplj_device_result result = hplj_device_connect(&device);
  assert(result.error.category == HPLJ_ERROR_UNSUPPORTED_DEVICE);
  assert(result.error.retry == HPLJ_RETRY_EXPLICIT);
  assert(device.state == HPLJ_DEVICE_UNSUPPORTED);
  assert(hplj_status_from_device(device.state).diagnostic ==
         HPLJ_ERROR_UNSUPPORTED_DEVICE);
  assert(usb.opens == 0);

  usb = reference_usb();
  usb.identities[0] = "MFG:HP;MDL:HP LaserJet 1022;";
  device = make_device(&usb);
  result = hplj_device_connect(&device);
  assert(result.error.category == HPLJ_ERROR_UNSUPPORTED_DEVICE);
  assert(result.error.retry == HPLJ_RETRY_EXPLICIT);
  assert(device.state == HPLJ_DEVICE_UNSUPPORTED);
  assert(hplj_status_from_device(device.state).queue == HPLJ_QUEUE_STOPPED);
  assert(usb.releases == 1);

  usb = reference_usb();
  usb.identities[0] =
      "CMD:ACL;MDL:HP LaserJet 1020;MFG:Hewlett-Packard;CLS:PRINTER;";
  device = make_device(&usb);
  result = hplj_device_connect(&device);
  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(device.state == HPLJ_DEVICE_PRE_FIRMWARE);
  assert(hplj_status_from_device(device.state).queue == HPLJ_QUEUE_HELD);
}

static void test_firmware_is_idempotent_and_verifies_expected_version(void) {
  const unsigned char firmware[] = {1, 2, 3};
  struct fake_usb usb = reference_usb();
  usb.identities[0] = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;";
  struct hplj_device device = make_device(&usb);
  assert(hplj_device_connect(&device).error.category == HPLJ_ERROR_NONE);
  assert(device.state == HPLJ_DEVICE_FIRMWARE_PRESENT);
  const unsigned char page[] = {9};
  assert(hplj_device_send(&device, page, sizeof(page), false).error.category ==
         HPLJ_ERROR_INVALID_STATE);
  struct hplj_device_result result = hplj_device_bootstrap_firmware(
      &device, firmware, sizeof(firmware), "20050309");
  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(result.error.retry == HPLJ_RETRY_SAFE_AUTOMATIC);
  assert(hplj_status_from_device(device.state).queue == HPLJ_QUEUE_READY);
  assert(usb.uploads == 0);

  usb = reference_usb();
  usb.identities[1] = "MFG:HP;MDL:HP LaserJet 1020;FWVER:wrong;";
  usb.identity_count = 2;
  device = make_device(&usb);
  assert(hplj_device_connect(&device).error.category == HPLJ_ERROR_NONE);
  result = hplj_device_bootstrap_firmware(&device, firmware, sizeof(firmware), "20050309");
  assert(result.error.category == HPLJ_ERROR_FIRMWARE_UNVERIFIED);
  assert(result.error.retry == HPLJ_RETRY_EXPLICIT);
  assert(device.state == HPLJ_DEVICE_FIRMWARE_UNVERIFIED);
  assert(hplj_status_from_device(device.state).queue == HPLJ_QUEUE_HELD);
  assert(usb.uploads == 1);
}

static void test_activation_survives_usb_reenumeration(void) {
  const unsigned char firmware[] = {1};
  struct fake_usb usb = reference_usb();
  usb.identities[1] = "";
  usb.identity_errors[1] = HPLJ_ERROR_DEVICE_DISCONNECTED;
  usb.identities[2] = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;";
  usb.identity_count = 3;
  struct hplj_device device = make_device(&usb);
  assert(hplj_device_connect(&device).error.category == HPLJ_ERROR_NONE);

  struct hplj_device_result result = hplj_device_bootstrap_firmware(
      &device, firmware, sizeof(firmware), "20050309");

  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(result.error.retry == HPLJ_RETRY_SAFE_AUTOMATIC);
  assert(result.attempts == 2);
  assert(device.state == HPLJ_DEVICE_READY);
  assert(hplj_status_from_device(device.state).queue == HPLJ_QUEUE_READY);
  assert(usb.uploads == 1);
  assert(usb.opens == 2);
  assert(usb.releases == 1);
}

static void test_activation_waits_for_firmware_version_without_reuploading(void) {
  const unsigned char firmware[] = {1};
  struct fake_usb usb = reference_usb();
  usb.identities[1] = "MFG:HP;MDL:HP LaserJet 1020;";
  usb.identities[2] = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;";
  usb.identity_count = 3;
  struct hplj_device device = make_device(&usb);
  assert(hplj_device_connect(&device).error.category == HPLJ_ERROR_NONE);

  struct hplj_device_result result = hplj_device_bootstrap_firmware(
      &device, firmware, sizeof(firmware), "20050309");

  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(result.error.retry == HPLJ_RETRY_SAFE_AUTOMATIC);
  assert(result.attempts == 2);
  assert(device.state == HPLJ_DEVICE_READY);
  assert(hplj_status_from_device(device.state).queue == HPLJ_QUEUE_READY);
  assert(usb.uploads == 1);
}

static void test_firmware_transfer_retries_only_to_the_bound(void) {
  const unsigned char firmware[] = {1};
  struct fake_usb usb = reference_usb();
  usb.upload_errors[0] = HPLJ_ERROR_DEVICE_TIMEOUT;
  usb.upload_error_count = 1;
  usb.identities[1] = "MFG:HP;MDL:HP LaserJet 1020;";
  usb.identities[2] = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;";
  usb.identity_count = 3;
  struct hplj_device device = make_device(&usb);
  assert(hplj_device_connect(&device).error.category == HPLJ_ERROR_NONE);

  struct hplj_device_result result = hplj_device_bootstrap_firmware(
      &device, firmware, sizeof(firmware), "20050309");

  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(result.attempts == 2);
  assert(usb.uploads == 2);

  usb = reference_usb();
  usb.upload_errors[0] = HPLJ_ERROR_DEVICE_TIMEOUT;
  usb.upload_errors[1] = HPLJ_ERROR_DEVICE_TIMEOUT;
  usb.upload_errors[2] = HPLJ_ERROR_DEVICE_TIMEOUT;
  usb.upload_error_count = 3;
  usb.identities[1] = "MFG:HP;MDL:HP LaserJet 1020;";
  usb.identities[2] = "MFG:HP;MDL:HP LaserJet 1020;";
  usb.identity_count = 3;
  device = make_device(&usb);
  assert(hplj_device_connect(&device).error.category == HPLJ_ERROR_NONE);
  result = hplj_device_bootstrap_firmware(
      &device, firmware, sizeof(firmware), "20050309");
  assert(result.error.category == HPLJ_ERROR_FIRMWARE_TRANSFER_FAILED);
  assert(result.error.retry == HPLJ_RETRY_EXPLICIT);
  assert(result.attempts == HPLJ_MAX_AUTOMATIC_ATTEMPTS);
  assert(device.state == HPLJ_DEVICE_FIRMWARE_TRANSFER_FAILED);
  assert(usb.uploads == HPLJ_MAX_AUTOMATIC_ATTEMPTS);
  assert(hplj_status_from_device(device.state).diagnostic ==
         HPLJ_ERROR_FIRMWARE_TRANSFER_FAILED);
}

static void test_reenumeration_rejects_identity_change(void) {
  const unsigned char firmware[] = {1};
  struct fake_usb usb = reference_usb();
  usb.identities[1] = "";
  usb.identity_errors[1] = HPLJ_ERROR_DEVICE_DISCONNECTED;
  usb.identities[2] = "MFG:HP;MDL:HP LaserJet 1022;FWVER:20050309;";
  usb.identity_count = 3;
  struct hplj_device device = make_device(&usb);
  assert(hplj_device_connect(&device).error.category == HPLJ_ERROR_NONE);

  struct hplj_device_result result = hplj_device_bootstrap_firmware(
      &device, firmware, sizeof(firmware), "20050309");

  assert(result.error.category == HPLJ_ERROR_UNSUPPORTED_DEVICE);
  assert(device.state == HPLJ_DEVICE_UNSUPPORTED);
  assert(result.error.retry == HPLJ_RETRY_EXPLICIT);
  assert(hplj_status_from_device(device.state).queue == HPLJ_QUEUE_STOPPED);
}

static void test_connect_retries_are_bounded_and_observable(void) {
  struct fake_usb usb = reference_usb();
  usb.discover_errors[0] = HPLJ_ERROR_DEVICE_TIMEOUT;
  usb.discover_errors[1] = HPLJ_ERROR_DEVICE_TIMEOUT;
  usb.discover_count = 2;
  struct hplj_device device = make_device(&usb);
  struct hplj_device_result result = hplj_device_connect(&device);
  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(result.attempts == 3);

  usb = reference_usb();
  usb.discover_errors[0] = HPLJ_ERROR_DEVICE_TIMEOUT;
  usb.discover_errors[1] = HPLJ_ERROR_DEVICE_TIMEOUT;
  usb.discover_errors[2] = HPLJ_ERROR_DEVICE_TIMEOUT;
  usb.discover_count = 3;
  device = make_device(&usb);
  result = hplj_device_connect(&device);
  assert(result.error.category == HPLJ_ERROR_DEVICE_TIMEOUT);
  assert(result.error.retry == HPLJ_RETRY_EXPLICIT);
  assert(result.attempts == HPLJ_MAX_AUTOMATIC_ATTEMPTS);
  assert(device.state == HPLJ_DEVICE_DISCONNECTED);
  assert(hplj_status_from_device(device.state).queue == HPLJ_QUEUE_HELD);
}

static void test_transfer_retry_boundary_is_job_bytes(void) {
  const unsigned char page[] = {1, 2, 3};
  struct fake_usb usb = reference_usb();
  usb.identities[0] = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;";
  usb.writes[0] = (struct hplj_transfer_result){HPLJ_ERROR_DEVICE_TIMEOUT, 0};
  usb.writes[1] = (struct hplj_transfer_result){HPLJ_ERROR_NONE, sizeof(page)};
  usb.write_count = 2;
  struct hplj_device device = make_device(&usb);
  struct hplj_device_result result = hplj_device_connect(&device);
  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(result.error.retry == HPLJ_RETRY_SAFE_AUTOMATIC);
  assert(hplj_device_bootstrap_firmware(&device, NULL, 0, "20050309")
             .error.category == HPLJ_ERROR_NONE);
  result = hplj_device_send(&device, page, sizeof(page), false);
  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(result.attempts == 2);
  assert(result.bytes_transferred == sizeof(page));

  usb = reference_usb();
  usb.identities[0] = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;";
  usb.writes[0] = (struct hplj_transfer_result){HPLJ_ERROR_DEVICE_TIMEOUT, 1};
  usb.write_count = 1;
  device = make_device(&usb);
  assert(hplj_device_connect(&device).error.category == HPLJ_ERROR_NONE);
  assert(hplj_device_bootstrap_firmware(&device, NULL, 0, "20050309")
             .error.category == HPLJ_ERROR_NONE);
  result = hplj_device_send(&device, page, sizeof(page), false);
  assert(result.error.category == HPLJ_ERROR_DEVICE_TIMEOUT);
  assert(result.error.retry == HPLJ_RETRY_EXPLICIT);
  assert(result.bytes_transferred == 1);
  assert(result.attempts == 1);
  assert(hplj_status_from_device(device.state).queue == HPLJ_QUEUE_HELD);

  usb = reference_usb();
  usb.identities[0] = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;";
  usb.writes[0] = (struct hplj_transfer_result){HPLJ_ERROR_NONE, sizeof(page) + 1};
  usb.write_count = 1;
  device = make_device(&usb);
  assert(hplj_device_connect(&device).error.category == HPLJ_ERROR_NONE);
  assert(hplj_device_bootstrap_firmware(&device, NULL, 0, "20050309")
             .error.category == HPLJ_ERROR_NONE);
  result = hplj_device_send(&device, page, sizeof(page), false);
  assert(result.error.category == HPLJ_ERROR_DEVICE_PROTOCOL);
  assert(result.error.retry == HPLJ_RETRY_EXPLICIT);
  assert(result.bytes_transferred == sizeof(page) + 1);
  assert(hplj_status_from_device(device.state).queue == HPLJ_QUEUE_HELD);
}

static void test_disconnect_and_sleep_invalidate_stale_handles(void) {
  struct fake_usb usb = reference_usb();
  usb.identities[0] = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;";
  usb.identities[1] = "MFG:HP;MDL:HP LaserJet 1020;";
  usb.identity_count = 2;
  struct hplj_device device = make_device(&usb);
  struct hplj_device_result result = hplj_device_connect(&device);
  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(hplj_device_bootstrap_firmware(&device, NULL, 0, "20050309")
             .error.category == HPLJ_ERROR_NONE);

  hplj_device_suspend(&device);
  assert(device.state == HPLJ_DEVICE_DISCONNECTED);
  struct hplj_status status = hplj_status_from_device(device.state);
  assert(status.queue == HPLJ_QUEUE_HELD);
  assert(status.action == HPLJ_ACTION_RECONNECT_PRINTER);
  assert(!device.opened);
  assert(usb.releases == 1);
  result = hplj_device_connect(&device);
  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(result.error.retry == HPLJ_RETRY_SAFE_AUTOMATIC);
  assert(device.state == HPLJ_DEVICE_PRE_FIRMWARE);
  assert(hplj_status_from_device(device.state).queue == HPLJ_QUEUE_HELD);

  hplj_device_disconnect(&device);
  assert(device.state == HPLJ_DEVICE_DISCONNECTED);
  assert(usb.releases == 2);
}

static void test_ready_device_power_cycle_returns_to_firmware_activation(void) {
  const unsigned char firmware[] = {1};
  struct fake_usb usb = reference_usb();
  usb.identities[0] = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;";
  usb.identities[1] = "MFG:HP;MDL:HP LaserJet 1020;";
  usb.identities[2] = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;";
  usb.identity_count = 3;
  struct hplj_device device = make_device(&usb);
  assert(hplj_device_connect(&device).error.category == HPLJ_ERROR_NONE);
  assert(hplj_device_bootstrap_firmware(&device, NULL, 0, "20050309")
             .error.category == HPLJ_ERROR_NONE);

  struct hplj_device_result result =
      hplj_device_revalidate(&device, "20050309");
  assert(result.error.category == HPLJ_ERROR_FIRMWARE_MISSING);
  assert(result.error.retry == HPLJ_RETRY_SAFE_AUTOMATIC);
  assert(device.state == HPLJ_DEVICE_PRE_FIRMWARE);
  assert(device.opened);
  assert(usb.releases == 0);

  result = hplj_device_bootstrap_firmware(&device, firmware, sizeof(firmware),
                                          "20050309");
  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(device.state == HPLJ_DEVICE_READY);
  assert(usb.uploads == 1);
}

static void test_ready_device_reports_actionable_port_status(void) {
  struct fake_usb usb = reference_usb();
  usb.identities[0] = "MFG:HP;MDL:HP LaserJet 1020;FWVER:20050309;";
  usb.conditions = HPLJ_DEVICE_CONDITION_MEDIA_EMPTY |
                   HPLJ_DEVICE_CONDITION_FAULT;
  struct hplj_device device = make_device(&usb);
  assert(hplj_device_connect(&device).error.category == HPLJ_ERROR_NONE);
  assert(hplj_device_bootstrap_firmware(&device, NULL, 0, "20050309")
             .error.category == HPLJ_ERROR_NONE);
  unsigned int conditions = 0;
  assert(hplj_device_get_status(&device, &conditions).error.category ==
         HPLJ_ERROR_NONE);
  assert(conditions == usb.conditions);

  usb.status_error = HPLJ_ERROR_DEVICE_DISCONNECTED;
  assert(hplj_device_get_status(&device, &conditions).error.category ==
         HPLJ_ERROR_DEVICE_DISCONNECTED);
  assert(device.state == HPLJ_DEVICE_DISCONNECTED);
  assert(!device.opened);
}

static void test_production_libusb_transport_binds_without_a_helper(void) {
  struct hplj_libusb_transport *transport = NULL;
  struct hplj_device_ops ops = {0};
  assert(hplj_libusb_transport_create(&transport) == HPLJ_ERROR_NONE);
  assert(transport != NULL);
  hplj_libusb_device_ops(transport, &ops);
  assert(ops.discover != NULL);
  assert(ops.open != NULL);
  assert(ops.claim_interface != NULL);
  assert(ops.read_identity != NULL);
  assert(ops.upload_firmware != NULL);
  assert(ops.write != NULL);
  assert(ops.release != NULL);
  assert(ops.context == transport);
  hplj_libusb_transport_destroy(transport);
}

int main(void) {
  test_discovery_requires_exact_descriptor_and_identity();
  test_firmware_is_idempotent_and_verifies_expected_version();
  test_activation_survives_usb_reenumeration();
  test_activation_waits_for_firmware_version_without_reuploading();
  test_firmware_transfer_retries_only_to_the_bound();
  test_reenumeration_rejects_identity_change();
  test_connect_retries_are_bounded_and_observable();
  test_transfer_retry_boundary_is_job_bytes();
  test_disconnect_and_sleep_invalidate_stale_handles();
  test_ready_device_power_cycle_returns_to_firmware_activation();
  test_ready_device_reports_actionable_port_status();
  test_production_libusb_transport_binds_without_a_helper();
  return 0;
}
